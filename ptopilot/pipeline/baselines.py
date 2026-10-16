"""Stage `baselines`: typical price and spread per (origin, airport, month, trip-length bucket) (spec §7).

Uses the trailing BASELINE_WINDOW_DAYS of observations, cached and verified alike, keeping only the
cheapest price per exact date pair per day so heavily-checked routes don't dominate. The latest
Google typical range for the key (from SerpApi) seeds cold-start baselines.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.core.stats import compute_baseline
from ptopilot.db.models import PriceObservation, RouteBaseline
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import BaselineKey, baseline_key, start_of, todays_route_queries


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    since = start_of(ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS))
    until = start_of(ctx.run_date + timedelta(days=1))
    with session_scope(ctx.engine) as s:
        rqs = todays_route_queries(s, ctx.run_date)
        wanted = {baseline_key(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date) for rq in rqs}
        routes = {(k[0], k[1]) for k in wanted}
        daily_min: dict[tuple, Decimal] = {}
        google: dict[BaselineKey, tuple[object, Decimal, Decimal]] = {}
        rows = s.scalars(
            select(PriceObservation).where(
                PriceObservation.observed_at >= since,
                PriceObservation.observed_at < until,
                PriceObservation.depart_date.is_not(None),
                PriceObservation.return_date.is_not(None),
            )
        )
        for o in rows:
            if (o.origin, o.dest_airport) not in routes:
                continue
            key = baseline_key(o.origin, o.dest_airport, o.depart_date, o.return_date)
            if key not in wanted:
                continue
            day_key = (key, o.depart_date, o.return_date, o.observed_at.date())
            if day_key not in daily_min or o.price < daily_min[day_key]:
                daily_min[day_key] = o.price
            if o.typical_low is not None and o.typical_high is not None:
                if key not in google or o.observed_at > google[key][0]:
                    google[key] = (o.observed_at, o.typical_low, o.typical_high)

        prices: defaultdict[BaselineKey, list[float]] = defaultdict(list)
        for (key, *_), price in daily_min.items():
            prices[key].append(float(price))

        for key in sorted(wanted):
            g = google.get(key)
            b = compute_baseline(prices[key], (float(g[1]), float(g[2])) if g else None)
            if b is None:
                counts["no_data"] += 1
                continue
            values = {
                "median": Decimal(str(round(b.median, 2))),
                "sigma": Decimal(str(round(b.sigma, 2))),
                "n": b.n,
                "confidence": b.confidence,
                "google_typical_low": g[1] if g else None,
                "google_typical_high": g[2] if g else None,
                "computed_at": ctx.stamp(),
            }
            origin, dest, month, bucket = key
            stmt = insert(RouteBaseline).values(
                origin=origin, dest_airport=dest, month=month, length_bucket=bucket, **values
            )
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["origin", "dest_airport", "month", "length_bucket"], set_=values
                )
            )
            counts[f"confidence_{b.confidence}"] += 1
    return dict(counts)
