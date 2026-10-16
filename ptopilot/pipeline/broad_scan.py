"""Stage `broad_scan`: one cached month scan per (origin, airport, month) needed today (spec §7)."""

from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal

from ptopilot import config
from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import month_of, todays_route_queries
from ptopilot.sources.base import SourceUnavailable

log = logging.getLogger(__name__)


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.month_source is None:
        raise StageSkipped("no month-scan source configured (set TRAVELPAYOUTS_TOKEN)")
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        keys = sorted(
            {
                (rq.origin, rq.dest_airport, month_of(rq.depart_date))
                for rq in todays_route_queries(s, ctx.run_date)
            }
        )
    last_error = ""
    for origin, dest, month in keys:
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
        with session_scope(ctx.engine) as s:
            for q in quotes:
                if q.return_date is None:
                    continue
                s.add(
                    PriceObservation(
                        origin=q.origin,
                        dest_airport=q.dest_airport,
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
                )
                counts["quotes"] += 1
    if keys and not counts["scans_ok"]:
        raise StageFailed(f"all {len(keys)} month scans failed; last error: {last_error}")
    return dict(counts)
