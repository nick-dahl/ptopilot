from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from ptopilot.core.misery import Assessment
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


def fine(o):
    return Assessment("ok", (), None)


def ruled(o):
    return Assessment("ruled_out", (), "bad")


def pick(options, evening=False, judge=fine):
    got = pick_option(options, USER, evening, judge=judge)
    return None if got is None else got[0].id


def test_pick_option_applies_every_filter():
    options = [
        obs(1, 500, stops=3),  # too many stops for long haul (fastest 780 min >= 600)
        obs(2, 520, overnight=True),  # overnight layover not allowed
        obs(4, 600),
        obs(5, 650, stops=0),
    ]
    assert pick(options) == 4


def test_pick_option_short_haul_uses_short_stop_limit():
    options = [obs(1, 200, stops=2, duration=300), obs(2, 250, stops=1, duration=320)]
    assert pick(options) == 2


def test_pick_option_evening_variant_needs_late_departure():
    options = [obs(1, 500, dep=time(9, 0)), obs(2, 600, dep=time(19, 30))]
    assert pick(options, evening=True) == 2
    assert pick(options) == 1


def test_pick_option_none_when_nothing_passes():
    assert pick([obs(1, 500, stops=4)]) is None
    assert pick([]) is None


def test_existing_filters_still_apply_first():
    # The judge would love these, but stops, overnight and Friday evening are decided before it is asked.
    asked = []

    def judge(o):
        asked.append(o.id)
        return fine(o)

    options = [
        obs(1, 100, stops=3),
        obs(2, 110, overnight=True),
        obs(3, 120, dep=time(9, 0)),
        obs(4, 900, dep=time(19, 0)),
    ]
    got = pick_option(options, USER, True, judge=judge)
    assert got[0].id == 4 and set(asked) <= {4}


def test_the_cheapest_acceptable_option_wins_over_a_cheaper_miserable_one():
    options = [obs(1, 300), obs(2, 400), obs(3, 500)]
    judge = lambda o: ruled(o) if o.id == 1 else fine(o)  # noqa: E731
    got = pick_option(options, USER, False, judge=judge)
    assert got[0].id == 2 and got[1].verdict == "ok"


def test_pick_option_falls_back_to_the_cheapest_ruled_out_option():
    got = pick_option([obs(1, 300), obs(2, 400)], USER, False, judge=ruled)
    assert got[0].id == 1 and got[1].verdict == "ruled_out"


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
                return_airport="LIS",
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


def test_a_trip_with_only_miserable_options_is_recorded_ruled_out(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(
        ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780,
        longest_layover_min=600, longest_layover_airport="MAD",
    )  # fmt: skip
    counts = score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.verdict, c.price, c.deal_level, c.go_now) == ("ruled_out", 700, "none", 0)
    assert c.misery_note == "10h layover in Madrid"
    assert counts["candidates"] == 1


def test_the_miserable_cheaper_option_is_skipped_for_an_acceptable_one(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(
        ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780,
        longest_layover_min=600, longest_layover_airport="MAD",
    )  # fmt: skip
    add_observation(ctx.engine, *TRIP, 900, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.verdict, c.price, c.misery_note) == ("ok", 900, None)


def test_a_forgiven_option_keeps_its_deal_level_and_note(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(
        ctx.engine, *TRIP, 550, observed=RUN, verified=True, stops=1, duration_min=780,
        longest_layover_min=390, longest_layover_airport="MAD",
    )  # fmt: skip
    score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert c.verdict == "forgiven" and c.deal_level != "none" and c.go_now > 0
    assert c.misery_note == "6h 30m layover in Madrid (worth it at 45% below typical)"


def test_a_slow_option_is_now_judged_not_dropped(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(ctx.engine, *TRIP, 2000, observed=RUN, verified=True, stops=1, duration_min=780)
    add_observation(ctx.engine, *TRIP, 550, observed=RUN, verified=True, stops=1, duration_min=1250)
    score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.verdict, c.price) == ("forgiven", 550)
    assert c.misery_note.startswith("21h journey, 1.6× the fastest")


def test_a_slow_option_without_a_deep_discount_is_ruled_out(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    fast = {
        "stops": 1,
        "duration_min": 780,
        "longest_layover_min": 600,
    }  # itself miserable, but sets "fastest"
    add_observation(ctx.engine, *TRIP, 2000, observed=RUN, verified=True, **fast)
    add_observation(ctx.engine, *TRIP, 800, observed=RUN, verified=True, stops=1, duration_min=1250)
    score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.verdict, c.price, c.deal_level, c.go_now) == ("ruled_out", 800, "none", 0)
