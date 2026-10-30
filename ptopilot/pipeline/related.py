"""Stage `related`: a light daily watch of the related places users accepted (Plan 14).

Free cached month fares to each accepted related airport are compared with the main destination's typical
price. A round trip that fits the user's year and is at least RELATED_STUNNING_PCT% below that typical is
promising. The biggest discounts get a free fast-flights check, at most RELATED_LIVE_CHECKS_PER_DAY a day
across all users (counted from today's related_checks, failures included), and every check is stored there.
Related places get no route queries, baselines or alerts of their own, so nothing here writes prices.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.fit import BookedTrip
from ptopilot.core.geo import Destination, Geo, UnknownCodeError
from ptopilot.core.misery import assess, problems
from ptopilot.core.planner import target_band
from ptopilot.core.related import fits
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.core.stats import Baseline
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import RelatedCheck, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.digest.select import booked_pairs
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.expand import profile_for
from ptopilot.pipeline.queries import BaselineKey, baseline_key, load_baselines, month_of
from ptopilot.pipeline.score import passing_filters
from ptopilot.plan_totals import remaining_by_year
from ptopilot.planning import booked_trips, planning_years, year_ranges
from ptopilot.related_links import accepted_links
from ptopilot.sources.base import (
    ExactQuery,
    ExactSearchSource,
    FareQuote,
    FlightOption,
    SourceUnavailable,
    snippet,
)

log = logging.getLogger(__name__)

LIVE_SOURCE = "google_flights"  # free; budgeted sources (SerpApi) are never spent on related places
Trip = tuple[int, str, date, date]  # user, related airport, depart, return
ScanKey = tuple[str, str, date]  # origin, related airport, month
COUNTS = (
    "links_watched", "scans", "scans_failed", "quotes",
    "promising", "checked", "confirmed", "held_live_cap", "skipped_no_typical",
)  # fmt: skip


@dataclass(frozen=True)
class _Link:
    """An accepted related airport whose main tracker is being watched."""

    id: int
    user: User
    tracker: Tracker
    airport: str
    place: Destination
    main: Destination


@dataclass(frozen=True)
class _Year:
    """A user's year as the fit checks see it."""

    homes: tuple[str, ...]
    calendar: WorkCalendar
    ranges: dict[int, list[tuple[date, date]]]  # open ranges ending after the run date, by planning year
    remaining: dict[int, int]  # PTO left after booked trips
    booked: list[BookedTrip]

    def months(self) -> list[date]:
        return sorted({m for ranges in self.ranges.values() for a, b in ranges for m in _months(a, b)})

    def year_of(self, depart: date, ret: date) -> int | None:
        """The planning year whose open range holds the whole trip."""
        for year, ranges in self.ranges.items():
            if any(a <= depart and ret <= b for a, b in ranges):
                return year
        return None


@dataclass(frozen=True)
class _Fare:
    link: _Link  # the main destination with the lowest typical
    origin: str
    depart: date
    ret: date
    price: float
    typical: float
    pto_cost: int

    @property
    def trip(self) -> Trip:
        return (self.link.user.id, self.link.airport, self.depart, self.ret)

    @property
    def discount(self) -> float:
        return 1 - self.price / self.typical


def stunning(price: float, typical: float) -> bool:
    return price <= (1 - config.RELATED_STUNNING_PCT / 100) * typical


def _months(start: date, end: date) -> list[date]:
    out, m = [], month_of(start)
    while m <= end:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def _watched_links(s: Session, ctx: RunContext, geo: Geo) -> list[_Link]:
    out = []
    for link in accepted_links(s):
        tracker = s.get(Tracker, link.tracker_id)
        if not tracker.active or (
            tracker.snoozed_until is not None and tracker.snoozed_until >= ctx.run_date
        ):
            continue
        try:
            place, main = geo.destination(link.place_code), geo.destination(tracker.destination_code)
        except UnknownCodeError:
            log.warning("related link %s names an unknown place; not watched", link.id)
            continue
        out.append(_Link(link.id, s.get(User, link.user_id), tracker, link.airport, place, main))
    return out


def _year(s: Session, user: User, run_date: date, geo: Geo) -> _Year:
    profile = profile_for(user)
    years = [py.year for py in planning_years(s, user) if py.year >= run_date.year]
    ranges = {y: [(a, b) for a, b in year_ranges(s, user, y) if b > run_date] for y in years}
    return _Year(
        profile.home_airports,
        profile.calendar,
        ranges,
        remaining_by_year(s, user, years),
        booked_trips(s, user, geo=geo),
    )


