"""Stage `shortlist`: order every in-horizon trip for a live check (spec §7, Plan 18).

Every route query departing within LIVE_HORIZON_DAYS is queued, in check order:
1. Not fresh today (no ok trip check yet, from any source): longest waiting first, by the day of the last
   fresh check (a trip never fresh goes before everything; checks seconds apart count as the same wait),
   then the most promising. Reason `deal` when the cached price is at or below ~p35 of a confident
   baseline (promise = deal strength x urgency x tracker priority), else `explore` (promise 0).
   Staleness looks only at checks before today, so a later run the same day orders the rest the same way.
   Known-unpriceable trips (latest check failed for a route-specific reason) go after every other
   not-fresh trip: still retried, but they must never head every run (and trip Google's route breaker).
2. `audit`: round trips whose only fresh price today came from a budgeted source (SerpApi); a free Google
   check can still confirm or correct them.
3. `second`: fresh trips that are hot, at most SECOND_CHECKS_PER_RUN: the last live price is a deal or near
   one, the trip departs within SOON_DAYS, or its live prices swing (coefficient of variation >= VOLATILE_CV).
   Near-deal first, then soonest, then most volatile.

Hot signals count one live price per check, its cheapest itinerary. Only active trackers' trips are queued.

Departures more than LIVE_HORIZON_DAYS out are left alone: Google can't price them yet. Open-jaw routes
are capped at what open-jaw-capable sources (SerpApi) can still price today.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, timedelta
from statistics import fmean, pstdev

from sqlalchemy import Integer, and_, any_, bindparam, delete, func, select
from sqlalchemy.dialects.postgresql import ARRAY

from ptopilot import config
from ptopilot.core.stats import z_score
from ptopilot.db.models import PriceObservation, RouteQuery, ShortlistEntry, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.freshness import fresh_on, google_fresh_on, known_unpriceable, last_fresh
from ptopilot.pipeline.live_verify import Budget
from ptopilot.pipeline.queries import (
    cached_prices,
    date_key,
    estimate,
    load_baselines,
    rq_baseline_key,
    start_of,
    todays_route_queries,
)

NEVER = date.min
UNLIMITED = 1_000_000  # open-jaw capacity of a source with no daily budget


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
                return UNLIMITED
            total += left
    return total


def _live_prices(s, rq_ids: list[int], run_date) -> dict:
    """Each listed trip's live price per check over the baseline window, oldest first.

    A check stores every itinerary it found; only its cheapest is the trip's price at that moment."""
    prices: dict = {}
    if not rq_ids:
        return prices
    trip = (
        PriceObservation.origin,
        PriceObservation.dest_airport,
        PriceObservation.return_airport,
        PriceObservation.depart_date,
        PriceObservation.return_date,
    )
    same_trip = and_(
        RouteQuery.origin == PriceObservation.origin,
        RouteQuery.dest_airport == PriceObservation.dest_airport,
        RouteQuery.return_airport == PriceObservation.return_airport,
        RouteQuery.depart_date == PriceObservation.depart_date,
        RouteQuery.return_date == PriceObservation.return_date,
    )
    rows = s.execute(
        select(*trip, func.min(PriceObservation.price))
        .join(RouteQuery, same_trip)
        .where(
            # one array parameter, however many trips are fresh
            RouteQuery.id == any_(bindparam("rq_ids", rq_ids, type_=ARRAY(Integer))),
            PriceObservation.verified.is_(True),
            PriceObservation.observed_at >= start_of(run_date - timedelta(days=config.BASELINE_WINDOW_DAYS)),
            PriceObservation.observed_at < start_of(run_date + timedelta(days=1)),
        )
        .group_by(*trip, PriceObservation.observed_at)
        .order_by(PriceObservation.observed_at)
    )
    for *key, price in rows:
        prices.setdefault(tuple(key), []).append(float(price))
    return prices


