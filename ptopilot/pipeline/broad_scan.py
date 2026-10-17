"""Stage `broad_scan`: one cached month scan per (origin, airport, month) needed today (spec §7).

Only two kinds of quote are stored, to keep the append-only table small (Neon's free tier is 0.5 GB):
the cheapest quote for each date pair some tracker wants today, and the month's single cheapest quote
(which `shortlist` uses as the month-level estimate). Route-months already scanned today are skipped.
Open-jaw routes are skipped entirely: the cache only holds plain round trips.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import date_key, month_of, start_of, todays_route_queries
from ptopilot.sources.base import FareQuote, SourceUnavailable

log = logging.getLogger(__name__)


def _keep(quotes: list[FareQuote], tracked: set) -> list[FareQuote]:
    round_trips = [q for q in quotes if q.return_date is not None]
    best: dict[tuple, FareQuote] = {}
    for q in round_trips:
        key = (q.origin, q.dest_airport, q.dest_airport, q.depart_date, q.return_date)
        if key in tracked and (key not in best or q.price < best[key].price):
            best[key] = q
    cheapest = min(round_trips, key=lambda q: q.price, default=None)
    kept = list(best.values())
    if cheapest is not None and cheapest not in kept:
        kept.append(cheapest)
    return kept


def _observation(ctx: RunContext, q: FareQuote) -> PriceObservation:
    return PriceObservation(
        origin=q.origin,
        dest_airport=q.dest_airport,
        return_airport=q.dest_airport,
        depart_date=q.depart_date,
        return_date=q.return_date,
        month=month_of(q.depart_date),
        source=q.source,
        price=Decimal(str(q.price)),
        currency=q.currency or config.DEFAULT_CURRENCY,
        carrier=q.airline,
        stops=q.stops,
        duration_min=q.duration_min,
        flight_numbers=[q.flight_number] if q.flight_number else [],
        deep_link=q.deep_link,
        verified=False,
        observed_at=ctx.stamp(),
    )


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.month_source is None:
        raise StageSkipped("no month-scan source configured (set TRAVELPAYOUTS_TOKEN)")
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        rqs = [rq for rq in todays_route_queries(s, ctx.run_date) if rq.return_airport == rq.dest_airport]
        tracked = {date_key(rq) for rq in rqs}
        keys = sorted({(rq.origin, rq.dest_airport, month_of(rq.depart_date)) for rq in rqs})
        scanned_today = set(
            s.execute(
                select(PriceObservation.origin, PriceObservation.dest_airport, PriceObservation.month).where(
                    PriceObservation.verified.is_(False),
                    PriceObservation.observed_at >= start_of(ctx.run_date),
                    PriceObservation.observed_at < start_of(ctx.run_date + timedelta(days=1)),
                )
            ).all()
        )
    last_error = ""
    for origin, dest, month in keys:
        if (origin, dest, month) in scanned_today:
            counts["already_scanned"] += 1
            continue
        try:
            quotes = ctx.month_source.month_scan(
                origin, dest, month, market=ctx.geo.airport(origin).country, currency=config.DEFAULT_CURRENCY
            )
        except SourceUnavailable as exc:
            counts["scans_failed"] += 1
            last_error = str(exc)
            log.warning("month scan %s-%s %s failed: %s", origin, dest, month, exc)
            continue
        counts["scans_ok"] += 1
        kept = _keep(quotes, tracked)
        with session_scope(ctx.engine) as s:
            s.add_all(_observation(ctx, q) for q in kept)
        counts["quotes"] += len(kept)
    if keys and not counts["scans_ok"] and not counts["already_scanned"]:
        raise StageFailed(f"all {len(keys)} month scans failed; last error: {last_error}")
    return dict(counts)
