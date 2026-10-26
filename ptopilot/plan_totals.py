"""A planning year's PTO in numbers: booked trips at their real PTO, planned trips at an estimate.

The planner page, the deal notes and the email share these. Every function acts on the given user's rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ptopilot.core.geo import Geo, UnknownCodeError
from ptopilot.core.planner import TrackerSpec, Window, estimate_pto
from ptopilot.core.seasons import SeasonTable
from ptopilot.db.models import PlannedTrip, PlanningYear, User
from ptopilot.pipeline.expand import profile_for
from ptopilot.planning import booked_trips, year_ranges, year_trackers


@dataclass(frozen=True)
class YearTotals:
    year: int
    pto_days: int
    other_time_off: int
    booked: int
    planned: int

    @property
    def available(self) -> int:
        return self.pto_days - self.other_time_off

    @property
    def remaining(self) -> int:
        """What is left once booked trips are paid for; deal notes compare against this."""
        return self.available - self.booked

    @property
    def left(self) -> int:
        """What is left once the planned trips are paid for too; the banner shows this."""
        return self.remaining - self.planned


def trip_estimates(
    s: Session, user: User, year: int, geo: Geo, seasons: SeasonTable
) -> dict[int, int | None]:
    """The estimated PTO of each unbooked planned trip in the year, by tracker id."""
    booked = {b.tracker_id for b in booked_trips(s, user, [year], geo=geo)}
    profile = profile_for(user)
    windows = [Window(a, b) for a, b in year_ranges(s, user, year)]
    estimates: dict[int, int | None] = {}
    for t in year_trackers(s, user, year):
        if t.id in booked:
            continue
        spec = TrackerSpec(t.destination_code, t.min_stay_days, t.max_stay_days, t.target_days)
        try:
            estimates[t.id] = estimate_pto(profile, spec, windows, geo, seasons)
        except UnknownCodeError:
            continue
    return estimates


def year_totals(
    s: Session,
    user: User,
    year: int,
    geo: Geo,
    seasons: SeasonTable,
    *,
    estimates: Mapping[int, int | None] | None = None,
) -> YearTotals | None:
    py = s.get(PlanningYear, (user.id, year))
    if py is None:
        return None
    if estimates is None:
        estimates = trip_estimates(s, user, year, geo, seasons)
    return YearTotals(
        year=year,
        pto_days=py.pto_days,
        other_time_off=py.other_time_off,
        booked=sum(b.pto_cost for b in booked_trips(s, user, [year], geo=geo)),
        planned=sum(e for e in estimates.values() if e is not None),
    )


def remaining_by_year(s: Session, user: User, years: Iterable[int]) -> dict[int, int]:
    """PTO left after booked trips, per year, without estimating anything. Years not planned are absent."""
    years = set(years)
    booked = dict(
        s.execute(
            select(PlannedTrip.year, func.coalesce(func.sum(PlannedTrip.booked_pto), 0))
            .where(PlannedTrip.user_id == user.id, PlannedTrip.year.in_(years))
            .group_by(PlannedTrip.year)
        ).all()
    )
    rows = s.execute(
        select(PlanningYear.year, PlanningYear.pto_days, PlanningYear.other_time_off).where(
            PlanningYear.user_id == user.id, PlanningYear.year.in_(years)
        )
    )
    return {y: pto - other - int(booked.get(y, 0)) for y, pto, other in rows}
