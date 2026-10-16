from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from ptopilot.db.models import Candidate, PriceObservation, RouteBaseline, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, score
from ptopilot.pipeline.score import pick_option
from tests.pipeline.conftest import RUN, add_observation, add_tracker, add_user

JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 12), date(2027, 6, 20))
USER = SimpleNamespace(
    max_stops_short=1, max_stops_long=2, allow_overnight_layover=False, friday_evening_min_time=time(17, 0)
)


def obs(id, price, stops=1, duration=780, dep=time(18, 0), overnight=False):
    return PriceObservation(
        id=id,
        price=Decimal(price),
        stops=stops,
        duration_min=duration,
        outbound_departure=datetime.combine(date(2027, 6, 12), dep),
        overnight_layover=overnight,
    )


def test_pick_option_applies_every_filter():
    options = [
        obs(1, 500, stops=3),  # too many stops for long haul (fastest 780 min >= 600)
        obs(2, 520, overnight=True),  # overnight layover not allowed
        obs(3, 540, duration=1200),  # > 1.5x fastest (780)
        obs(4, 600),
        obs(5, 650, stops=0),
    ]
    assert pick_option(options, USER, evening_departure=False).id == 4


def test_pick_option_short_haul_uses_short_stop_limit():
    options = [obs(1, 200, stops=2, duration=300), obs(2, 250, stops=1, duration=320)]
    assert pick_option(options, USER, evening_departure=False).id == 2


def test_pick_option_evening_variant_needs_late_departure():
    options = [obs(1, 500, dep=time(9, 0)), obs(2, 600, dep=time(19, 30))]
    assert pick_option(options, USER, evening_departure=True).id == 2
    assert pick_option(options, USER, evening_departure=False).id == 1


def test_pick_option_none_when_nothing_passes():
    assert pick_option([obs(1, 500, stops=4)], USER, evening_departure=False) is None
    assert pick_option([], USER, evening_departure=False) is None


def candidates(engine):
    with session_scope(engine) as s:
        rows = s.execute(select(Candidate, RouteQuery).join(RouteQuery)).all()
        return {(rq.depart_date, rq.return_date): c for c, rq in rows}


def baseline(engine, median=1000, sigma=100):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="ORD",
                dest_airport="LIS",
                month=JUNE,
                length_bucket="week",
                median=Decimal(median),
                sigma=Decimal(sigma),
                n=20,
                confidence="normal",
            )
        )


def setup(make_ctx, **tracker_fields):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine), **tracker_fields)
    expand.run(ctx)
    return ctx


def test_verified_price_scored_against_baseline(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(ctx.engine, *TRIP, 820, observed=RUN, verified=True, stops=1, duration_min=780)
    add_observation(ctx.engine, *TRIP, 790, observed=RUN, verified=True, stops=3, duration_min=780)
    counts = score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.price, c.verified, c.confidence) == (820, True, "normal")
    assert c.z == -1.8 and c.deal_level == "great"
    assert 0 < c.go_now <= 100
    assert counts["deal_great"] == 1


def test_cached_exact_fare_is_an_unverified_fallback(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, *TRIP, 900, observed=RUN)
    score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.price, c.verified, c.z, c.deal_level, c.confidence) == (900, False, None, "none", "low")


def test_month_level_fares_never_become_a_candidate_price(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, date(2027, 6, 2), date(2027, 6, 9), 300, observed=RUN)
    counts = score.run(ctx)
    assert counts == {"no_price": 6}


def test_max_price_drops_expensive_trips(make_ctx):
    ctx = setup(make_ctx, max_price=Decimal(800))
    add_observation(ctx.engine, *TRIP, 900, observed=RUN, verified=True, stops=1, duration_min=780)
    assert score.run(ctx)["over_max_price"] == 1
    assert candidates(ctx.engine) == {}


def test_rerun_replaces_the_days_candidates(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, *TRIP, 900, observed=RUN)
    score.run(ctx)
    score.run(ctx)
    with session_scope(ctx.engine) as s:
        assert len(list(s.scalars(select(Candidate)))) == 1


def test_no_cached_fallback_when_live_options_were_all_rejected(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, *TRIP, 650, observed=RUN, verified=True, stops=3, duration_min=780)
    add_observation(ctx.engine, *TRIP, 600, observed=RUN)  # cached fare, probably the same 3-stop flight
    counts = score.run(ctx)
    assert counts["rejected_by_filters"] == 1
    assert TRIP not in candidates(ctx.engine)
