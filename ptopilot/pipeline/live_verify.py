"""Stage `live_verify`: live exact-date checks for the shortlist, with circuit breaker and budgets (§7).

Sources are tried in order (Google Flights first, SerpApi as fallback). A source that fails
BREAKER_THRESHOLD times in a row is skipped for the rest of the run. Every attempt is recorded in
`live_checks`, which lets a same-day re-run skip routes already checked (even ones with no flights) and
caps budgeted sources (SerpApi) per day; the monthly cap lives in `source_budget`. Instant alerts' searches
for the flight home are recorded too (purpose 'return'): they count toward the budgets, never as a route
checked.
Open-jaw queries go only to sources with `supports_open_jaw` (SerpApi); skipping a source that can't
price them never counts toward its circuit breaker.
Every option a source returns is stored as a verified observation; per-user filtering happens in `score`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.db.models import LiveCheck, PriceObservation, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import month_of
from ptopilot.sources.base import ExactQuery, ExactResult, ExactSearchSource, SourceUnavailable

log = logging.getLogger(__name__)


class Budget:
    """Per-day caps (counted from live_checks, so they survive re-runs) and per-month caps (source_budget)."""

    def __init__(self, ctx: RunContext):
        self._ctx = ctx
        self._period = month_of(ctx.run_date)

    def allows(self, source: str) -> bool:
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return True
        if self.used_today(source) >= caps["per_day"]:
            return False
        return self.used_this_month(source) < caps["per_month"]

    def remaining_today(self, source: str) -> int | None:
        """Calls this source may still make today (None = unbudgeted)."""
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return None
        left = min(
            caps["per_day"] - self.used_today(source), caps["per_month"] - self.used_this_month(source)
        )
        return max(left, 0)

    def used_today(self, source: str) -> int:
        with session_scope(self._ctx.engine) as s:
            return s.scalar(
                select(func.count()).where(
                    LiveCheck.source == source, LiveCheck.run_date == self._ctx.run_date
                )
            )

    def used_this_month(self, source: str) -> int:
        with session_scope(self._ctx.engine) as s:
            return (
                s.scalar(select(SourceBudget.calls_used).filter_by(source=source, period=self._period)) or 0
            )

    def charge(self, source: str) -> None:
        if source not in config.SOURCE_BUDGETS:
            return
        stmt = insert(SourceBudget).values(source=source, period=self._period, calls_used=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SourceBudget.source, SourceBudget.period],
            set_={"calls_used": SourceBudget.calls_used + 1},
        )
        with session_scope(self._ctx.engine) as s:
            s.execute(stmt)


def store_options(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    """Store every option of a live result as a verified observation of this route query."""
    low, high = result.typical_range or (None, None)
    with session_scope(ctx.engine) as s:
        for o in result.options:
            s.add(
                PriceObservation(
                    origin=rq.origin,
                    dest_airport=rq.dest_airport,
                    return_airport=rq.return_airport,
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
                    longest_layover_min=o.longest_layover_min,
                    longest_layover_airport=o.longest_layover_airport,
                    deep_link=result.deep_link,
                    verified=True,
                    observed_at=ctx.stamp(),
                    typical_low=None if low is None else Decimal(str(low)),
                    typical_high=None if high is None else Decimal(str(high)),
                )
            )
    return len(result.options)


def store_history(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    """Store Google's daily price history (SerpApi) for this route query, each point on its own day.

    Unverified and under HISTORY_SOURCE, so it feeds baselines but never becomes a price a user sees.
    Points outside the trailing baseline window (or after the run date), and days already stored for this
    trip (a later SerpApi call returns mostly the same history), are dropped. Returns the number stored."""
    first = ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS)
    with session_scope(ctx.engine) as s:
        stored_days = {
            when.date()
            for when in s.scalars(
                select(PriceObservation.observed_at).where(
                    PriceObservation.source == config.HISTORY_SOURCE,
                    PriceObservation.origin == rq.origin,
                    PriceObservation.dest_airport == rq.dest_airport,
                    PriceObservation.return_airport == rq.return_airport,
                    PriceObservation.depart_date == rq.depart_date,
                    PriceObservation.return_date == rq.return_date,
                )
            )
        }
        points = [
            (day, price)
            for day, price in result.price_history
            if first <= day <= ctx.run_date and day not in stored_days
        ]
        s.add_all(
            PriceObservation(
                origin=rq.origin,
                dest_airport=rq.dest_airport,
                return_airport=rq.return_airport,
                depart_date=rq.depart_date,
                return_date=rq.return_date,
                month=month_of(rq.depart_date),
                source=config.HISTORY_SOURCE,
                price=Decimal(str(price)),
                currency=result.currency,
                verified=False,
                observed_at=datetime.combine(day, time(12), UTC),
            )
            for day, price in points
        )
    return len(points)


def record_check(
    ctx: RunContext,
    rq: RouteQuery,
    source: str,
    ok: bool,
    options: int = 0,
    error: str | None = None,
    purpose: str = "trip",
):
    with session_scope(ctx.engine) as s:
        s.add(
            LiveCheck(
                run_date=ctx.run_date,
                route_query_id=rq.id,
                source=source,
                ok=ok,
                options=options,
                error=error,
                checked_at=ctx.stamp(),
                purpose=purpose,
            )
        )


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
        # A re-run of the same day skips routes already checked successfully for this run date. A budgeted
        # source's check (SerpApi, e.g. from seed_history) doesn't count for round trips: free Google still
        # prices them, which is also what gives the health audit its fast-flights vs SerpApi pairs.
        checked = {
            rq_id
            for rq_id, source, dest, ret in s.execute(
                select(
                    LiveCheck.route_query_id,
                    LiveCheck.source,
                    RouteQuery.dest_airport,
                    RouteQuery.return_airport,
                )
                .join(RouteQuery, RouteQuery.id == LiveCheck.route_query_id)
                .where(
                    LiveCheck.run_date == ctx.run_date, LiveCheck.ok.is_(True), LiveCheck.purpose == "trip"
                )
            )
            if source not in config.SOURCE_BUDGETS or ret != dest
        }

    budget = Budget(ctx)
    # Open-jaw routes can only be priced by budgeted SerpApi, so round-trip fallbacks never spend
    # the calls those routes still need.
    pending_open_jaw = sum(
        1 for rq in entries if rq.id not in checked and rq.return_airport != rq.dest_airport
    )
    consecutive_failures: Counter[str] = Counter()
    route_failures: Counter[str] = Counter()
    succeeded: set[str] = set()
    disabled: set[str] = set()
    started = ctx.clock()
    for i, rq in enumerate(entries):
        if rq.id in checked:
            counts["already_checked"] += 1
            continue
        if ctx.clock() - started > config.LIVE_VERIFY_BUDGET_S:
            counts["out_of_time"] += len(entries) - i
            break
        usable: list[ExactSearchSource] = [src for src in ctx.live_sources if src.name not in disabled]
        if not usable:
            counts["unchecked"] += len(entries) - i
            break
        query = ExactQuery(
            rq.origin,
            rq.dest_airport,
            rq.depart_date,
            rq.return_date,
            config.DEFAULT_CURRENCY,
            return_from=rq.return_airport,
        )
        if query.open_jaw:
            pending_open_jaw -= 1
        capable = [src for src in usable if src.supports_open_jaw or not query.open_jaw]
        if not capable:  # e.g. open-jaw with SerpApi unconfigured or out of budget for today
            counts["no_open_jaw_source"] += 1
            continue
        for src in capable:
            if not budget.allows(src.name):
                disabled.add(src.name)
                counts[f"{src.name}_budget_exhausted"] += 1
                continue
            if not query.open_jaw and src.supports_open_jaw and pending_open_jaw:
                left = budget.remaining_today(src.name)
                if left is not None and left <= pending_open_jaw:
                    counts[f"{src.name}_reserved_for_open_jaw"] += 1
                    continue
            budget.charge(src.name)
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
                record_check(ctx, rq, src.name, ok=False, error=str(exc))
                log.warning("%s failed for %s: %s", src.name, query, exc)
                if exc.route_specific:  # this route's problem, not an outage: leave the breaker alone
                    counts[f"{src.name}_route_failed"] += 1
                    route_failures[src.name] += 1
                    if src.name not in succeeded and route_failures[src.name] >= config.ROUTE_FAILURE_LIMIT:
                        disabled.add(src.name)  # every route failing: likely a format change, not routes
                        counts[f"{src.name}_route_breaker_tripped"] += 1
                    continue
                counts[f"{src.name}_failed"] += 1
                consecutive_failures[src.name] += 1
                if consecutive_failures[src.name] >= config.BREAKER_THRESHOLD:
                    disabled.add(src.name)
                    counts[f"{src.name}_breaker_tripped"] += 1
                continue
            consecutive_failures[src.name] = 0
            succeeded.add(src.name)
            counts[f"{src.name}_ok"] += 1
            counts["options_stored"] += store_options(ctx, rq, result)
            counts["history_points_stored"] += store_history(ctx, rq, result)
            record_check(ctx, rq, src.name, ok=True, options=len(result.options))
            if not result.options:
                counts["no_flights"] += 1
            break
        else:
            counts["all_sources_failed"] += 1
        if i < len(entries) - 1:
            ctx.sleep(ctx.rng.uniform(*config.LIVE_DELAY_S))

    successes = sum(v for k, v in counts.items() if k.endswith("_ok"))
    # Routes no configured source can price (open-jaw without SerpApi) were never attempted: not a failure.
    pending = len(entries) - counts["already_checked"] - counts["no_open_jaw_source"]
    if pending and not successes:
        raise StageFailed(f"no live check succeeded for {pending} shortlisted routes: {dict(counts)}")
    return dict(counts)
