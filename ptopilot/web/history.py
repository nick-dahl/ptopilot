"""What the dashboard and destination pages show: each tracker's trips from the latest scan, and its trend.

Read-only. Prices come from `candidates` (one row per trip per scan day), so no extra history table is needed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ptopilot.core.geo import Geo, Palette, palette
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.db.models import Candidate, PriceObservation, RouteQuery, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.digest.select import latest_run_date, next_good_month
from ptopilot.pipeline.queries import load_baselines, rq_baseline_key
from ptopilot.web.viz import BarGeometry, TrendPoint, bar_geometry, sigma_floor

TREND_DAYS = 30
DIMMED_STATES = frozenset({"snoozed", "excluded"})


@dataclass(frozen=True)
class TripOption:
    candidate_id: int
    tracker_id: int
    origin: str
    dest_airport: str
    return_airport: str
    depart_date: date
    return_date: date
    evening_departure: bool
    price: Decimal
    currency: str
    pto_cost: int
    days_away: int
    season_rating: str
    weather_note: str | None
    carrier: str | None
    stops: int | None
    overnight: bool | None
    deep_link: str | None
    deal_level: str
    go_now: int
    state: str
    median: float | None
    sigma: float | None
    bar: BarGeometry | None

    @property
    def open_jaw(self) -> bool:
        return self.return_airport != self.dest_airport

    @property
    def dimmed(self) -> bool:
        return self.state in DIMMED_STATES

    @property
    def pct_below(self) -> int | None:
        if not self.median:
            return None
        return round(100 * (1 - float(self.price) / self.median))


@dataclass(frozen=True)
class DestinationSummary:
    tracker_id: int
    code: str
    name: str
    palette: Palette
    stay: tuple[int, int]  # days on the ground, min..max
    best: TripOption | None
    snoozed_until: date | None
    next_good_month: str | None


def _options(
    s: Session, geo: Geo, seasons: SeasonTable, trackers: list[Tracker], run_date: date
) -> dict[int, list[TripOption]]:
    """Every candidate on run_date for these trackers, cheapest first."""
    by_id = {t.id: t for t in trackers}
    if not by_id:
        return {}
    baselines = load_baselines(s)
    rows = s.execute(
        select(Candidate, RouteQuery, TrackerRouteLink, PriceObservation)
        .join(RouteQuery, RouteQuery.id == Candidate.route_query_id)
        .join(
            TrackerRouteLink,
            (TrackerRouteLink.tracker_id == Candidate.tracker_id)
            & (TrackerRouteLink.route_query_id == Candidate.route_query_id)
            & (TrackerRouteLink.run_date == Candidate.run_date)
            & (TrackerRouteLink.evening_departure == Candidate.evening_departure),
        )
        .outerjoin(PriceObservation, PriceObservation.id == Candidate.price_observation_id)
        .where(Candidate.run_date == run_date, Candidate.tracker_id.in_(by_id))
        .order_by(Candidate.price, RouteQuery.depart_date, Candidate.id)
    ).all()
    out: defaultdict[int, list[TripOption]] = defaultdict(list)
    for c, rq, link, obs in rows:
        dest = geo.destination(by_id[c.tracker_id].destination_code)
        b = baselines.get(rq_baseline_key(rq))
        out[c.tracker_id].append(
            TripOption(
                candidate_id=c.id,
                tracker_id=c.tracker_id,
                origin=rq.origin,
                dest_airport=rq.dest_airport,
                return_airport=rq.return_airport,
                depart_date=rq.depart_date,
                return_date=rq.return_date,
                evening_departure=c.evening_departure,
                price=c.price,
                currency=c.currency,
                pto_cost=link.pto_cost,
                days_away=link.days_away,
                season_rating=link.season_rating,
                weather_note=seasons.note(
                    (dest.code, dest.country), trip_month(rq.depart_date, rq.return_date)
                ),
                carrier=obs.carrier if obs else None,
                stops=obs.stops if obs else None,
                overnight=obs.overnight_layover if obs else None,
                deep_link=obs.deep_link if obs else None,
                deal_level=c.deal_level,
                go_now=c.go_now,
                state=c.state,
                median=b.median if b else None,
                sigma=b.sigma if b else None,
                bar=bar_geometry(c.price, b.median, b.sigma) if b else None,
            )
        )
    return out


def trip_options(
    engine: Engine, geo: Geo, seasons: SeasonTable, tracker_id: int, today: date
) -> list[TripOption]:
    """The tracker's trips from the latest scan on or before today, cheapest first."""
    run_date = latest_run_date(engine, today)
    if run_date is None:
        return []
    with session_scope(engine) as s:
        tracker = s.get(Tracker, tracker_id)
        return _options(s, geo, seasons, [tracker], run_date).get(tracker_id, []) if tracker else []


def trend(engine: Engine, tracker_id: int, today: date) -> list[TrendPoint]:
    """The cheapest price per scan day over the last TREND_DAYS days, oldest first."""
    with session_scope(engine) as s:
        rows = s.execute(
            select(Candidate.run_date, func.min(Candidate.price))
            .where(
                Candidate.tracker_id == tracker_id,
                Candidate.run_date > today - timedelta(days=TREND_DAYS),
                Candidate.run_date <= today,
            )
            .group_by(Candidate.run_date)
            .order_by(Candidate.run_date)
        ).all()
    return [TrendPoint(run_date, price) for run_date, price in rows]


def typical_band(options: list[TripOption]) -> tuple[Decimal, Decimal] | None:
    """Median +/- sigma for the cheapest trip's route, the band drawn behind the trend line."""
    best = options[0] if options else None
    if best is None or best.median is None:
        return None
    median, sigma = (
        Decimal(str(round(best.median))),
        Decimal(str(round(sigma_floor(best.median, best.sigma)))),
    )
    return median - sigma, median + sigma


def destination_summaries(
    engine: Engine, geo: Geo, seasons: SeasonTable, user_id: int, today: date
) -> list[DestinationSummary]:
    """One card per active tracker: priced ones cheapest first, then the rest in the order they were added."""
    run_date = latest_run_date(engine, today)
    with session_scope(engine) as s:
        trackers = list(
            s.scalars(
                select(Tracker)
                .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                .order_by(Tracker.id)
            )
        )
        options = _options(s, geo, seasons, trackers, run_date) if run_date else {}
        summaries = []
        for t in trackers:
            dest = geo.destination(t.destination_code)
            mine = options.get(t.id, [])
            summaries.append(
                DestinationSummary(
                    tracker_id=t.id,
                    code=dest.code,
                    name=dest.name,
                    palette=palette(dest),
                    stay=(t.min_stay_days, t.max_stay_days),
                    best=next((o for o in mine if not o.dimmed), mine[0] if mine else None),
                    snoozed_until=t.snoozed_until if t.snoozed_until and t.snoozed_until >= today else None,
                    next_good_month=next_good_month(seasons, (dest.code, dest.country), today),
                )
            )
    priced = sorted((x for x in summaries if x.best), key=lambda x: (x.best.price, x.tracker_id))
    return priced + [x for x in summaries if not x.best]
