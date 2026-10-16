"""Stage `live_verify`: live exact-date checks for the shortlist, with circuit breaker and budgets (§7).

Sources are tried in order (Google Flights first, SerpApi as fallback). A source that fails
BREAKER_THRESHOLD times in a row is skipped for the rest of the run. Budgeted sources (SerpApi) are
capped per run and per calendar month via `source_budget`; every attempted call counts.
Every option a source returns is stored as a verified observation; per-user filtering happens in `score`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.db.models import PriceObservation, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import month_of, start_of
from ptopilot.sources.base import ExactQuery, ExactResult, ExactSearchSource, SourceUnavailable

log = logging.getLogger(__name__)


class Budget:
    """Per-run and per-month call caps for budgeted sources, persisted in source_budget."""

    def __init__(self, ctx: RunContext):
        self._ctx = ctx
        self._period = month_of(ctx.run_date)
        self._run_calls: Counter[str] = Counter()

    def allows(self, source: str) -> bool:
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return True
        if self._run_calls[source] >= caps["per_run"]:
            return False
        return self.used_this_month(source) < caps["per_month"]

    def used_this_month(self, source: str) -> int:
        with session_scope(self._ctx.engine) as s:
            return (
                s.scalar(select(SourceBudget.calls_used).filter_by(source=source, period=self._period)) or 0
            )

    def charge(self, source: str) -> None:
        self._run_calls[source] += 1
        if source not in config.SOURCE_BUDGETS:
            return
        stmt = insert(SourceBudget).values(source=source, period=self._period, calls_used=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SourceBudget.source, SourceBudget.period],
            set_={"calls_used": SourceBudget.calls_used + 1},
        )
        with session_scope(self._ctx.engine) as s:
            s.execute(stmt)


def _store(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    low, high = result.typical_range or (None, None)
    with session_scope(ctx.engine) as s:
        for o in result.options:
            s.add(
                PriceObservation(
                    origin=rq.origin,
                    dest_airport=rq.dest_airport,
                    depart_date=rq.depart_date,
                    return_date=rq.return_date,
                    month=month_of(rq.depart_date),
                    source=result.source,
                    price=Decimal(str(o.price)),
                    currency=result.currency,
                    carrier=o.carrier,
                    stops=o.stops,
                    duration_min=o.duration_min,
                    outbound_departure=o.outbound_departure,
                    flight_numbers=list(o.flight_numbers),
                    overnight_layover=o.overnight_layover,
                    deep_link=result.deep_link,
                    verified=True,
                    observed_at=ctx.stamp(),
                    typical_low=None if low is None else Decimal(str(low)),
                    typical_high=None if high is None else Decimal(str(high)),
                )
            )
    return len(result.options)


def run(ctx: RunContext) -> dict[str, int]:
    if not ctx.live_sources:
        raise StageSkipped("no live sources configured")
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        entries = (
            s.execute(
                select(RouteQuery)
                .join(ShortlistEntry, ShortlistEntry.route_query_id == RouteQuery.id)
                .where(ShortlistEntry.run_date == ctx.run_date)
                .order_by(ShortlistEntry.rank)
            )
            .scalars()
            .all()
        )
        # A re-run of the same day skips routes already checked for this run date.
        checked = set(
            s.execute(
                select(
                    PriceObservation.origin,
                    PriceObservation.dest_airport,
                    PriceObservation.depart_date,
                    PriceObservation.return_date,
                ).where(
                    PriceObservation.verified.is_(True),
                    PriceObservation.observed_at >= start_of(ctx.run_date),
                    PriceObservation.observed_at < start_of(ctx.run_date + timedelta(days=1)),
                )
            ).all()
        )

    budget = Budget(ctx)
    consecutive_failures: Counter[str] = Counter()
    disabled: set[str] = set()
    for i, rq in enumerate(entries):
        if (rq.origin, rq.dest_airport, rq.depart_date, rq.return_date) in checked:
            counts["already_checked"] += 1
            continue
        usable: list[ExactSearchSource] = [src for src in ctx.live_sources if src.name not in disabled]
        if not usable:
            counts["unchecked"] += len(entries) - i
            break
        query = ExactQuery(
            rq.origin, rq.dest_airport, rq.depart_date, rq.return_date, config.DEFAULT_CURRENCY
        )
        for src in usable:
            if not budget.allows(src.name):
                disabled.add(src.name)
                counts[f"{src.name}_budget_exhausted"] += 1
                continue
            budget.charge(src.name)
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
                counts[f"{src.name}_failed"] += 1
                consecutive_failures[src.name] += 1
                log.warning("%s failed for %s: %s", src.name, query, exc)
                if consecutive_failures[src.name] >= config.BREAKER_THRESHOLD:
                    disabled.add(src.name)
                    counts[f"{src.name}_breaker_tripped"] += 1
                continue
            consecutive_failures[src.name] = 0
            counts[f"{src.name}_ok"] += 1
            counts["options_stored"] += _store(ctx, rq, result)
            if not result.options:
                counts["no_flights"] += 1
            break
        else:
            counts["all_sources_failed"] += 1
        if i < len(entries) - 1:
            ctx.sleep(ctx.rng.uniform(*config.LIVE_DELAY_S))

    successes = sum(v for k, v in counts.items() if k.endswith("_ok"))
    pending = len(entries) - counts["already_checked"]
    if pending and not successes:
        raise StageFailed(f"no live check succeeded for {pending} shortlisted routes: {dict(counts)}")
    return dict(counts)
