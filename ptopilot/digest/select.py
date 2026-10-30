"""Choose what goes into each traveler's digest (spec §8)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.duration import duration_label
from ptopilot.core.fit import BookedTrip, fit_notes
from ptopilot.core.geo import NEUTRAL_PALETTE, Geo, Palette, palette
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.core.standout import is_standout, standout_tag
from ptopilot.db.models import (
    Candidate,
    DigestSend,
    PlannedTrip,
    PriceObservation,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    User,
)
from ptopilot.db.session import session_scope
from ptopilot.links import web_link
from ptopilot.pipeline.queries import load_baselines, rq_baseline_key
from ptopilot.plan_totals import YearTotals, remaining_by_year, year_totals
from ptopilot.planning import booked_trips, current_year

LEVELS = {"none": 0, "good": 1, "great": 2}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class DealCard:
    candidate_id: int
    tracker_id: int
    route_query_id: int
    destination: str
    origin: str
    dest_airport: str
    return_airport: str
    depart_date: date
    return_date: date
    evening_departure: bool
    price: Decimal
    currency: str
    typical: Decimal | None
    deal_level: str
    go_now: int
    confidence: str
    verified: bool
    pto_cost: int
    days_away: int
    days_off: tuple[str, ...]
    season_rating: str
    weather_note: str | None
    carrier: str | None
    stops: int | None
    duration_min: int | None
    outbound_departure: datetime | None
    flight_numbers: tuple[str, ...]
    deep_link: str | None
    observed_at: datetime | None
    palette: Palette = NEUTRAL_PALETTE
    sigma: float | None = None  # spread of the typical price, for the "where this price sits" bar
    fit_notes: tuple[str, ...] = ()  # soft warnings: overlaps a booked trip, over the PTO left
    misery_note: str | None = None  # a forgiven trade-off, e.g. a long layover worth the price
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
    def pct_below(self) -> int | None:
        if not self.typical or self.typical <= 0:
            return None
        return round(100 * (1 - self.price / self.typical))


@dataclass(frozen=True)
class TrackerRow:
    tracker_id: int
    destination: str
    best_price: Decimal | None
    typical: Decimal | None
    trend: str  # "down" | "up" | "flat" | "new"
    next_good_month: str | None
    snoozed_until: date | None
    palette: Palette = NEUTRAL_PALETTE


@dataclass
class Digest:
    user_id: int
    email: str
    run_date: date
    deals: list[DealCard]
    trackers: list[TrackerRow]
    held_back: int = 0  # deals left out because they were already sent at (about) this price
    banner: YearTotals | None = None  # the PTO line at the top: booked, planned, left for one year

    @property
    def quiet(self) -> bool:
        return not self.deals


def next_good_month(seasons: SeasonTable, codes: tuple[str, ...], start: date) -> str | None:
    for i in range(12):
        month = (start.month - 1 + i) % 12 + 1
        if seasons.rating(codes, month) == "good":
            return MONTHS[month - 1]
    return None


def _trend(today: Decimal | None, week_ago: Decimal | None) -> str:
    if today is None or week_ago is None:
        return "new"
    band = Decimal(str(config.TREND_BAND))
    if today < week_ago * (1 - band):
        return "down"
    if today > week_ago * (1 + band):
        return "up"
    return "flat"


def booked_pairs(s: Session, tracker_ids: Collection[int] | None = None) -> set[tuple[int, int]]:
    """The (tracker, year) pairs whose trip is booked: those leave the watch."""
    query = select(PlannedTrip.tracker_id, PlannedTrip.year).where(PlannedTrip.booked_depart.is_not(None))
    if tracker_ids is not None:
        query = query.where(PlannedTrip.tracker_id.in_(list(tracker_ids)))
    return {(tracker_id, year) for tracker_id, year in s.execute(query)}


def latest_run_date(engine: Engine, today: date) -> date | None:
    with session_scope(engine) as s:
        return s.scalar(select(func.max(Candidate.run_date)).where(Candidate.run_date <= today))


def build_digests(
    engine: Engine,
    geo: Geo,
    seasons: SeasonTable,
    today: date,
    min_level: str = "good",
    user_id: int | None = None,
    skip_sent: bool = True,
    all_deals: bool = False,
) -> list[Digest]:
    """One digest per user with active trackers (or only `user_id`), from the latest scan up to today.

    `all_deals` keeps every qualifying deal instead of the digest's pick (instant alerts look at them all)."""
    run_date = latest_run_date(engine, today)
    if run_date is None:
        return []
    floor = LEVELS[min_level]
    with session_scope(engine) as s:
        baselines = load_baselines(s)
        booked = booked_pairs(s)
        user_filter = User.id == user_id if user_id is not None else User.id.is_not(None)
        users = list(s.scalars(select(User).where(user_filter).order_by(User.id)))
        trackers = list(s.scalars(select(Tracker).where(Tracker.active.is_(True)).order_by(Tracker.id)))
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
            .where(Candidate.run_date == run_date, Candidate.verdict != "ruled_out")
        ).all()
        # Each user's bookings and PTO left, loaded once for all of their cards.
        years = {rq.depart_date.year for _, rq, _, _ in rows}
        fit_context: dict[int, tuple[list[BookedTrip], dict[int, int]]] = {
            u.id: (booked_trips(s, u, geo=geo), remaining_by_year(s, u, years)) for u in users
        }
        week_ago = dict(
            s.execute(
                select(Candidate.tracker_id, func.min(Candidate.price))
                .where(Candidate.run_date == run_date - timedelta(days=7), Candidate.verdict != "ruled_out")
                .group_by(Candidate.tracker_id)
            ).all()
        )
        # Lowest price already sent per (tracker, route, evening variant). Matched on the identity stored in
        # each item, not on candidate ids: a re-run of the score stage deletes and recreates candidates.
        # Items without that identity (recorded before it was stored) are ignored.
        sent_price: dict[tuple, Decimal] = {}
        for send in s.scalars(select(DigestSend)):
            for item in send.items or []:
                if "route_query_id" not in item:
                    continue
                key = (item["tracker_id"], item["route_query_id"], item["evening_departure"])
                price = Decimal(str(item["price"]))
                sent_price[key] = min(price, sent_price.get(key, price))

    tracker_by_id = {t.id: t for t in trackers}
    cards_by_tracker: defaultdict[int, list[DealCard]] = defaultdict(list)
    held_back: defaultdict[int, int] = defaultdict(int)
    best_today: dict[int, tuple[Decimal, Decimal | None]] = {}
    for c, rq, link, obs in rows:
        tracker = tracker_by_id.get(c.tracker_id)
        if tracker is None or (c.tracker_id, rq.depart_date.year) in booked:
            continue
        b = baselines.get(rq_baseline_key(rq))
        typical = Decimal(str(round(b.median))) if b else None
        if c.tracker_id not in best_today or c.price < best_today[c.tracker_id][0]:
            best_today[c.tracker_id] = (c.price, typical)
        if LEVELS[c.deal_level] < floor or c.state == "excluded":
            continue
        if tracker.snoozed_until is not None and tracker.snoozed_until >= today:
            continue
        prior = sent_price.get((c.tracker_id, c.route_query_id, c.evening_departure))
        if skip_sent and prior is not None and c.price > prior * Decimal(str(config.DIGEST_RESEND_FACTOR)):
            held_back[c.tracker_id] += 1
            continue
        dest = geo.destination(tracker.destination_code)
        codes = (dest.code, dest.country)
        cards_by_tracker[c.tracker_id].append(
            DealCard(
                candidate_id=c.id,
                tracker_id=c.tracker_id,
                route_query_id=c.route_query_id,
                destination=dest.name,
                origin=rq.origin,
                dest_airport=rq.dest_airport,
                return_airport=rq.return_airport,
                depart_date=rq.depart_date,
                return_date=rq.return_date,
                evening_departure=c.evening_departure,
                price=c.price,
                currency=c.currency,
                typical=typical,
                deal_level=c.deal_level,
                go_now=c.go_now,
                confidence=c.confidence,
                verified=c.verified,
                pto_cost=link.pto_cost,
                days_away=link.days_away,
                days_off=tuple(link.days_off or ()),
                season_rating=link.season_rating,
                weather_note=seasons.note(codes, trip_month(rq.depart_date, rq.return_date)),
                carrier=obs.carrier if obs else None,
                stops=obs.stops if obs else None,
                duration_min=obs.duration_min if obs else None,
                outbound_departure=obs.outbound_departure if obs else None,
                flight_numbers=tuple(obs.flight_numbers or ()) if obs else (),
                deep_link=web_link(obs.deep_link) if obs else None,
                observed_at=obs.observed_at if obs else None,
                palette=palette(dest),
                sigma=b.sigma if b else None,
                misery_note=c.misery_note if c.verdict == "forgiven" else None,
                expected_days=c.expected_days,
                duration_thin=c.duration_thin,
                standout=c.verdict != "ruled_out"
                and is_standout(c.go_now, c.deal_level, c.confidence, c.verified, c.expected_days),
            )
        )

    digests = []
    for user in users:
        mine = [t for t in trackers if t.user_id == user.id]
        if not mine:
            continue
        tops, alternates = [], []
        for t in mine:
            ranked = sorted(cards_by_tracker[t.id], key=lambda d: (-d.go_now, d.price, d.candidate_id))
            tops += ranked[:1]
            alternates += ranked[1 : 1 + config.DIGEST_ALTERNATES_PER_TRACKER]
        by_score = lambda d: (-d.go_now, d.price, d.candidate_id)  # noqa: E731
        if all_deals:
            chosen = sorted((d for t in mine for d in cards_by_tracker[t.id]), key=by_score)
        else:
            chosen = (sorted(tops, key=by_score) + sorted(alternates, key=by_score))[
                : config.DIGEST_MAX_DEALS
            ]
        user_booked, user_remaining = fit_context[user.id]
        chosen = [
            replace(
                d,
                fit_notes=fit_notes(
                    d.depart_date,
                    d.return_date,
                    d.pto_cost,
                    user_booked,
                    user_remaining.get(d.depart_date.year),
                    d.tracker_id,
                ),
            )
            for d in chosen
        ]
        rows_for_user = []
        for t in mine:
            dest = geo.destination(t.destination_code)
            best, typical = best_today.get(t.id, (None, None))
            rows_for_user.append(
                TrackerRow(
                    tracker_id=t.id,
                    destination=dest.name,
                    best_price=best,
                    typical=typical,
                    trend=_trend(best, week_ago.get(t.id)),
                    next_good_month=next_good_month(seasons, (dest.code, dest.country), run_date),
                    snoozed_until=t.snoozed_until if t.snoozed_until and t.snoozed_until >= today else None,
                    palette=palette(dest),
                )
            )
        held = sum(held_back[t.id] for t in mine)
        digests.append(
            Digest(
                user.id,
                user.email,
                run_date,
                _standout_first(sorted(chosen, key=by_score)),
                rows_for_user,
                held,
                _banner(engine, user, chosen, geo, seasons, today),
            )
        )
    return digests


def _standout_first(deals: list[DealCard]) -> list[DealCard]:
    """The lead card is the best standout deal when there is one; the order is otherwise unchanged."""
    lead = next((d for d in deals if d.standout), None)
    return [lead, *(d for d in deals if d is not lead)] if lead else deals


def _banner(
    engine: Engine, user: User, chosen: list[DealCard], geo: Geo, seasons: SeasonTable, today: date
) -> YearTotals | None:
    """The year totals for the earliest deal's year, or for the current planning year in a quiet week."""
    with session_scope(engine) as s:
        if chosen:
            year = min(d.depart_date for d in chosen).year
        else:
            py = current_year(s, user, today)
            if py is None:
                return None
            year = py.year
        return year_totals(s, user, year, geo, seasons)
