"""Stage `shortlist`: choose which route queries get a live check today (spec §7).

Two kinds of entry, deals first in check order:
- deal: the cached price is at or below ~p35 of a confident baseline, ranked by
  deal strength × urgency × tracker priority.
- explore: routes with too little history (n < COLD_START_N) or no cached price at all, least
  recently live-checked first (any outcome, from `live_checks`, so "no flights" counts as checked).
  EXPLORATION_QUOTA slots are reserved for these so history keeps building even on days full of deals,
  and exploration also takes any of the LIVE_CHECK_CAP slots that deals leave unused.

Departures more than LIVE_HORIZON_DAYS out are left alone: Google can't price them yet. Open-jaw routes
are capped at what open-jaw-capable sources (SerpApi) can still price today.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from ptopilot import config
from ptopilot.core.stats import z_score
from ptopilot.db.models import LiveCheck, ShortlistEntry, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.live_verify import Budget
from ptopilot.pipeline.queries import (
    cached_prices,
    date_key,
    estimate,
    load_baselines,
    rq_baseline_key,
    todays_route_queries,
)

NEVER = datetime.min


def urgency(days_until: int) -> float:
    if days_until < 30:
        return config.URGENCY["soon"]
    if days_until <= 120:
        return config.URGENCY["sweet"]
    return config.URGENCY["far"]


def open_jaw_capacity(ctx: RunContext) -> int:
    """How many open-jaw routes the configured sources can still price today."""
    budget, total = Budget(ctx), 0
    for src in ctx.live_sources:
        if src.supports_open_jaw:
            left = budget.remaining_today(src.name)
            if left is None:
                return config.LIVE_CHECK_CAP
            total += left
    return total


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        s.execute(delete(ShortlistEntry).where(ShortlistEntry.run_date == ctx.run_date))
        rqs = todays_route_queries(s, ctx.run_date)
        exact, monthly = cached_prices(s, rqs, ctx.run_date)
        baselines = load_baselines(s)
        best_priority = dict(
            s.execute(
                select(TrackerRouteLink.route_query_id, func.min(Tracker.priority))
                .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
                .where(TrackerRouteLink.run_date == ctx.run_date)
                .group_by(TrackerRouteLink.route_query_id)
            ).all()
        )
        # Only checks from before today: a same-day re-run must pick the same routes again.
        last_checked = {
            rq_id: when.replace(tzinfo=None)
            for rq_id, when in s.execute(
                select(LiveCheck.route_query_id, func.max(LiveCheck.checked_at))
                .where(LiveCheck.run_date < ctx.run_date)
                .group_by(LiveCheck.route_query_id)
            ).all()
        }

        deals: list[tuple[float, int, Decimal]] = []
        explore: list[tuple[datetime, date, int, Decimal | None, bool]] = []
        for rq in rqs:
            if (rq.depart_date - ctx.run_date).days > config.LIVE_HORIZON_DAYS:
                counts["beyond_horizon"] += 1
                continue
            est = estimate(rq, exact, monthly)
            b = baselines.get(rq_baseline_key(rq))
            if est is None or b is None or b.n < config.COLD_START_N:
                seen = last_checked.get(rq.id, NEVER)
                explore.append(
                    (
                        seen,
                        rq.depart_date,
                        rq.id,
                        est.price if est else None,
                        rq.return_airport != rq.dest_airport,
                    )
                )
                continue
            z = z_score(float(est.price), b)
            if z > config.SHORTLIST_Z:
                counts["not_cheap"] += 1
                continue
            weight = config.PRIORITY_WEIGHTS.get(best_priority.get(rq.id, 2), 0.8)
            if date_key(rq) not in exact:
                weight *= config.MONTH_ESTIMATE_WEIGHT
            score = -z * urgency((rq.depart_date - ctx.run_date).days) * weight
            deals.append((score, rq.id, est.price))

        explore.sort()
        # Open-jaw routes nobody can price today would otherwise sit at the front of the queue every day.
        room_for_open_jaw, kept = open_jaw_capacity(ctx), []
        for item in explore:
            if item[4]:
                if room_for_open_jaw <= 0:
                    counts["open_jaw_unpriceable"] += 1
                    continue
                room_for_open_jaw -= 1
            kept.append(item)
        explore = kept
        deals.sort(key=lambda d: (-d[0], d[1]))
        reserved = min(config.EXPLORATION_QUOTA, len(explore))
        picked_deals = deals[: config.LIVE_CHECK_CAP - reserved]
        picked_explore = explore[: config.LIVE_CHECK_CAP - len(picked_deals)]  # reserved + unused deal slots

        rank = 0
        for _, rq_id, price in picked_deals:
            rank += 1
            s.add(
                ShortlistEntry(
                    run_date=ctx.run_date, route_query_id=rq_id, rank=rank, reason="deal", est_price=price
                )
            )
        for _, _, rq_id, price, _ in picked_explore:
            rank += 1
            s.add(
                ShortlistEntry(
                    run_date=ctx.run_date, route_query_id=rq_id, rank=rank, reason="explore", est_price=price
                )
            )
        counts.update(
            {
                "candidates": len(rqs),
                "deal": len(picked_deals),
                "explore": len(picked_explore),
                "deal_overflow": len(deals) - len(picked_deals),
                "explore_overflow": len(explore) - len(picked_explore),
            }
        )
    return dict(counts)
