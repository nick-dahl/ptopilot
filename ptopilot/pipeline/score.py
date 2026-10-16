"""Stage `score`: one candidate per tracker link with a price, judged against its baseline (spec §7).

Price choice per link: the cheapest of today's verified options that pass the user's filters
(stops, duration, overnight layovers, Friday-evening departure time); otherwise a cached fare for the
exact same dates. Month-level minimums only steer the shortlist; they never become a candidate's price.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import delete, select

from ptopilot import config
from ptopilot.core.scoring import go_now
from ptopilot.core.stats import deal_level, z_score
from ptopilot.db.models import Candidate, PriceObservation, RouteQuery, Tracker, TrackerRouteLink, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    DateKey,
    baseline_key,
    cached_prices,
    date_key,
    load_baselines,
    start_of,
    todays_route_queries,
)


def pick_option(
    options: list[PriceObservation], user: User, evening_departure: bool
) -> PriceObservation | None:
    """Cheapest verified option that passes this user's filters."""
    if not options:
        return None
    durations = [o.duration_min for o in options if o.duration_min]
    fastest = min(durations) if durations else None
    long_haul = fastest is not None and fastest >= config.SHORT_HAUL_MAX_MIN
    max_stops = user.max_stops_long if long_haul else user.max_stops_short
    ok = []
    for o in options:
        if o.stops is not None and o.stops > max_stops:
            continue
        if fastest and o.duration_min and o.duration_min > config.MAX_DURATION_RATIO * fastest:
            continue
        if o.overnight_layover and not user.allow_overnight_layover:
            continue
        if evening_departure and (
            o.outbound_departure is None or o.outbound_departure.time() < user.friday_evening_min_time
        ):
            continue
        ok.append(o)
    return min(ok, key=lambda o: (o.price, o.id), default=None)


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        s.execute(delete(Candidate).where(Candidate.run_date == ctx.run_date))
        rqs = todays_route_queries(s, ctx.run_date)
        exact, _ = cached_prices(s, rqs, ctx.run_date)
        baselines = load_baselines(s)
        wanted = {date_key(rq) for rq in rqs}
        verified: defaultdict[DateKey, list[PriceObservation]] = defaultdict(list)
        for o in s.scalars(
            select(PriceObservation).where(
                PriceObservation.verified.is_(True),
                PriceObservation.observed_at >= start_of(ctx.run_date),
                PriceObservation.observed_at < start_of(ctx.run_date + timedelta(days=1)),
            )
        ):
            key = (o.origin, o.dest_airport, o.depart_date, o.return_date)
            if key in wanted:
                verified[key].append(o)

        rows = s.execute(
            select(TrackerRouteLink, RouteQuery, Tracker, User)
            .join(RouteQuery, RouteQuery.id == TrackerRouteLink.route_query_id)
            .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
            .join(User, User.id == Tracker.user_id)
            .where(TrackerRouteLink.run_date == ctx.run_date)
            .order_by(TrackerRouteLink.id)
        ).all()
        for link, rq, tracker, user in rows:
            chosen = pick_option(verified[date_key(rq)], user, link.evening_departure)
            if chosen is not None:
                price, obs_id, is_verified, currency = chosen.price, chosen.id, True, chosen.currency
            elif (est := exact.get(date_key(rq))) is not None:  # exact dates only, never a month minimum
                price, obs_id, is_verified, currency = (
                    est.price,
                    est.observation_id,
                    False,
                    config.DEFAULT_CURRENCY,
                )
            else:
                counts["no_price"] += 1
                continue
            if tracker.max_price is not None and price > tracker.max_price:
                counts["over_max_price"] += 1
                continue
            b = baselines.get(baseline_key(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date))
            z = z_score(float(price), b) if b else None
            dest = ctx.geo.destination(tracker.destination_code)
            s.add(
                Candidate(
                    user_id=user.id,
                    tracker_id=tracker.id,
                    route_query_id=rq.id,
                    price_observation_id=obs_id,
                    run_date=ctx.run_date,
                    evening_departure=link.evening_departure,
                    price=price,
                    currency=currency,
                    z=z,
                    deal_level=deal_level(z) if z is not None else "none",
                    go_now=go_now(
                        z,
                        link.season_rating,  # type: ignore[arg-type]
                        link.efficiency,
                        (rq.depart_date - ctx.run_date).days,
                        ctx.geo.is_international(rq.origin, dest),
                    ),
                    confidence=b.confidence if b else "low",
                    verified=is_verified,
                )
            )
            counts["candidates"] += 1
            counts["verified" if is_verified else "unverified"] += 1
            if z is not None:
                counts[f"deal_{deal_level(z)}"] += 1
    return dict(counts)
