"""Stage `score`: one candidate per tracker link with a price, judged against its baseline (spec §7).

Price choice per link: the cheapest of today's verified options that pass the user's filters and
aren't miserable (stops, overnight layovers, Friday-evening departure time); otherwise a cached fare for the
exact same dates. Month-level minimums only steer the shortlist; they never become a candidate's price.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import delete, select

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.misery import Assessment, assess, problems
from ptopilot.core.scoring import go_now, length_fit
from ptopilot.core.stats import deal_level, z_score
from ptopilot.db.models import Candidate, PriceObservation, RouteQuery, Tracker, TrackerRouteLink, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    DateKey,
    cached_prices,
    date_key,
    load_baselines,
    rq_baseline_key,
    start_of,
    todays_route_queries,
)


def pick_option(
    options: list[PriceObservation],
    user: User,
    evening_departure: bool,
    *,
    judge: Callable[[PriceObservation], Assessment],
) -> tuple[PriceObservation, Assessment] | None:
    """Cheapest verified option that passes this user's filters and isn't ruled out as miserable.

    When every filtered option is ruled out, the cheapest one comes back with its ruled-out assessment.
    """
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
        if o.overnight_layover and not user.allow_overnight_layover:
            continue
        if evening_departure and (
            o.outbound_departure is None or o.outbound_departure.time() < user.friday_evening_min_time
        ):
            continue
        ok.append(o)
    judged = sorted(((o, judge(o)) for o in ok), key=lambda pair: (pair[0].price, pair[0].id))
    for pair in judged:
        if pair[1].verdict != "ruled_out":
            return pair
    return judged[0] if judged else None


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    catalog = AirportCatalog.load()
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
            key = date_key(o)
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
            live_options = verified[date_key(rq)]
            b = baselines.get(rq_baseline_key(rq))
            dest = ctx.geo.destination(tracker.destination_code)
            fastest_all = min((o.duration_min for o in live_options if o.duration_min), default=None)

            def judge(o: PriceObservation, rq=rq, dest=dest, b=b, fastest_all=fastest_all) -> Assessment:
                layover = catalog.get(o.longest_layover_airport) if o.longest_layover_airport else None
                found = problems(
                    longest_layover_min=o.longest_layover_min,
                    layover_city=layover.city if layover else None,
                    duration_min=o.duration_min,
                    fastest_min=fastest_all,
                    ground_min=ctx.geo.ground_minutes(dest, rq.dest_airport),
                    destination_name=dest.name,
                )
                return assess(
                    found,
                    price=float(o.price),
                    typical_median=b.median if b else None,
                    typical_confident=bool(b and b.confidence == "normal"),
                )

            picked = pick_option(live_options, user, link.evening_departure, judge=judge)
            chosen, assessment = picked if picked else (None, Assessment("ok", (), None))
            if chosen is None and live_options:
                # Live prices exist but none fit this user; the cached fare is likely one of the same flights.
                counts["rejected_by_filters"] += 1
                continue
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
            ruled_out = assessment.verdict == "ruled_out"
            if tracker.max_price is not None and price > tracker.max_price:
                counts["over_max_price"] += 1
                continue
            z = None if ruled_out or not b else z_score(float(price), b)
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
                    go_now=0
                    if ruled_out
                    else go_now(
                        z,
                        link.season_rating,  # type: ignore[arg-type]
                        link.efficiency,
                        (rq.depart_date - ctx.run_date).days,
                        ctx.geo.is_international(rq.origin, dest),
                        length_fit=length_fit(link.days_away, tracker.target_days or user.ideal_trip_days),
                    ),
                    confidence=b.confidence if b else "low",
                    verified=is_verified,
                    verdict=assessment.verdict,
                    misery_note=assessment.note,
                )
            )
            counts["candidates"] += 1
            counts["verified" if is_verified else "unverified"] += 1
            if z is not None:
                counts[f"deal_{deal_level(z)}"] += 1
    return dict(counts)
