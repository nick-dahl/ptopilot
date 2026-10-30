"""What the dashboard and destination pages show: each tracker's trips from the latest scan, and its trend.

Read-only. Prices come from `candidates` (one row per trip per scan day), so no extra history table is needed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ptopilot.core.duration import duration_label
from ptopilot.core.fit import BookedTrip, fit_notes
from ptopilot.core.geo import Destination, Geo, Palette, palette
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.core.standout import is_standout, standout_tag
from ptopilot.db.models import (
    Candidate,
    PriceObservation,
    RouteBaseline,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    User,
)
from ptopilot.db.session import session_scope
from ptopilot.digest.select import RelatedCard, booked_pairs, latest_run_date, next_good_month, related_cards
from ptopilot.links import web_link
from ptopilot.pipeline.queries import load_baselines, rq_baseline_key
from ptopilot.plan_totals import remaining_by_year
from ptopilot.planning import booked_trips
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
    fit_notes: tuple[str, ...] = ()  # soft warnings: overlaps a booked trip, over the PTO left
    confidence: str = "normal"
    verdict: str = "ok"  # 'ok' | 'forgiven' | 'ruled_out'
    misery_note: str | None = None  # the problem: why it is ruled out, or what was forgiven
    expected_days: int | None = None  # how long a dip like this usually lasts; None when unknown
    duration_thin: bool = False  # a dip today, but too little history to say how long it lasts
    standout: bool = False  # rare: great, verified and likely gone within days

    @property
    def duration_note(self) -> str | None:
        return duration_label(self.expected_days, dips_found=not self.duration_thin)

    @property
    def standout_tag(self) -> str | None:
        return standout_tag(self.expected_days) if self.standout else None

    @property
    def open_jaw(self) -> bool:
        return self.return_airport != self.dest_airport

    @property
    def ruled_out(self) -> bool:
        return self.verdict == "ruled_out"

    @property
    def dimmed(self) -> bool:
        return self.state in DIMMED_STATES or self.ruled_out

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
    ruled_out: bool = False  # it has trips today, but every one is snoozed or excluded
    building_history: bool = False  # no normal-confidence price baseline yet for any home route
    target_days: int | None = None
    booked: tuple[BookedTrip, ...] = ()  # this destination's booked trips, this year on


def _options(
    s: Session, geo: Geo, seasons: SeasonTable, trackers: list[Tracker], run_date: date
) -> dict[int, list[TripOption]]:
    """Every candidate on run_date for these trackers, cheapest first, each with its fit notes."""
    by_id = {t.id: t for t in trackers}
    if not by_id:
        return {}
    user_ids = {t.user_id for t in trackers}
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
    booked = booked_pairs(s, by_id)
    rows = [r for r in rows if (r[0].tracker_id, r[1].depart_date.year) not in booked]
    baselines = load_baselines(
        s, routes={(rq.origin, rq.dest_airport, rq.return_airport) for _, rq, _, _ in rows}
    )
    # The user's bookings and PTO left, loaded once for every row.
    fit: dict[int, tuple[list[BookedTrip], dict[int, int]]] = {}
    years = {rq.depart_date.year for _, rq, _, _ in rows}
    for user in s.scalars(select(User).where(User.id.in_(user_ids))):
        fit[user.id] = (booked_trips(s, user, geo=geo), remaining_by_year(s, user, years))
    out: defaultdict[int, list[TripOption]] = defaultdict(list)
    for c, rq, link, obs in rows:
        user_booked, user_remaining = fit.get(by_id[c.tracker_id].user_id, ([], {}))
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
                deep_link=web_link(obs.deep_link) if obs else None,
                deal_level=c.deal_level,
                go_now=c.go_now,
                state=c.state,
                confidence=c.confidence,
                verdict=c.verdict,
                misery_note=c.misery_note,
                expected_days=c.expected_days,
                duration_thin=c.duration_thin,
                standout=c.verdict != "ruled_out"
                and is_standout(c.go_now, c.deal_level, c.confidence, c.verified, c.expected_days),
                median=b.median if b else None,
                sigma=b.sigma if b else None,
                bar=bar_geometry(c.price, b.median, b.sigma) if b else None,
                fit_notes=fit_notes(
                    rq.depart_date,
                    rq.return_date,
                    link.pto_cost,
                    user_booked,
                    user_remaining.get(rq.depart_date.year),
                    c.tracker_id,
                ),
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


def related_deals(s: Session, tracker_id: int, run_date: date, geo: Geo, today: date) -> list[RelatedCard]:
    """The tracker's confirmed related deals from one scan day (the Related panel); none while snoozed."""
    return related_cards(s, run_date, geo, today, tracker_id=tracker_id)


def trend(engine: Engine, tracker_id: int, today: date) -> list[TrendPoint]:
    """The cheapest price per scan day over the last TREND_DAYS days, oldest first."""
    with session_scope(engine) as s:
        rows = s.execute(
            select(Candidate.run_date, func.min(Candidate.price))
            .where(
                Candidate.tracker_id == tracker_id,
                Candidate.verdict != "ruled_out",
                Candidate.run_date > today - timedelta(days=TREND_DAYS),
                Candidate.run_date <= today,
            )
            .group_by(Candidate.run_date)
            .order_by(Candidate.run_date)
        ).all()
    return [TrendPoint(run_date, price) for run_date, price in rows]


def typical_band(options: list[TripOption]) -> tuple[Decimal, Decimal] | None:
    """Median +/- sigma for the cheapest trip's route, the band drawn behind the trend line."""
    best = next((o for o in options if not o.ruled_out), None)
    if best is None or best.median is None:
        return None
    median, sigma = (
        Decimal(str(round(best.median))),
        Decimal(str(round(sigma_floor(best.median, best.sigma)))),
    )
    return median - sigma, median + sigma


def building_history(s: Session, homes: Sequence[str], dest: Destination) -> bool:
    """True until some home airport has a normal-confidence price baseline to this destination."""
    found = s.scalar(
        select(RouteBaseline.origin)
        .where(
            RouteBaseline.confidence == "normal",
            RouteBaseline.origin.in_(list(homes)),
            RouteBaseline.dest_airport.in_(dest.airports),
            RouteBaseline.return_airport.in_(dest.home_from),
        )
        .limit(1)
    )
    return found is None


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
        user = s.get(User, user_id)
        homes = [user.home_airport, *user.nearby_airports] if user else []
        bookings: defaultdict[int, list[BookedTrip]] = defaultdict(list)
        for b in booked_trips(s, user, geo=geo) if user else []:
            if b.year >= today.year:
                bookings[b.tracker_id].append(b)
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
                    best=next((o for o in mine if not o.dimmed), None),  # dimmed includes ruled-out trips
                    snoozed_until=t.snoozed_until if t.snoozed_until and t.snoozed_until >= today else None,
                    next_good_month=next_good_month(seasons, (dest.code, dest.country), today),
                    ruled_out=bool(mine) and all(o.dimmed for o in mine),
                    building_history=building_history(s, homes, dest),
                    target_days=t.target_days,
                    booked=tuple(bookings[t.id]),
                )
            )
    priced = sorted((x for x in summaries if x.best), key=lambda x: (x.best.price, x.tracker_id))
    return priced + [x for x in summaries if not x.best]
