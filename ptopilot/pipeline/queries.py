"""Queries shared by several stages.

A route is (origin, fly-into airport, fly-home-from airport); the last two differ only for open-jaw
trips. Every key below includes all three, so a round trip to Porto and an open-jaw into Porto
never share prices or baselines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.stats import Baseline, length_bucket
from ptopilot.db.models import PriceObservation, RouteBaseline, RouteQuery, TrackerRouteLink

Route = tuple[str, str, str]  # origin, dest_airport, return_airport
DateKey = tuple[str, str, str, date, date]  # route + depart, return
BaselineKey = tuple[str, str, str, date, str]  # route + month, length_bucket


def month_of(d: date) -> date:
    return d.replace(day=1)


def start_of(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def date_key(rq: RouteQuery | PriceObservation) -> DateKey:
    return (rq.origin, rq.dest_airport, rq.return_airport, rq.depart_date, rq.return_date)


def baseline_key(origin: str, dest: str, return_airport: str, depart: date, ret: date) -> BaselineKey:
    return (origin, dest, return_airport, month_of(depart), length_bucket((ret - depart).days + 1))


def rq_baseline_key(rq: RouteQuery) -> BaselineKey:
    return baseline_key(rq.origin, rq.dest_airport, rq.return_airport, rq.depart_date, rq.return_date)


def todays_route_queries(s: Session, run_date: date) -> list[RouteQuery]:
    """Route queries any tracker wants on this run."""
    linked = select(TrackerRouteLink.route_query_id).where(TrackerRouteLink.run_date == run_date)
    return list(s.scalars(select(RouteQuery).where(RouteQuery.id.in_(linked)).order_by(RouteQuery.id)))


@dataclass(frozen=True)
class CachedPrice:
    observation_id: int
    price: Decimal


def cached_prices(
    s: Session, rqs: list[RouteQuery], run_date: date
) -> tuple[dict[DateKey, CachedPrice], dict[tuple[str, str, str, date], CachedPrice]]:
    """Cheapest recent unverified fare per exact date pair, and per (route, month)."""
    since = start_of(run_date - timedelta(days=config.CACHE_LOOKBACK_DAYS))
    routes: set[Route] = {(rq.origin, rq.dest_airport, rq.return_airport) for rq in rqs}
    exact: dict[DateKey, CachedPrice] = {}
    monthly: dict[tuple[str, str, str, date], CachedPrice] = {}
    if not routes:
        return exact, monthly
    rows = s.scalars(
        select(PriceObservation).where(
            PriceObservation.verified.is_(False),
            PriceObservation.source != config.HISTORY_SOURCE,  # history seeds baselines, never prices
            PriceObservation.observed_at >= since,
            PriceObservation.observed_at < start_of(run_date + timedelta(days=1)),
        )
    )
    for o in rows:
        route = (o.origin, o.dest_airport, o.return_airport)
        if route not in routes:
            continue
        cp = CachedPrice(o.id, o.price)
        mkey = (*route, o.month)
        if mkey not in monthly or cp.price < monthly[mkey].price:
            monthly[mkey] = cp
        if o.depart_date and o.return_date:
            dkey = date_key(o)
            if dkey not in exact or cp.price < exact[dkey].price:
                exact[dkey] = cp
    return exact, monthly


def estimate(rq: RouteQuery, exact: dict, monthly: dict) -> CachedPrice | None:
    return exact.get(date_key(rq)) or monthly.get(
        (rq.origin, rq.dest_airport, rq.return_airport, month_of(rq.depart_date))
    )


def load_baselines(s: Session, routes: set[Route] | None = None) -> dict[BaselineKey, Baseline]:
    """Every baseline, or only those for the given (origin, dest_airport, return_airport) routes."""
    query = select(RouteBaseline)
    if routes is not None:
        if not routes:
            return {}
        route = tuple_(RouteBaseline.origin, RouteBaseline.dest_airport, RouteBaseline.return_airport)
        query = query.where(route.in_(sorted(routes)))
    return {
        (b.origin, b.dest_airport, b.return_airport, b.month, b.length_bucket): Baseline(
            float(b.median), float(b.sigma), b.n, b.confidence
        )
        for b in s.scalars(query)
    }
