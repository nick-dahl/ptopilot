from datetime import timedelta

from tests.pipeline.conftest import RUN, add_observation
from tests.pipeline.test_score_v2 import TRIP, baseline, candidate, setup


def test_score_stores_expected_days(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    dips = {50: 3, 49: 3, 48: 3, 40: 3, 39: 3, 38: 3, 30: 3, 29: 3, 28: 3}
    for ago in range(58, 0, -1):
        add_observation(ctx.engine, *TRIP, 700 if ago in dips else 1000, observed=RUN - timedelta(days=ago))
    add_observation(ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780)
    from ptopilot.pipeline import score

    score.run(ctx)
    assert candidate(ctx.engine).expected_days == 3


def test_without_dips_expected_days_is_null(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780)
    from ptopilot.pipeline import score

    score.run(ctx)
    assert candidate(ctx.engine).expected_days is None


def test_a_dip_with_too_little_history_is_flagged_thin(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    for ago in range(20, 0, -1):
        add_observation(ctx.engine, *TRIP, 1000, observed=RUN - timedelta(days=ago))
    add_observation(ctx.engine, *TRIP, 700, observed=RUN, verified=True, stops=1, duration_min=780)
    from ptopilot.pipeline import score

    score.run(ctx)
    c = candidate(ctx.engine)
    assert c.expected_days is None and c.duration_thin is True


def test_no_dip_today_is_not_thin(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    for ago in range(20, 0, -1):
        add_observation(ctx.engine, *TRIP, 1000, observed=RUN - timedelta(days=ago))
    add_observation(ctx.engine, *TRIP, 1000, observed=RUN, verified=True, stops=1, duration_min=780)
    from ptopilot.pipeline import score

    score.run(ctx)
    c = candidate(ctx.engine)
    assert c.expected_days is None and c.duration_thin is False