def _hot_rank(rq: RouteQuery, prices: list[float], baseline, run_date) -> tuple | None:
    """Sort key if this fresh trip deserves a second check (near-deal, then soonest, then most volatile)."""
    if prices and baseline is not None and baseline.n >= config.COLD_START_N:
        z = z_score(prices[-1], baseline)
        if z <= config.GOOD_DEAL_Z + config.NEAR_DEAL_Z_MARGIN:
            return (0, z, rq.id)
    if (rq.depart_date - run_date).days <= config.SOON_DAYS:
        return (1, rq.depart_date, rq.id)
    if len(prices) >= 2 and (mean := fmean(prices)) > 0:
        cv = pstdev(prices) / mean
        if cv >= config.VOLATILE_CV:
            return (2, -cv, rq.id)
    return None


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        s.execute(delete(ShortlistEntry).where(ShortlistEntry.run_date == ctx.run_date))
        rqs = todays_route_queries(s, ctx.run_date, active_only=True)
        exact, monthly = cached_prices(s, rqs, ctx.run_date)
        baselines = load_baselines(s)
        best_priority = dict(
            s.execute(
                select(TrackerRouteLink.route_query_id, func.min(Tracker.priority))
                .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
                .where(TrackerRouteLink.run_date == ctx.run_date, Tracker.active.is_(True))
                .group_by(TrackerRouteLink.route_query_id)
            ).all()
        )
        in_horizon = [rq for rq in rqs if (rq.depart_date - ctx.run_date).days <= config.LIVE_HORIZON_DAYS]
        counts["beyond_horizon"] = len(rqs) - len(in_horizon)
        fresh, google_fresh = fresh_on(s, ctx.run_date), google_fresh_on(s, ctx.run_date)
        # Only checks from before today: a same-day re-run must order the not-yet-fresh trips the same way.
        seen = last_fresh(s, [rq.id for rq in in_horizon], before=start_of(ctx.run_date))
        unpriceable = known_unpriceable(s, [rq.id for rq in in_horizon if rq.id not in fresh])
        live = _live_prices(s, [rq.id for rq in in_horizon if rq.id in fresh], ctx.run_date)

        first, audits, seconds = [], [], []  # (sort key, route query, reason, estimated price)
        for rq in in_horizon:
            est = estimate(rq, exact, monthly)
            price = est.price if est else None
            b = baselines.get(rq_baseline_key(rq))
            if rq.id in fresh:
                if rq.return_airport == rq.dest_airport and rq.id not in google_fresh:
                    audits.append(((rq.depart_date, rq.id), rq, "audit", price))
                elif hot := _hot_rank(rq, live.get(date_key(rq), []), b, ctx.run_date):
                    seconds.append((hot, rq, "second", price))
                continue
            reason, promise = "explore", 0.0
            if est is not None and b is not None and b.n >= config.COLD_START_N:
                z = z_score(float(est.price), b)
                if z <= config.SHORTLIST_Z:
                    weight = config.PRIORITY_WEIGHTS.get(best_priority.get(rq.id, 2), 0.8)
                    if date_key(rq) not in exact:
                        weight *= config.MONTH_ESTIMATE_WEIGHT
                    reason = "deal"
                    promise = -z * urgency((rq.depart_date - ctx.run_date).days) * weight
                else:
                    counts["not_cheap"] += 1
            when = seen.get(rq.id)
            stale_since = when.astimezone(UTC).date() if when else NEVER
            key = (rq.id in unpriceable, stale_since, -promise, rq.depart_date, rq.id)
            first.append((key, rq, reason, price))

        first.sort(key=lambda e: e[0])
        audits.sort(key=lambda e: e[0])
        seconds.sort(key=lambda e: e[0])
        counts["second_overflow"] = max(0, len(seconds) - config.SECOND_CHECKS_PER_RUN)
        queue = first + audits + seconds[: config.SECOND_CHECKS_PER_RUN]

        # Open-jaw routes nobody can price today would otherwise sit at the front of the queue every day.
        room_for_open_jaw, rank = open_jaw_capacity(ctx), 0
        for _, rq, reason, price in queue:
            if rq.return_airport != rq.dest_airport:
                if room_for_open_jaw <= 0:
                    counts["open_jaw_unpriceable"] += 1
                    continue
                room_for_open_jaw -= 1
            rank += 1
            counts[reason] += 1
            s.add(
                ShortlistEntry(
                    run_date=ctx.run_date, route_query_id=rq.id, rank=rank, reason=reason, est_price=price
                )
            )
        counts["candidates"] = len(rqs)
        for reason in ("deal", "explore", "audit", "second"):
            counts[reason] += 0  # always reported, even at zero
    return dict(counts)
