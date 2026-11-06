from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import LiveCheck, PriceObservation, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, live_verify, shortlist
from ptopilot.pipeline.context import StageFailed, StageSkipped
from ptopilot.sources.base import SourceUnavailable
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    add_tracker,
    add_user,
    answering,
    failing,
    option,
)


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
    assert counts == {"checked_this_run": 6}
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


def test_live_verify_stores_layover_fields(make_ctx):
    opt = replace(option(700), longest_layover_min=420, longest_layover_airport="MAD")
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", answering(opt, option(650)))])
    live_verify.run(ctx)
    rows = verified(ctx.engine)
    assert {(r.longest_layover_min, r.longest_layover_airport) for r in rows} == {(420, "MAD"), (None, None)}


def listed(engine):
    with session_scope(engine) as s:
        return [
            (rq_id, reason)
            for rq_id, reason in s.execute(
                select(ShortlistEntry.route_query_id, ShortlistEntry.reason).order_by(ShortlistEntry.rank)
            )
        ]


def earlier_check(engine, rq_id, hour, source="google_flights", ok=True):
    with session_scope(engine) as s:
        s.add(
            LiveCheck(
                run_date=RUN,
                route_query_id=rq_id,
                source=source,
                ok=ok,
                options=1,
                checked_at=datetime(RUN.year, RUN.month, RUN.day, hour, tzinfo=UTC),
                purpose="trip",
            )
        )


def test_skips_only_what_this_run_checked(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    first = listed(ctx.engine)[0][0]
    with session_scope(ctx.engine) as s:
        s.query(ShortlistEntry).filter_by(route_query_id=first).update({"reason": "second"})
    earlier_check(ctx.engine, first, 6)  # an earlier run today; this run starts at noon
    counts = live_verify.run(ctx)
    assert len(src.calls) == 6 and counts["second_checks"] == 1 and counts["first_checks"] == 5
    again = live_verify.run(ctx)  # same run (same stage start): everything was checked in it
    assert again == {"checked_this_run": 6} and len(src.calls) == 6


def test_a_deal_or_explore_entry_fresh_by_now_is_skipped(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    first = listed(ctx.engine)[0][0]
    earlier_check(ctx.engine, first, 6, source="serpapi")  # any source
    counts = live_verify.run(ctx)
    assert counts["already_checked"] == 1 and counts["first_checks"] == 5 and len(src.calls) == 5


def test_an_audit_entry_is_checked_even_when_fresh(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    first = listed(ctx.engine)[0][0]
    with session_scope(ctx.engine) as s:
        s.query(ShortlistEntry).filter_by(route_query_id=first).update({"reason": "audit"})
    earlier_check(ctx.engine, first, 6, source="serpapi")
    counts = live_verify.run(ctx)
    assert counts["audits"] == 1 and len(src.calls) == 6 and "already_checked" not in counts


def long_shortlist(ctx, total=40):
    """Replace the shortlist with `total` explore entries (extra route queries are made up as needed)."""
    with session_scope(ctx.engine) as s:
        s.query(ShortlistEntry).delete()
        for n in range(total):
            rq = RouteQuery(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                depart_date=date(2027, 7, 1) + timedelta(days=n),
                return_date=date(2027, 7, 12) + timedelta(days=n),
            )
            s.add(rq)
            s.flush()
            s.add(ShortlistEntry(run_date=RUN, route_query_id=rq.id, rank=n, reason="explore"))
    return total


def test_backoff_slows_then_stops_when_google_refuses(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_DELAY_S", (10.0, 10.0))
    seen = []

    def respond(q):
        n = len(seen)
        seen.append(q)
        if n < 7:
            return answering(option(700))(q)  # 7 good, then 13 bad, then bad for good
        if n % 2:
            raise SourceUnavailable("429")
        return answering()(q)  # an empty answer is bad too

    pauses = []
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", respond)], sleep=pauses.append)
    total = long_shortlist(ctx)
    counts = live_verify.run(ctx)
    assert counts["backoff_slowed"] == 1
    assert pauses[:19] == [10.0] * 19 and set(pauses[19:]) == {10.0 * config.BACKOFF_PAUSE_FACTOR}
    assert len(seen) == 24  # 17 bad of the last 20 (0.85) stops the run
    assert counts["backoff_stopped"] == total - 24
    assert counts["first_checks"] == 24


def test_no_success_at_all_still_fails_the_stage(make_ctx):
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", failing("429"))])
    with pytest.raises(StageFailed, match="no live check succeeded for 3 shortlisted"):
        live_verify.run(ctx)  # the breaker trips after 3, the rest were never attempted
