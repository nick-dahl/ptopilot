"""Stage `live_verify`: live exact-date checks for the shortlist, with circuit breaker and budgets (§7).

Sources are tried in order (Google Flights first, SerpApi as fallback). A source that fails
BREAKER_THRESHOLD times in a row is skipped for the rest of the run. Every attempt is recorded in
`live_checks`, which lets a run skip routes it already checked (even ones with no flights), lets first-check
entries (deal/explore) skip routes already fresh today, and caps budgeted sources (SerpApi) per day; the
monthly cap lives in `source_budget`. Audit entries are the
routes only SerpApi has priced today: they are checked again, by free Google. Instant alerts' searches
for the flight home are recorded too (purpose 'return'): they count toward the budgets, never as a route
checked.
Open-jaw queries go only to sources with `supports_open_jaw` (SerpApi); skipping a source that can't
price them never counts toward its circuit breaker.
The whole shortlist is worked in order. When Google (an unbudgeted source) fails or answers empty for much of
the last BACKOFF_WINDOW attempts, pauses grow; when it does so for nearly all, the run stops and the next
scan run carries on.
Every option a source returns is stored as a verified observation; per-user filtering happens in `score`.
"""

from __future__ import annotations

import logging
from collections import Counter, deque
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.db.models import LiveCheck, PriceObservation, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.freshness import fresh_on
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
    route_specific: bool = False,
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
                route_specific=route_specific,
            )
        )


def run(ctx: RunContext) -> dict[str, int]:
    if not ctx.live_sources:
        raise StageSkipped("no live sources configured")
    counts: Counter[str] = Counter()
    run_start = ctx.stamp()
    with session_scope(ctx.engine) as s:
        rows = s.execute(
            select(RouteQuery, ShortlistEntry.reason)
            .join(ShortlistEntry, ShortlistEntry.route_query_id == RouteQuery.id)
            .where(ShortlistEntry.run_date == ctx.run_date)
            .order_by(ShortlistEntry.rank)
        ).all()
        entries = [rq for rq, _ in rows]
        reasons = [reason for _, reason in rows]
        # Fresh today (any source) before this run: first-check entries (deal/explore) that are already
        # fresh need nothing. Audit and second-check entries are for exactly such routes, so they run anyway.
        fresh = fresh_on(s, ctx.run_date)
        # Checked since this stage started (any outcome): a repeat entry of one run must not hit Google twice.
        checked = set(
            s.scalars(
                select(LiveCheck.route_query_id).where(
                    LiveCheck.run_date == ctx.run_date,
                    LiveCheck.purpose == "trip",
                    LiveCheck.checked_at >= run_start,
                )
            )
        )

    def first_check_done(i: int) -> bool:
        return reasons[i] in ("deal", "explore") and entries[i].id in fresh

    budget = Budget(ctx)
    # Open-jaw routes can only be priced by budgeted SerpApi, so round-trip fallbacks never spend
    # the calls those routes still need.
    pending_open_jaw = sum(
        1
        for i, rq in enumerate(entries)
        if rq.id not in checked and not first_check_done(i) and rq.return_airport != rq.dest_airport
    )
    window: deque[bool] = deque(maxlen=config.BACKOFF_WINDOW)  # True = bad answer from an unbudgeted source
    slowed = False
    consecutive_failures: Counter[str] = Counter()
    route_failures: Counter[str] = Counter()
    succeeded: set[str] = set()
    disabled: set[str] = set()
    started = ctx.clock()
    for i, rq in enumerate(entries):
        if rq.id in checked:
            counts["checked_this_run"] += 1
            continue
        if first_check_done(i):
            counts["already_checked"] += 1
            continue
        if len(window) == window.maxlen and sum(window) / len(window) >= config.BACKOFF_STOP_SHARE:
            counts["backoff_stopped"] += len(entries) - i
            break
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
        counts[{"second": "second_checks", "audit": "audits"}.get(reasons[i], "first_checks")] += 1
        checked.add(rq.id)
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
            unbudgeted = src.name not in config.SOURCE_BUDGETS
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
                record_check(ctx, rq, src.name, ok=False, error=str(exc), route_specific=exc.route_specific)
                log.warning("%s failed for %s: %s", src.name, query, exc)
                if unbudgeted:
                    window.append(True)
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
            fresh.add(rq.id)
            if unbudgeted:
                window.append(not result.options)
            if not result.options:
                counts["no_flights"] += 1
            break
        else:
            counts["all_sources_failed"] += 1
        if len(window) == window.maxlen and sum(window) / len(window) >= config.BACKOFF_SLOW_SHARE:
            slowed = True
            counts["backoff_slowed"] = 1
        elif len(window) == window.maxlen:
            slowed = False
        if i < len(entries) - 1:
            pause = ctx.rng.uniform(*config.LIVE_DELAY_S)
            ctx.sleep(pause * config.BACKOFF_PAUSE_FACTOR if slowed else pause)

    successes = sum(v for k, v in counts.items() if k.endswith("_ok"))
    # Entries no configured source could price (open-jaw without SerpApi) were never attempted, nor were
    # those the time budget, a tripped breaker or the back-off left over: only attempts count.
    attempted = counts["first_checks"] + counts["second_checks"] + counts["audits"]
    if attempted and not successes:
        raise StageFailed(f"no live check succeeded for {attempted} shortlisted routes: {dict(counts)}")
    return dict(counts)