def _typical(baselines: dict[BaselineKey, Baseline], origin: str, main: Destination, d: date, r: date):
    """The lowest normal-confidence median over the main destination's airport pairs; None without one."""
    medians = [
        b.median
        for a in main.airports
        for h in main.home_from
        if (b := baselines.get(baseline_key(origin, a, h, d, r))) is not None and b.confidence == "normal"
    ]
    return min(medians, default=None)


def _band(link: _Link, origin: str, geo: Geo) -> tuple[int, int]:
    """Days away worth taking: around the main tracker's target (or the user's ideal length); with neither,
    the user's own trip lengths, never below the shortest trip worth taking to the place."""
    rule = geo.travel_rule(origin, link.place)
    target = link.tracker.target_days or link.user.ideal_trip_days
    if target:
        return target_band(target, config.TARGET_TOLERANCE_DAYS, rule.min_trip_days)
    return max(link.user.min_trip_days, rule.min_trip_days), link.user.max_trip_days


def _scan(
    ctx: RunContext, keys: list[ScanKey], geo: Geo, counts: Counter[str]
) -> dict[ScanKey, list[FareQuote]]:
    """One month scan per (origin, airport, month), shared by every user who needs it."""
    found: dict[ScanKey, list[FareQuote]] = {}
    last_error = ""
    for origin, airport, month in keys:
        counts["scans"] += 1
        try:
            quotes = ctx.month_source.month_scan(
                origin, airport, month, market=geo.airport(origin).country, currency=config.DEFAULT_CURRENCY
            )
        except SourceUnavailable as exc:
            counts["scans_failed"] += 1
            last_error = str(exc)
            log.warning("related month scan %s-%s %s failed: %s", origin, airport, month, exc)
            continue
        counts["quotes"] += len(quotes)
        found[(origin, airport, month)] = quotes
    if keys and counts["scans_failed"] == len(keys):
        raise StageFailed(f"all {len(keys)} related month scans failed; last error: {last_error}")
    return found


def _promising(
    ctx: RunContext,
    links: list[_Link],
    years: dict[int, _Year],
    found: dict[ScanKey, list[FareQuote]],
    baselines: dict[BaselineKey, Baseline],
    booked: set[tuple[int, int]],
    geo: Geo,
    seasons: SeasonTable,
    counts: Counter[str],
) -> list[_Fare]:
    """The cheapest promising fare per trip, against the lowest typical of the main destinations it fits."""
    fitting: defaultdict[Trip, list[_Fare | None]] = defaultdict(list)  # None: fits, but no typical
    for link in links:
        year = years[link.user.id]
        for origin in year.homes:
            for month in year.months():
                for q in found.get((origin, link.airport, month), ()):
                    if q.return_date is None or q.depart_date <= ctx.run_date:
                        continue
                    d, r = q.depart_date, q.return_date
                    fare_year = year.year_of(d, r)
                    if fare_year is None or (link.tracker.id, fare_year) in booked:
                        continue
                    ratings = seasons.ratings.get(
                        link.place.code
                    )  # never SeasonTable.rating's "good" default
                    pto = year.calendar.pto_cost(d, r)
                    if not fits(
                        d,
                        r,
                        ranges=year.ranges[fare_year],
                        pto_cost=pto,
                        pto_remaining=year.remaining.get(fare_year, 0),
                        band=_band(link, origin, geo),
                        rating=ratings[trip_month(d, r) - 1] if ratings else None,
                        booked=year.booked,
                    ):
                        continue
                    typical = _typical(baselines, origin, link.main, d, r)
                    trip = (link.user.id, link.airport, d, r)
                    fitting[trip].append(
                        None if typical is None else _Fare(link, origin, d, r, q.price, typical, pto)
                    )
    out = []
    for fares in fitting.values():
        priced = [f for f in fares if f is not None]
        if not priced:
            counts["skipped_no_typical"] += 1
            continue
        strictest: dict[str, _Fare] = {}  # per origin: the cheapest quote against the lowest typical
        for f in priced:
            have = strictest.get(f.origin)
            if have is None:
                strictest[f.origin] = f
            else:
                low = f if f.typical < have.typical else have
                strictest[f.origin] = _Fare(
                    low.link, f.origin, f.depart, f.ret, min(f.price, have.price), low.typical, f.pto_cost
                )
        hits = [f for f in strictest.values() if stunning(f.price, f.typical)]
        if hits:
            out.append(min(hits, key=lambda f: (f.price, -f.discount, f.origin)))
    counts["promising"] = len(out)
    return sorted(out, key=lambda f: (-f.discount, f.depart, f.ret, f.link.airport, f.link.user.id))


