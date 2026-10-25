"""The planning year: the PTO a user plans to spend, their open date ranges and the trips picked for it.

    python -m ptopilot.planning convert-targets [--dry-run]

Every function takes a Session and acts only on the given user's rows. The caller commits.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable
from datetime import date

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.geo import Geo, UnknownCodeError
from ptopilot.core.yearplan import merge_ranges
from ptopilot.data import load_geo
from ptopilot.db.models import PlannedTrip, PlanningYear, Tracker, TravelWindow, User
from ptopilot.db.session import make_engine
from ptopilot.settings import Settings

MIN_TARGET_DAYS, MAX_TARGET_DAYS = 2, 60


def planning_years(s: Session, user: User) -> list[PlanningYear]:
    return list(
        s.scalars(select(PlanningYear).where(PlanningYear.user_id == user.id).order_by(PlanningYear.year))
    )


def current_year(s: Session, user: User, today: date) -> PlanningYear | None:
    return s.scalars(
        select(PlanningYear)
        .where(PlanningYear.user_id == user.id, PlanningYear.year >= today.year)
        .order_by(PlanningYear.year)
    ).first()


def default_new_year(s: Session, user: User, today: date) -> int:
    years = planning_years(s, user)
    if years:
        return years[-1].year + 1
    return today.year + 1 if today.month >= config.PLAN_NEXT_YEAR_FROM_MONTH else today.year


def _check_pto(pto_days: int, other_time_off: int) -> None:
    if not 0 <= other_time_off <= pto_days <= config.MAX_PTO_DAYS:
        raise ValueError(f"PTO must satisfy 0 <= days already committed <= PTO days <= {config.MAX_PTO_DAYS}")


def start_year(
    s: Session,
    user: User,
    year: int,
    pto_days: int,
    other_time_off: int,
    carry_tracker_ids: Iterable[int],
    *,
    today: date,
) -> PlanningYear:
    existing = s.get(PlanningYear, (user.id, year))
    if existing is not None:
        return existing
    if not today.year <= year <= today.year + config.PLAN_YEARS_AHEAD:
        raise ValueError(f"year must be {today.year} to {today.year + config.PLAN_YEARS_AHEAD}")
    _check_pto(pto_days, other_time_off)
    row = PlanningYear(user_id=user.id, year=year, pto_days=pto_days, other_time_off=other_time_off)
    s.add(row)
    ids = set(carry_tracker_ids)
    if ids:
        trackers = s.scalars(
            select(Tracker).where(Tracker.id.in_(ids), Tracker.user_id == user.id, Tracker.active.is_(True))
        )
        s.add_all(PlannedTrip(user_id=user.id, year=year, tracker_id=t.id) for t in trackers)
    s.flush()
    return row


def set_year_pto(s: Session, user: User, year: int, pto_days: int, other_time_off: int) -> None:
    _check_pto(pto_days, other_time_off)
    row = s.get(PlanningYear, (user.id, year))
    if row is not None:
        row.pto_days, row.other_time_off = pto_days, other_time_off
        s.flush()


def _year_windows(user: User, year: int):
    """Where clauses for the user's open ranges in a year: those whose start date falls in it."""
    return (
        TravelWindow.user_id == user.id,
        TravelWindow.start_date >= date(year, 1, 1),
        TravelWindow.start_date <= date(year, 12, 31),
    )


def year_ranges(s: Session, user: User, year: int) -> list[tuple[date, date]]:
    rows = s.execute(
        select(TravelWindow.start_date, TravelWindow.end_date)
        .where(*_year_windows(user, year))
        .order_by(TravelWindow.start_date, TravelWindow.end_date)
    )
    return [(a, b) for a, b in rows]


def set_ranges(
    s: Session, user: User, year: int, ranges: Iterable[tuple[date, date]]
) -> list[tuple[date, date]]:
    ranges = list(ranges)
    for i, (start, end) in enumerate(ranges):
        if start > end:
            raise ValueError(f"range {i + 1}: ends {end} before it starts {start}")
        if start.year != year:
            raise ValueError(f"range {i + 1}: starts {start}, which is not in {year}")
    merged = merge_ranges(ranges)
    s.execute(delete(TravelWindow).where(*_year_windows(user, year)))
    s.add_all(TravelWindow(user_id=user.id, start_date=a, end_date=b) for a, b in merged)
    s.flush()
    return merged


def year_trackers(s: Session, user: User, year: int) -> list[Tracker]:
    return list(
        s.scalars(
            select(Tracker)
            .join(PlannedTrip, PlannedTrip.tracker_id == Tracker.id)
            .where(PlannedTrip.user_id == user.id, PlannedTrip.year == year, Tracker.active.is_(True))
            .order_by(Tracker.priority, Tracker.id)
        )
    )


def plan_trip(s: Session, user: User, tracker: Tracker, year: int) -> None:
    taken = s.scalar(select(exists().where(PlannedTrip.tracker_id == tracker.id, PlannedTrip.year == year)))
    if not taken:
        s.add(PlannedTrip(user_id=user.id, year=year, tracker_id=tracker.id))
        s.flush()


def unplan_trip(s: Session, user: User, tracker_id: int, year: int, *, today: date) -> bool:
    """Take a destination out of a year. One planned in no remaining year stops being tracked."""
    tracker = s.get(Tracker, tracker_id)
    if tracker is None or tracker.user_id != user.id:
        return False
    s.execute(delete(PlannedTrip).where(PlannedTrip.tracker_id == tracker_id, PlannedTrip.year == year))
    s.flush()
    still_planned = s.scalar(
        select(exists().where(PlannedTrip.tracker_id == tracker_id, PlannedTrip.year >= today.year))
    )
    if not still_planned:
        tracker.active = False
        s.flush()
    return True


def set_target(s: Session, user: User, tracker_id: int, target_days: int) -> bool:
    if not MIN_TARGET_DAYS <= target_days <= MAX_TARGET_DAYS:
        raise ValueError(f"days away must be {MIN_TARGET_DAYS} to {MAX_TARGET_DAYS}")
    tracker = s.get(Tracker, tracker_id)
    if tracker is None or tracker.user_id != user.id:
        return False
    tracker.target_days = target_days
    tracker.min_stay_days = max(target_days - 2 - 1, 1)
    tracker.max_stay_days = target_days + 2
    s.flush()
    return True


def convert_targets(s: Session, geo: Geo) -> int:
    """Give every tracker without a target the midpoint of its stay range, as days away from home."""
    changed = 0
    rows = s.execute(
        select(Tracker, User.home_airport)
        .join(User, User.id == Tracker.user_id)
        .where(Tracker.target_days.is_(None))
    ).all()
    for tracker, home in rows:
        try:
            rule = geo.travel_rule(home, geo.destination(tracker.destination_code))
        except UnknownCodeError:
            continue
        days = math.floor((tracker.min_stay_days + tracker.max_stay_days) / 2 + rule.overhead_days + 0.5)
        tracker.target_days = min(max(days, MIN_TARGET_DAYS), MAX_TARGET_DAYS)
        changed += 1
    s.flush()
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.planning")
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser(
        "convert-targets", help="give trackers without a target the middle of their stay"
    )
    convert.add_argument("--dry-run", action="store_true", help="show the count without saving")
    args = parser.parse_args(argv)

    engine = make_engine(Settings.from_env().database_url)
    geo = load_geo(engine)
    with Session(engine) as s:
        n = convert_targets(s, geo)
        if args.dry_run:
            s.rollback()
        else:
            s.commit()
    print(f"converted {n} trackers" + (" (dry run, nothing saved)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
