"""Stage `gems`: publish each person's weekly hidden gem and price their newest ones (Plan 16, spec §3.4-3.5).

Publishing: everyone with an active tracker or a finished profile gets their due issue (`publish_due`).

Pricing, with free sources only: each person's newest GEM_PRICED_ISSUES issues (retired gems skipped) whose
last gem_fares row is GEM_RECHECK_DAYS old, or missing, are priced from their home airports. Candidate dates
come from cached month scans over the person's open ranges (or, with none, the gem's best months in the
next 12 months), round trips within TRIP_SLACK_DAYS of their trip length. The cheapest candidate per
(person, gem) gets one google_flights live check, at most GEM_LIVE_CHECKS_PER_DAY a day across everyone
(counted from today's checked gem_fares rows, so re-runs get no fresh allowance). SerpApi is never used.
Every attempt stores one row: `found`, `none` (no candidate, or no acceptable live option) or `failed`.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.gem_feed import publish_due
from ptopilot.core.geo import Geo
from ptopilot.core.seasons import trip_month
from ptopilot.data import load_geo
from ptopilot.db.models import GemFare, GemIssue, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.gems import Gem, approved, load_catalogue
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.expand import profile_for
from ptopilot.pipeline.queries import month_of
from ptopilot.pipeline.related import LIVE_SOURCE, _months, best_option
from ptopilot.plan_totals import remaining_by_year
from ptopilot.planning import planning_years, year_ranges
from ptopilot.sources.base import ExactQuery, ExactSearchSource, FareQuote, SourceUnavailable

log = logging.getLogger(__name__)

TRIP_SLACK_DAYS = 2  # candidate trips within this many days of the person's trip length
COUNTS = (
    "users", "published", "priced_due", "scans", "scans_failed",
    "checked", "would_check", "found", "none", "failed", "held_live_cap",
)  # fmt: skip
ScanKey = tuple[str, str, date]  # origin, gem airport, month


@dataclass(frozen=True)
class _Person:
    """A user as the fare checks see them."""

    user: User
    homes: tuple[str, ...]
    calendar: WorkCalendar
    ranges: dict[int, list[tuple[date, date]]]  # open ranges ending after the run date, by planning year
    remaining: dict[int, int]  # PTO left after booked trips
    length: int  # days away to aim for

    def range_months(self, run_date: date) -> list[date]:
        first = run_date + timedelta(days=1)
        return sorted({m for rs in self.ranges.values() for a, b in rs for m in _months(max(a, first), b)})

    def year_of(self, depart: date, ret: date) -> int | None:
        for year, ranges in self.ranges.items():
            if any(a <= depart and ret <= b for a, b in ranges):
                return year
        return None


@dataclass(frozen=True)
class _Due:
    person: _Person
    gem: Gem
    months: tuple[date, ...]


@dataclass(frozen=True)
class _Candidate:
    due: _Due
    origin: str
    airport: str
    depart: date
    ret: date
    price: float


def _person(s: Session, user: User, run_date: date) -> _Person:
    profile = profile_for(user)
    years = [py.year for py in planning_years(s, user) if py.year >= run_date.year]
    ranges = {y: [(a, b) for a, b in year_ranges(s, user, y) if b > run_date] for y in years}
    length = user.ideal_trip_days or (user.min_trip_days + user.max_trip_days) // 2
    return _Person(
        user, profile.home_airports, profile.calendar, ranges, remaining_by_year(s, user, years), length
    )


def _best_months(gem: Gem, run_date: date) -> list[date]:
    """The gem's best months among the next 12, starting with the month of tomorrow."""
    m, out = month_of(run_date + timedelta(days=1)), []
    for _ in range(12):
        if m.month in gem.best_months:
            out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def _users(s: Session) -> list[User]:
    """Everyone with an active tracker or a finished profile."""
    tracking = exists().where(Tracker.user_id == User.id, Tracker.active.is_(True))
    return list(
        s.scalars(select(User).where(or_(tracking, User.onboarded_at.is_not(None))).order_by(User.id))
    )


def _due(s: Session, person: _Person, catalogue: dict[str, Gem], run_date: date) -> list[_Due]:
    """The person's newest issues of live gems that weren't priced in the last GEM_RECHECK_DAYS."""
    newest = s.scalars(
        select(GemIssue.gem_slug)
        .where(GemIssue.user_id == person.user.id)
        .order_by(GemIssue.published_on.desc(), GemIssue.id.desc())
        .limit(config.GEM_PRICED_ISSUES)
    ).all()
    last = dict(
        s.execute(
            select(GemFare.gem_slug, func.max(GemFare.run_date))
            .where(GemFare.user_id == person.user.id)
            .group_by(GemFare.gem_slug)
        ).all()
    )
    out = []
    for slug in newest:
        gem = catalogue.get(slug)
        if gem is None:  # retired, demoted or removed: never priced
            continue
        if slug in last and (run_date - last[slug]).days < config.GEM_RECHECK_DAYS:
            continue
        months = person.range_months(run_date) or _best_months(gem, run_date)
        out.append(_Due(person, gem, tuple(months)))
    return out


def _scan(
    ctx: RunContext, keys: list[ScanKey], geo: Geo, counts: Counter[str]
) -> dict[ScanKey, list[FareQuote]]:
    """One month scan per (origin, gem airport, month), shared by everyone who needs it."""
    found: dict[ScanKey, list[FareQuote]] = {}
    for origin, airport, month in keys:
        counts["scans"] += 1
        try:
            found[(origin, airport, month)] = ctx.month_source.month_scan(
                origin, airport, month, market=geo.airport(origin).country, currency=config.DEFAULT_CURRENCY
            )
        except SourceUnavailable as exc:
            counts["scans_failed"] += 1
            log.warning("gem month scan %s-%s %s failed: %s", origin, airport, month, exc)
    return found