def best_option(
    options: Sequence[FlightOption], user: User, place: Destination, typical: float, catalog: AirportCatalog
) -> FlightOption | None:
    """The cheapest option that passes the user's filters and isn't ruled out as miserable.

    Judged as return_check does; the related airport is the place itself, so there is no ground time."""
    fastest = min((o.duration_min for o in options if o.duration_min), default=None)
    for o in sorted(passing_filters(options, user), key=lambda o: o.price):
        layover = catalog.get(o.longest_layover_airport) if o.longest_layover_airport else None
        found = problems(
            longest_layover_min=o.longest_layover_min,
            layover_city=layover.city if layover else None,
            duration_min=o.duration_min,
            fastest_min=fastest,
            ground_min=0,
            destination_name=place.name,
        )
        if (
            assess(found, price=o.price, typical_median=typical, typical_confident=True).verdict
            != "ruled_out"
        ):
            return o
    return None


def _check(ctx: RunContext, source: ExactSearchSource, fare: _Fare, catalog: AirportCatalog) -> RelatedCheck:
    link = fare.link
    row = RelatedCheck(
        run_date=ctx.run_date,
        user_id=link.user.id,
        tracker_id=link.tracker.id,
        link_id=link.id,
        origin=fare.origin,
        airport=link.airport,
        depart_date=fare.depart,
        return_date=fare.ret,
        cached_price=Decimal(str(fare.price)),
        typical_median=Decimal(str(fare.typical)),
        currency=config.DEFAULT_CURRENCY,
        pto_cost=fare.pto_cost,
        confirmed=False,
    )
    try:
        result = source.exact_search(ExactQuery(fare.origin, link.airport, fare.depart, fare.ret))
    except SourceUnavailable as exc:
        row.error = snippet(str(exc), 1000) or "unavailable"
        return row
    best = best_option(result.options, link.user, link.place, fare.typical, catalog)
    row.currency, row.deep_link = result.currency, result.deep_link
    if best is not None:
        row.live_price = Decimal(str(best.price))
        row.confirmed = stunning(best.price, fare.typical)
    return row


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.month_source is None:
        raise StageSkipped("no month-scan source configured (set TRAVELPAYOUTS_TOKEN)")
    counts: Counter[str] = Counter(dict.fromkeys(COUNTS, 0))
    geo, seasons = load_geo(ctx.engine), load_seasons(ctx.engine)  # with the places users added
    with session_scope(ctx.engine) as s:
        links = _watched_links(s, ctx, geo)
        years = {link.user.id: _year(s, link.user, ctx.run_date, geo) for link in links}
        booked = booked_pairs(s, {link.tracker.id for link in links})
        baselines = load_baselines(s)
        today = select(RelatedCheck).where(RelatedCheck.run_date == ctx.run_date)
        checked = {(c.user_id, c.airport, c.depart_date, c.return_date) for c in s.scalars(today)}
        used = s.scalar(select(func.count()).where(RelatedCheck.run_date == ctx.run_date)) or 0
    counts["links_watched"] = len(links)
    keys = sorted(
        {
            (o, link.airport, m)
            for link in links
            for o in years[link.user.id].homes
            for m in years[link.user.id].months()
        }
    )
    found = _scan(ctx, keys, geo, counts)
    fares = _promising(ctx, links, years, found, baselines, booked, geo, seasons, counts)

    source = next((src for src in ctx.live_sources if src.name == LIVE_SOURCE), None)
    if fares and source is None:
        log.warning("no %s source: %d promising related fares left unchecked", LIVE_SOURCE, len(fares))
        fares = []
    catalog = AirportCatalog.load()
    for fare in fares:
        if fare.trip in checked:
            continue
        if used >= config.RELATED_LIVE_CHECKS_PER_DAY:
            counts["held_live_cap"] += 1
            continue
        used += 1
        row = _check(ctx, source, fare, catalog)
        with session_scope(ctx.engine) as s:
            s.add(row)
        counts["checked"] += 1
        counts["confirmed"] += int(row.confirmed)
    return dict(counts)
