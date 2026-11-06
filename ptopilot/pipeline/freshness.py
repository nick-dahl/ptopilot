"""What counts as a fresh live price, and how stale a day's route queries are.

A route query is *fresh* on a run date when it has an `ok` live check of purpose 'trip' that day, from any
source: a successful check that found no flights is still a fresh answer, and a SerpApi check counts like
a Google one. Failed checks, and the return-leg searches of instant alerts, never count.
`google_fresh_on` counts only unbudgeted sources, so SerpApi spend can be planned around what free Google
already covered.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.db.models import LiveCheck, RouteQuery, Tracker, TrackerRouteLink


def _ok_trip_checks():
    return (LiveCheck.ok.is_(True), LiveCheck.purpose == "trip")


def last_fresh(s: Session, rq_ids: Iterable[int], before: datetime | None = None) -> dict[int, datetime]:
    """Latest time each route query had a fresh check (only checks before `before`, if given)."""
    stmt = (
        select(LiveCheck.route_query_id, func.max(LiveCheck.checked_at))
        .where(LiveCheck.route_query_id.in_(list(rq_ids)), *_ok_trip_checks())
        .group_by(LiveCheck.route_query_id)
    )
    if before is not None:
        stmt = stmt.where(LiveCheck.checked_at < before)
    return dict(s.execute(stmt).all())


def fresh_on(s: Session, day: date) -> set[int]:
    """Route queries with a fresh check on this run date, from any source."""
    return set(
        s.scalars(select(LiveCheck.route_query_id).where(LiveCheck.run_date == day, *_ok_trip_checks()))
    )


def google_fresh_on(s: Session, day: date) -> set[int]:
    """Like `fresh_on`, counting only unbudgeted sources."""
    return set(
        s.scalars(
            select(LiveCheck.route_query_id).where(
                LiveCheck.run_date == day,
                LiveCheck.source.not_in(list(config.SOURCE_BUDGETS)),
                *_ok_trip_checks(),
            )
        )
    )


@dataclass(frozen=True)
class DayFreshness:
    in_horizon: int
    fresh: int
    not_fresh: list[int]  # worth retrying: failed by outage or not attempted yet
    unpriceable: list[int]  # every attempt today failed for a reason about the route itself
    open_jaw_no_budget: list[int]  # open-jaw, never attempted (only budgeted SerpApi can price them)
    longest_wait_days: int  # longest time a not-fresh route has gone without a fresh price


def day_freshness(s: Session, day: date) -> DayFreshness:
    """Freshness of every route query an active tracker wants on this run date within the live horizon."""
    wanted = (
        select(TrackerRouteLink.route_query_id)
        .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
        .where(TrackerRouteLink.run_date == day, Tracker.active.is_(True))
    )
    rqs = [
        rq
        for rq in s.scalars(select(RouteQuery).where(RouteQuery.id.in_(wanted)).order_by(RouteQuery.id))
        if (rq.depart_date - day).days <= config.LIVE_HORIZON_DAYS
    ]
    fresh = fresh_on(s, day)
    attempts: dict[int, list[bool]] = {}
    for rq_id, specific in s.execute(
        select(LiveCheck.route_query_id, LiveCheck.route_specific).where(
            LiveCheck.run_date == day,
            LiveCheck.purpose == "trip",
            LiveCheck.route_query_id.in_([rq.id for rq in rqs]),
        )
    ):
        attempts.setdefault(rq_id, []).append(specific)

    not_fresh: list[int] = []
    unpriceable: list[int] = []
    open_jaw: list[int] = []
    for rq in rqs:
        if rq.id in fresh:
            continue
        tried = attempts.get(rq.id)
        if tried and all(tried):
            unpriceable.append(rq.id)
        elif not tried and rq.return_airport != rq.dest_airport:
            open_jaw.append(rq.id)
        else:
            not_fresh.append(rq.id)

    longest = 0
    if not_fresh:
        seen = last_fresh(s, not_fresh)
        first_link = dict(
            s.execute(
                select(TrackerRouteLink.route_query_id, func.min(TrackerRouteLink.run_date))
                .where(TrackerRouteLink.route_query_id.in_(not_fresh))
                .group_by(TrackerRouteLink.route_query_id)
            ).all()
        )
        for rq_id in not_fresh:
            if rq_id in seen:
                waited = (day - seen[rq_id].date()).days
            else:
                waited = max((day - first_link[rq_id]).days, 1)
            longest = max(longest, waited)
    n_fresh = len(rqs) - len(not_fresh) - len(unpriceable) - len(open_jaw)
    return DayFreshness(len(rqs), n_fresh, not_fresh, unpriceable, open_jaw, longest)
