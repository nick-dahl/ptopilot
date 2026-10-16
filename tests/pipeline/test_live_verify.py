from datetime import date

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import PriceObservation, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, live_verify, shortlist
from ptopilot.pipeline.context import StageFailed, StageSkipped
from tests.pipeline.conftest import RUN, FakeLiveSource, add_tracker, add_user, answering, failing, option


def verified(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(PriceObservation).where(PriceObservation.verified.is_(True))))


def budget_used(engine, source):
    with session_scope(engine) as s:
        return s.scalar(select(SourceBudget.calls_used).filter_by(source=source, period=date(2027, 3, 1)))


def shortlisted(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)  # no history -> 6 exploration entries
    return ctx


def test_skipped_without_live_sources(make_ctx):
    with pytest.raises(StageSkipped):
        live_verify.run(make_ctx())


def test_stores_every_option_as_verified_with_typical_range(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700), option(650, stops=0), typical=(600, 900)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    counts = live_verify.run(ctx)
    assert counts["google_flights_ok"] == 6 and counts["options_stored"] == 12
    rows = verified(ctx.engine)
    assert len(rows) == 12
    assert {(r.typical_low, r.typical_high) for r in rows} == {(600, 900)}
    assert all(r.observed_at.date() == RUN and r.deep_link for r in rows)


def test_breaker_trips_after_three_failures_and_fallback_takes_over(make_ctx):
    primary = FakeLiveSource("google_flights", failing("429"))
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[primary, fallback])
    counts = live_verify.run(ctx)
    assert len(primary.calls) == 3
    assert counts["google_flights_breaker_tripped"] == 1
    assert counts["serpapi_ok"] == 6


def test_fallback_budget_caps_calls_per_run_and_is_persisted(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 2, "per_month": 250})
    primary = FakeLiveSource("google_flights", failing())
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[primary, fallback])
    counts = live_verify.run(ctx)
    assert len(fallback.calls) == 2
    assert counts["serpapi_budget_exhausted"] == 1
    assert counts["unchecked"] > 0
    assert budget_used(ctx.engine, "serpapi") == 2


def test_monthly_budget_already_spent_blocks_the_source(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 8, "per_month": 250})
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[fallback])
    with session_scope(ctx.engine) as s:
        s.add(SourceBudget(source="serpapi", period=date(2027, 3, 1), calls_used=250))
    with pytest.raises(StageFailed):
        live_verify.run(ctx)
    assert fallback.calls == []


def test_every_source_failing_fails_the_stage(make_ctx):
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", failing())])
    with pytest.raises(StageFailed, match="no live check succeeded"):
        live_verify.run(ctx)


def test_no_flights_counts_as_a_successful_check(make_ctx):
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", answering())])
    counts = live_verify.run(ctx)
    assert (counts["google_flights_ok"], counts["no_flights"], counts["options_stored"]) == (6, 6, 0)


def test_rerun_skips_routes_already_checked_today(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    live_verify.run(ctx)
    counts = live_verify.run(ctx)
    assert counts == {"already_checked": 6}
    assert len(src.calls) == 6


def test_pauses_between_checks(make_ctx):
    pauses = []
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src], sleep=pauses.append)
    live_verify.run(ctx)
    assert len(pauses) == 5
    assert all(config.LIVE_DELAY_S[0] <= p <= config.LIVE_DELAY_S[1] for p in pauses)


def test_rerun_does_not_recheck_routes_that_had_no_flights(make_ctx):
    src = FakeLiveSource("google_flights", answering())
    ctx = shortlisted(make_ctx, live_sources=[src])
    live_verify.run(ctx)
    live_verify.run(ctx)
    assert len(src.calls) == 6


def test_daily_budget_holds_across_reruns(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 2, "per_month": 250})
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", failing()), fallback])
    live_verify.run(ctx)
    with pytest.raises(StageFailed):
        live_verify.run(ctx)  # retry the same day: the remaining routes find no budget left
    assert len(fallback.calls) == 2
    assert budget_used(ctx.engine, "serpapi") == 2
