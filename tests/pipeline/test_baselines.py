from datetime import date

import pytest
from sqlalchemy import select

from ptopilot.db.models import RouteBaseline
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, expand
from tests.pipeline.conftest import RUN, add_observation, add_tracker, add_user

JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 12), date(2027, 6, 20))  # "week" bucket


def stored(engine):
    with session_scope(engine) as s:
        return {
            (b.month, b.length_bucket): b
            for b in s.scalars(select(RouteBaseline).where(RouteBaseline.dest_airport == "LIS"))
        }


@pytest.fixture
def ctx(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    return ctx


def test_uses_cheapest_price_per_day_and_trailing_window(ctx):
    for price in (950, 900, 920):  # same trip, same day: only 900 counts
        add_observation(ctx.engine, *TRIP, price, observed=date(2027, 2, 20))
    add_observation(ctx.engine, *TRIP, 1000, observed=date(2027, 2, 25), verified=True)
    add_observation(ctx.engine, *TRIP, 50, observed=date(2026, 12, 1))  # older than 60 days: ignored
    baselines.run(ctx)
    b = stored(ctx.engine)[(JUNE, "week")]
    assert (b.median, b.n, b.confidence) == (950, 2, "low")


def test_blends_with_latest_google_typical_range(ctx):
    add_observation(
        ctx.engine, *TRIP, 700, observed=date(2027, 2, 1), verified=True, typical_low=100, typical_high=200
    )
    add_observation(
        ctx.engine, *TRIP, 700, observed=date(2027, 2, 20), verified=True, typical_low=600, typical_high=1000
    )
    baselines.run(ctx)
    b = stored(ctx.engine)[(JUNE, "week")]
    # n=2 -> weight 2/15 on own data (700), 13/15 on Google's midpoint (800)
    assert float(b.median) == pytest.approx(786.67, abs=0.01)
    assert (b.google_typical_low, b.google_typical_high) == (600, 1000)


def test_keys_without_data_are_skipped_and_rerun_updates_in_place(ctx):
    add_observation(ctx.engine, *TRIP, 800, observed=date(2027, 2, 20))
    counts = baselines.run(ctx)
    assert counts["confidence_low"] == 1 and counts["no_data"] >= 1
    add_observation(ctx.engine, *TRIP, 600, observed=date(2027, 2, 21))
    baselines.run(ctx)
    rows = stored(ctx.engine)
    assert len(rows) == 1
    assert rows[(JUNE, "week")].median == 700
    assert rows[(JUNE, "week")].computed_at.date() == RUN
