"""Stage `expand`: turn every active tracker into today's route queries (spec §7).

The season filter (spec's separate `season_filter` stage) happens inside core.planner, before
top-N pruning, so it is not a stage of its own.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import UnknownCodeError
from ptopilot.core.planner import PlannedItinerary, TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.db.models import (
    PlannedTrip,
    PlanningYear,
    RouteQuery,
    Tracker,
    TrackerExclusion,
    TrackerRouteLink,
    TravelWindow,
    User,
)
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext

log = logging.getLogger(__name__)


def profile_for(user: User, pto_available: int | None = None) -> TravelerProfile:
    return TravelerProfile(
        home_airports=(user.home_airport, *user.nearby_airports),
        calendar=WorkCalendar.from_code(user.holiday_calendar, user.extra_days_off, user.ignored_holidays),
        pto_available=user.pto_days_total - user.pto_committed if pto_available is None else pto_available,
        min_trip_days=user.min_trip_days,
        max_trip_days=user.max_trip_days,
        weather_tolerance=user.weather_tolerance,  # type: ignore[arg-type]
        friday_evening_departure=user.friday_evening_departure,
        ideal_trip_days=user.ideal_trip_days,
    )


def _route_query_id(s: Session, it: PlannedItinerary, cache: dict) -> int:
    key = (it.origin, it.dest_airport, it.return_airport, it.shape.depart_date, it.shape.return_date)
    if key not in cache:
        names = ("origin", "dest_airport", "return_airport", "depart_date", "return_date")
        values = dict(zip(names, key, strict=True))
        s.execute(insert(RouteQuery).values(**values).on_conflict_do_nothing())
        cache[key] = s.scalar(select(RouteQuery.id).filter_by(**values))
    return cache[key]


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    tomorrow = ctx.run_date + timedelta(days=1)
    with session_scope(ctx.engine) as s:
        s.execute(delete(TrackerRouteLink).where(TrackerRouteLink.run_date == ctx.run_date))
        rows = s.execute(
            select(Tracker, User)
            .join(User, Tracker.user_id == User.id)
            .where(
                Tracker.active.is_(True),
                or_(Tracker.snoozed_until.is_(None), Tracker.snoozed_until < ctx.run_date),
            )
            .order_by(Tracker.id)
        ).all()
        pto_left = {
            (py.user_id, py.year): py.pto_days - py.other_time_off for py in s.scalars(select(PlanningYear))
        }
        planned: defaultdict[int, set[int]] = defaultdict(set)
        for pt in s.scalars(select(PlannedTrip).where(PlannedTrip.booked_depart.is_(None))):
            planned[pt.tracker_id].add(pt.year)  # a booked trip is no longer searched
        windows: defaultdict[tuple[int, int], list[Window]] = defaultdict(list)  # (user, year of the range)
        for w in s.scalars(select(TravelWindow).where(TravelWindow.end_date >= tomorrow)):
            windows[w.user_id, w.start_date.year].append(Window(max(w.start_date, tomorrow), w.end_date))
        excluded = {(e.tracker_id, e.depart_date, e.return_date) for e in s.scalars(select(TrackerExclusion))}

        cache: dict = {}
        for tracker, user in rows:
            counts["trackers"] += 1
            years = sorted(
                y for y in planned[tracker.id] if (user.id, y) in pto_left and windows.get((user.id, y))
            )
            if not years:
                counts["trackers_without_windows"] += 1
                continue
            try:
                spec = TrackerSpec(
                    tracker.destination_code,
                    tracker.min_stay_days,
                    tracker.max_stay_days,
                    tracker.target_days,
                )
                itineraries = [
                    it
                    for y in years
                    for it in plan_itineraries(
                        profile_for(user, pto_left[user.id, y]),
                        spec,
                        windows[user.id, y],
                        ctx.geo,
                        ctx.seasons,
                    )
                ]
            except (UnknownCodeError, ValueError, ArithmeticError) as exc:
                counts["tracker_errors"] += 1
                log.warning("tracker %s skipped: %s", tracker.id, exc)
                continue
            linked: set[tuple[int, bool]] = set()  # years' ranges can overlap: keep the first of a repeat
            for it in itineraries:
                shape = it.shape
                if shape.depart_date < tomorrow:
                    continue
                if (tracker.id, shape.depart_date, shape.return_date) in excluded:
                    counts["excluded"] += 1
                    continue
                route_query_id = _route_query_id(s, it, cache)
                if (route_query_id, shape.evening_departure) in linked:
                    continue
                linked.add((route_query_id, shape.evening_departure))
                s.add(
                    TrackerRouteLink(
                        tracker_id=tracker.id,
                        route_query_id=route_query_id,
                        run_date=ctx.run_date,
                        evening_departure=shape.evening_departure,
                        pto_cost=shape.pto_cost,
                        days_away=shape.days_away,
                        efficiency=shape.efficiency,
                        month=it.month,
                        season_rating=it.season_rating,
                        days_off=list(shape.days_off),
                    )
                )
                counts["links"] += 1
        counts["route_queries"] = len(cache)
    return dict(counts)
