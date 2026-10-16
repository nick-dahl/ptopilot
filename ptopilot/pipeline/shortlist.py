"""Stage `shortlist`: choose which route queries get a live check today (spec §7).

Two kinds of entry, deals first in check order:
- deal: the cached price is at or below ~p35 of a confident baseline, ranked by
  deal strength × urgency × tracker priority.
- explore: routes with too little history (n < COLD_START_N) or no cached price at all, oldest
  live check first. EXPLORATION_QUOTA slots are reserved for these so history keeps building even
  on days full of deals.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from ptopilot import config
from ptopilot.core.stats import z_score
from ptopilot.db.models import PriceObservation, ShortlistEntry, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    baseline_key,
    cached_prices,
    date_key,
    estimate,
    load_baselines,
    start_of,
    todays_route_queries,
)

NEVER = datetime.min


def urgency(days_until: int) -> float:
    if days_until < 30:
        return config.URGENCY["soon"]
    if days_until <= 120:
        return config.URGENCY["sweet"]
    return config.URGENCY["far"]


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
        last_live = {
            (o, d, dep, ret): when.replace(tzinfo=None)
            for o, d, dep, ret, when in s.execute(
                select(
                    PriceObservation.origin,
                    PriceObservation.dest_airport,
                    PriceObservation.depart_date,
                    PriceObservation.return_date,
                    func.max(PriceObservation.observed_at),
                )
                # Only checks from before today: a same-day re-run must pick the same routes again.
                .where(
                    PriceObservation.verified.is_(True), PriceObservation.observed_at < start_of(ctx.run_date)
                )
                .group_by(
                    PriceObservation.origin,
                    PriceObservation.dest_airport,
                    PriceObservation.depart_date,
                    PriceObservation.return_date,
                )
            ).all()
        }

        deals: list[tuple[float, int, Decimal]] = []
        explore: list[tuple[datetime, date, int, Decimal | None]] = []
        for rq in rqs:
            est = estimate(rq, exact, monthly)
            b = baselines.get(baseline_key(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date))
            if est is None or b is None or b.n < config.COLD_START_N:
                seen = last_live.get(date_key(rq), NEVER)
                explore.append((seen, rq.depart_date, rq.id, est.price if est else None))
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
        picked_explore = explore[: config.EXPLORATION_QUOTA]
        deals.sort(key=lambda d: (-d[0], d[1]))
        picked_deals = deals[: config.LIVE_CHECK_CAP - len(picked_explore)]

        rank = 0
        for _, rq_id, price in picked_deals:
            rank += 1
            s.add(
                ShortlistEntry(
                    run_date=ctx.run_date, route_query_id=rq_id, rank=rank, reason="deal", est_price=price
                )
            )
        for _, _, rq_id, price in picked_explore:
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
