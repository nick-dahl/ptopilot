from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from ptopilot.core.stats import compute_baseline, z_score
from ptopilot.db.models import Candidate, PriceObservation, RouteBaseline, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, score
from tests.pipeline.conftest import RUN, add_observation, add_tracker, add_user

JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 12), date(2027, 6, 20))


def baseline(engine, median=1000, sigma=50, confidence="normal"):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                month=JUNE,
                length_bucket="week",
                median=Decimal(median),
                sigma=Decimal(sigma),
                n=20,
                confidence=confidence,
            )
        )


def setup(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    return ctx


def candidate(engine):
    with session_scope(engine) as s:
        return s.execute(
            select(Candidate)
            .join(RouteQuery)
            .where(RouteQuery.depart_date == TRIP[0], Candidate.run_date == RUN)
        ).scalar_one()


def history(engine, prices, source_verified=False):
    for i, p in enumerate(prices, start=1):
        add_observation(engine, *TRIP, p, observed=RUN - timedelta(days=i), verified=source_verified)


def test_a_cheap_trip_is_judged_against_its_own_history(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)  # route-month: median 1000, sigma 50
    prices = [690 + (i % 5) * 5 for i in range(20)]  # the trip's own history, ~700
    history(ctx.engine, prices)
    add_observation(ctx.engine, *TRIP, 680, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    c = candidate(ctx.engine)
    own = compute_baseline([float(p) for p in prices])
    assert c.z == z_score(680.0, own) and c.z > -6.4
    assert c.deal_level != "great"


def test_without_trip_history_the_route_baseline_is_used(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    history(ctx.engine, [700] * 9)  # one short of TRIP_HISTORY_MIN
    add_observation(ctx.engine, *TRIP, 680, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    assert candidate(ctx.engine).z == (680 - 1000) / 50


def test_a_ruled_out_fare_does_not_count_as_trip_history(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    # Ten earlier days of a tracked trip whose candidates were all ruled out: no history at all.
    add_observation(ctx.engine, *TRIP, 680, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    with session_scope(ctx.engine) as s:
        c = s.scalars(select(Candidate)).one()
        tracker_id, user_id, rq_id = c.tracker_id, c.user_id, c.route_query_id
        for i in range(1, 11):
            s.add(
                Candidate(
                    user_id=user_id,
                    tracker_id=tracker_id,
                    route_query_id=rq_id,
                    run_date=RUN - timedelta(days=i),
                    price=Decimal(700),
                    currency="USD",
                    z=None,
                    deal_level="none",
                    go_now=0,
                    confidence="normal",
                    verified=True,
                    verdict="ruled_out",
                )
            )
    history(ctx.engine, [700] * 10)  # observations exist, but those days were ruled out
    score.run(ctx)
    assert candidate(ctx.engine).z == (680 - 1000) / 50


def test_unverified_or_low_confidence_prices_cannot_max_the_deal_part(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine, median=1000, sigma=100)
    add_observation(ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    c = candidate(ctx.engine)
    assert c.z == -3.0
    verified_go = c.go_now
    with session_scope(ctx.engine) as s:
        s.execute(delete(PriceObservation).where(PriceObservation.verified.is_(True)))
    add_observation(ctx.engine, *TRIP, 700, observed=RUN)  # cached, unverified
    score.run(ctx)
    c = candidate(ctx.engine)
    assert (c.verified, c.z) == (False, -3.0) and c.go_now == verified_go - 25
    # a low-confidence baseline caps a verified price too
    with session_scope(ctx.engine) as s:
        s.execute(delete(PriceObservation))
        s.query(RouteBaseline).update({"confidence": "low"})
    add_observation(ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    assert candidate(ctx.engine).go_now == verified_go - 25
