"""What the year planner page shows: trips with a bottom line, the PTO budget and a 12-month calendar."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Engine

from ptopilot import config
from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Destination, Geo, UnknownCodeError, palette
from ptopilot.core.planner import TrackerSpec, Window, estimate_pto, target_band
from ptopilot.core.seasons import SeasonTable
from ptopilot.core.yearplan import allocate_pto, month_grid
from ptopilot.db.models import PlanningYear, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.expand import profile_for
from ptopilot.planning import year_ranges, year_trackers
from ptopilot.web.history import building_history


def fewest_days_away(geo: Geo, homes: Sequence[str], dest: Destination) -> int:
    """The shortest trip to this place from any of the homes (0 when a route is unknown)."""
    try:
        return min(geo.travel_rule(h, dest).min_trip_days for h in homes)
    except UnknownCodeError:
        return 0


def too_short(geo: Geo, homes: Sequence[str], dest: Destination, target_days: int | None) -> int | None:
    """The fewest days away trips there take, when the target is shorter than that."""
    if target_days is None:
        return None
    needed = fewest_days_away(geo, homes, dest)
    return needed if target_days < needed else None


def _months(year: int, cal: WorkCalendar, open_ranges: Sequence[tuple[date, date]]):
    def cell(d: date | None):
        if d is None:
            return None
        return {
            "date": d,
            "weekend": d.weekday() >= 5,
            "holiday": cal.holiday_name(d),
            "day_off": d in cal.extra_days_off,
            "open": any(a <= d <= b for a, b in open_ranges),
        }

    return [
        (calendar.month_name[m], [[cell(d) for d in week] for week in month_grid(year, m)])
        for m in range(1, 13)
    ]


def blank_range_rows(saved: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    rows = [{"start": a, "end": b} for a, b in saved]
    return rows + [{"start": "", "end": ""} for _ in range(config.EXTRA_RANGE_ROWS)]


def plan_context(
    engine: Engine, geo: Geo, seasons: SeasonTable, user_id: int, year: int, today: date
) -> dict | None:
    """Everything the page needs, or None when the user has no such planning year."""
    with session_scope(engine) as s:
        user = s.get(User, user_id)
        py = s.get(PlanningYear, (user_id, year)) if user else None
        if py is None:
            return None
        homes = [user.home_airport, *user.nearby_airports]
        profile = profile_for(user)
        saved = year_ranges(s, user, year)
        windows = [Window(a, b) for a, b in saved]
        available = py.pto_days - py.other_time_off
        entries = []
        for t in year_trackers(s, user, year):
            try:
                dest = geo.destination(t.destination_code)
            except UnknownCodeError:
                continue
            spec = TrackerSpec(t.destination_code, t.min_stay_days, t.max_stay_days, t.target_days)
            needed = fewest_days_away(geo, homes, dest)
            band = (
                target_band(t.target_days, config.TARGET_TOLERANCE_DAYS, needed)
                if t.target_days is not None
                else None
            )
            entries.append(
                {
                    "tracker_id": t.id,
                    "name": dest.name,
                    "palette": palette(dest),
                    "target_days": t.target_days,
                    "band": band,
                    "est_pto": estimate_pto(profile, spec, windows, geo, seasons),
                    "min_trip": too_short(geo, homes, dest, t.target_days),
                    "building_history": building_history(s, homes, dest),
                    "snoozed_until": t.snoozed_until
                    if t.snoozed_until and t.snoozed_until >= today
                    else None,
                }
            )
        over = allocate_pto([(e["tracker_id"], e["est_pto"]) for e in entries], available)
        for e in entries:
            e["wont_fit"] = over.get(e["tracker_id"])
        cal = WorkCalendar.from_code(user.holiday_calendar, user.extra_days_off, user.ignored_holidays)
        return {
            "year": year,
            "pto_days": py.pto_days,
            "other_time_off": py.other_time_off,
            "available": available,
            "trips": entries,
            "totals": {
                "trips": len(entries),
                "days_away": sum(e["target_days"] or 0 for e in entries),
                "est_pto": sum(e["est_pto"] for e in entries if e["est_pto"] is not None),
            },
            "months": _months(year, cal, saved),
            "ranges": blank_range_rows([(a.isoformat(), b.isoformat()) for a, b in saved]),
        }