def _cheapest(
    ctx: RunContext, due: _Due, found: dict[ScanKey, list[FareQuote]]
) -> tuple[bool, _Candidate | None]:
    """(whether any of the gem's scans answered, its cheapest round trip of about the right length)."""
    answered, best = False, None
    for origin in due.person.homes:
        for airport in due.gem.airports:
            for month in due.months:
                quotes = found.get((origin, airport, month))
                if quotes is None:
                    continue
                answered = True
                for q in quotes:
                    if q.return_date is None or q.depart_date <= ctx.run_date:
                        continue
                    days = (q.return_date - q.depart_date).days + 1
                    if abs(days - due.person.length) > TRIP_SLACK_DAYS:
                        continue
                    if best is None or q.price < best.price:
                        best = _Candidate(due, origin, airport, q.depart_date, q.return_date, q.price)
    return answered, best


def _miss(ctx: RunContext, due: _Due) -> GemFare:
    """No cached candidate: a `none` row, so the gem waits GEM_RECHECK_DAYS like any other check."""
    gem = due.gem
    return GemFare(
        user_id=due.person.user.id,
        gem_slug=gem.slug,
        origin=due.person.homes[0],
        airport=gem.airports[0],
        return_airport=(gem.return_airports or gem.airports)[0],
        currency=config.DEFAULT_CURRENCY,
        status="none",
        run_date=ctx.run_date,
    )


def _check(ctx: RunContext, source: ExactSearchSource, c: _Candidate, catalog: AirportCatalog) -> GemFare:
    person, gem = c.due.person, c.due.gem
    airport, home_from = c.airport, c.airport
    if (
        gem.return_airports and source.supports_open_jaw
    ):  # in to the first airport, home from the first return
        airport, home_from = gem.airports[0], gem.return_airports[0]
    query = ExactQuery(
        c.origin, airport, c.depart, c.ret, return_from=None if home_from == airport else home_from
    )
    row = GemFare(
        user_id=person.user.id,
        gem_slug=gem.slug,
        origin=c.origin,
        airport=airport,
        return_airport=home_from,
        depart_date=c.depart,
        return_date=c.ret,
        currency=config.DEFAULT_CURRENCY,
        status="failed",
        run_date=ctx.run_date,
    )
    try:
        result = source.exact_search(query)
    except SourceUnavailable as exc:
        log.warning("gem live check %s for user %s failed: %s", gem.slug, person.user.id, exc)
        return row
    row.currency, row.deep_link = result.currency, result.deep_link
    best = best_option(result.options, person.user, gem, None, catalog)  # forgives nothing
    if best is None:
        row.status = "none"
        return row
    pto = person.calendar.pto_cost(c.depart, c.ret)
    year = person.year_of(c.depart, c.ret)
    fits = year is not None and pto <= person.remaining.get(year, 0)
    row.status, row.price, row.pto_cost, row.fits = "found", Decimal(str(best.price)), pto, fits
    row.fit_month = trip_month(c.depart, c.ret) if fits else None
    return row


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter(dict.fromkeys(COUNTS, 0))
    catalogue = load_catalogue()
    live = {g.slug: g for g in approved(catalogue)}
    if not live:
        return dict(counts)
    geo = load_geo(ctx.engine)  # with the places users added
    with session_scope(ctx.engine) as s:
        users = _users(s)
        counts["users"] = len(users)
        for user in users:
            counts["published"] += publish_due(s, user, ctx.run_date, catalogue, geo) is not None
    if ctx.month_source is None:
        log.info("no month-scan source configured: gems published but not priced")
        return dict(counts)

    with session_scope(ctx.engine) as s:
        due = [d for user in _users(s) for d in _due(s, _person(s, user, ctx.run_date), live, ctx.run_date)]
        used = s.scalar(
            select(func.count()).where(GemFare.run_date == ctx.run_date, GemFare.depart_date.is_not(None))
        )
        s.expunge_all()
    counts["priced_due"] = len(due)
    keys = sorted({(o, a, m) for d in due for o in d.person.homes for a in d.gem.airports for m in d.months})
    found = _scan(ctx, keys, geo, counts)

    source = next((src for src in ctx.live_sources if src.name == LIVE_SOURCE), None)
    catalog = AirportCatalog.load()
    for d in due:
        answered, candidate = _cheapest(ctx, d, found)
        if not answered:  # every scan for it failed: try again next run rather than store a miss
            continue
        if candidate is None:
            if not ctx.dry_run:
                with session_scope(ctx.engine) as s:
                    s.add(_miss(ctx, d))
                counts["none"] += 1
            continue
        if source is None:
            log.warning(
                "no %s source: gem %s left unpriced for user %s", LIVE_SOURCE, d.gem.slug, d.person.user.id
            )
            continue
        if used >= config.GEM_LIVE_CHECKS_PER_DAY:
            counts["held_live_cap"] += 1
            continue
        used += 1
        if ctx.dry_run:  # no live call and no row: the day's real allowance stays whole
            counts["would_check"] += 1
            continue
        if counts["checked"]:
            ctx.sleep(ctx.rng.uniform(*config.LIVE_DELAY_S))
        row = _check(ctx, source, candidate, catalog)
        with session_scope(ctx.engine) as s:
            s.add(row)
        counts["checked"] += 1
        counts[row.status] += 1
    return dict(counts)
