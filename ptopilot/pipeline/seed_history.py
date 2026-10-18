"""Stage `seed_history`: give baselines Google's own price history instead of weeks of waiting (V2 spec §2).

A SerpApi round-trip search returns ~60 days of Google's daily prices for the searched dates. One call per
baseline key (origin, airport, month, length bucket) that isn't confident yet stores that history, which
the `baselines` stage then uses like any other observation. Keys are skipped once seeded (history within the
baseline window), or for SEED_RETRY_DAYS after a SerpApi call on them returned no history. Open-jaw routes
(multi-city results carry no history) and departures beyond LIVE_HORIZON_DAYS are never seeded.

Runs before `live_verify` and leaves SEED_RESERVE_FOR_OPEN_JAW of the day's SerpApi calls for open-jaw
routes, which only SerpApi can price.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select

from ptopilot import config
from ptopilot.db.models import (
    LiveCheck,
    PriceObservation,
    RouteBaseline,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
)
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageSkipped
from ptopilot.pipeline.live_verify import Budget, record_check, store_history, store_options
from ptopilot.pipeline.queries import (
    BaselineKey,
    baseline_key,
    rq_baseline_key,
    start_of,
    todays_route_queries,
)
from ptopilot.sources.base import ExactQuery, SourceUnavailable


def _keys_to_seed(ctx: RunContext) -> list[tuple[BaselineKey, RouteQuery]]:
    """Unseeded, not-yet-confident round-trip keys in the horizon, each with its representative trip."""
    since = start_of(ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS))
    with session_scope(ctx.engine) as s:
        rqs = [
            rq
            for rq in todays_route_queries(s, ctx.run_date)
            if rq.return_airport == rq.dest_airport
            and (rq.depart_date - ctx.run_date).days <= config.LIVE_HORIZON_DAYS
        ]
        confident = {
            (b.origin, b.dest_airport, b.return_airport, b.month, b.length_bucket)
            for b in s.scalars(select(RouteBaseline).where(RouteBaseline.confidence == "normal"))
        }
        seeded = {
            baseline_key(o.origin, o.dest_airport, o.return_airport, o.depart_date, o.return_date)
            for o in s.scalars(
                select(PriceObservation).where(
                    PriceObservation.source == config.HISTORY_SOURCE, PriceObservation.observed_at >= since
                )
            )
        }
        tried = set(
            s.scalars(
                select(LiveCheck.route_query_id).where(
                    LiveCheck.source == "serpapi",
                    LiveCheck.ok.is_(True),
                    LiveCheck.run_date > ctx.run_date - timedelta(days=config.SEED_RETRY_DAYS),
                )
            )
        )
        priority = dict(
            s.execute(
                select(TrackerRouteLink.route_query_id, func.min(Tracker.priority))
                .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
                .where(TrackerRouteLink.run_date == ctx.run_date)
                .group_by(TrackerRouteLink.route_query_id)
            ).all()
        )
        s.expunge_all()
    by_key: defaultdict[BaselineKey, list[RouteQuery]] = defaultdict(list)
    for rq in rqs:
        by_key[rq_baseline_key(rq)].append(rq)
    picks = []
    for key, trips in by_key.items():
        if key in confident or key in seeded or any(rq.id in tried for rq in trips):
            continue
        rep = min(trips, key=lambda rq: (priority.get(rq.id, 2), rq.depart_date, rq.id))
        picks.append((key, rep))
    picks.sort(key=lambda kr: (priority.get(kr[1].id, 2), kr[1].depart_date, kr[0]))
    return picks


def run(ctx: RunContext) -> dict[str, int]:
    src = next((s for s in ctx.live_sources if getattr(s, "provides_history", False)), None)
    if src is None:
        raise StageSkipped("no live source provides Google price history (set SERPAPI_KEY)")
    counts: Counter[str] = Counter()
    picks = _keys_to_seed(ctx)
    counts["keys_needing_seed"] = len(picks)
    budget = Budget(ctx)
    left = budget.remaining_today(src.name)
    allowed = config.LIVE_CHECK_CAP if left is None else max(0, left - config.SEED_RESERVE_FOR_OPEN_JAW)
    failures = 0
    for i, (_, rq) in enumerate(picks):
        if allowed <= 0 or not budget.allows(src.name):
            counts["budget_exhausted"] = len(picks) - i
            break
        allowed -= 1
        budget.charge(src.name)
        query = ExactQuery(
            rq.origin, rq.dest_airport, rq.depart_date, rq.return_date, config.DEFAULT_CURRENCY
        )
        try:
            result = src.exact_search(query)
        except SourceUnavailable as exc:
            record_check(ctx, rq, src.name, ok=False, error=str(exc))
            counts[f"{src.name}_failed"] += 1
            if exc.route_specific:
                continue
            failures += 1
            if failures >= config.BREAKER_THRESHOLD:
                counts["breaker_tripped"] = 1
                break
            continue
        failures = 0
        counts["options_stored"] += store_options(ctx, rq, result)
        points = store_history(ctx, rq, result)
        counts["points_stored"] += points
        counts["seeded" if points else "no_history"] += 1
        record_check(ctx, rq, src.name, ok=True, options=len(result.options))
    return dict(counts)
