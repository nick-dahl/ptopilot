from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import (
    LiveCheck,
    PriceObservation,
    RouteQuery,
    ShortlistEntry,
    SourceBudget,
    TrackerRouteLink,
)
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
    assert counts["already_fresh"] == 1 and counts["first_checks"] == 5 and len(src.calls) == 5


def test_an_audit_entry_is_checked_even_when_fresh(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    first = listed(ctx.engine)[0][0]
    with session_scope(ctx.engine) as s:
        s.query(ShortlistEntry).filter_by(route_query_id=first).update({"reason": "audit"})
    earlier_check(ctx.engine, first, 6, source="serpapi")
    counts = live_verify.run(ctx)
    assert counts["audits"] == 1 and len(src.calls) == 6 and "already_fresh" not in counts


def long_shortlist(ctx, total=40, priced_days_ago=None):
    """Replace the shortlist with `total` explore entries (extra route queries are made up as needed),
    each with a priced Google check `priced_days_ago` (none when None)."""
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
            if priced_days_ago is not None:
                day = RUN - timedelta(days=priced_days_ago)
                s.add(
                    LiveCheck(
                        run_date=day,
                        route_query_id=rq.id,
                        source="google_flights",
                        ok=True,
                        options=3,
                        checked_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
                    )
                )
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
    total = long_shortlist(ctx, priced_days_ago=1)  # empty answers on trips Google priced yesterday
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


# --- final review: known-unpriceable trips, back-off on empties ---------------------------------------------


def linked_trip(engine, tracker_id, n) -> int:
    """A round trip linked to the tracker today, departing n days after 2027-07-01."""
    with session_scope(engine) as s:
        rq = RouteQuery(
            origin="ORD",
            dest_airport="LIS",
            return_airport="LIS",
            depart_date=date(2027, 7, 1) + timedelta(days=n),
            return_date=date(2027, 7, 9) + timedelta(days=n),
        )
        s.add(rq)
        s.flush()
        s.add(
            TrackerRouteLink(
                tracker_id=tracker_id,
                route_query_id=rq.id,
                run_date=RUN,
                pto_cost=3,
                days_away=9,
                efficiency=1.0,
                month=7,
                season_rating="good",
            )
        )
        return rq.id


def past_check(engine, rq_id, days_ago, ok=True, route_specific=False, options=1):
    day = RUN - timedelta(days=days_ago)
    with session_scope(engine) as s:
        s.add(
            LiveCheck(
                run_date=day,
                route_query_id=rq_id,
                source="google_flights",
                ok=ok,
                options=options if ok else 0,
                route_specific=route_specific,
                checked_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
                purpose="trip",
            )
        )


def test_known_unpriceable_trips_neither_lead_nor_switch_google_off(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine))
    unpriceable = [linked_trip(ctx.engine, tid, n) for n in range(10)]
    normal = [linked_trip(ctx.engine, tid, 20 + n) for n in range(5)]
    for rq_id in unpriceable:
        past_check(ctx.engine, rq_id, 1, ok=False, route_specific=True)  # never priced, failed yesterday
    for rq_id in normal:
        past_check(ctx.engine, rq_id, 2)
    bad_departures = {date(2027, 7, 1) + timedelta(days=n) for n in range(10)}

    def respond(q):
        if q.depart_date in bad_departures:
            raise SourceUnavailable("unreadable page", route_specific=True)
        return answering(option(700))(q)

    src = FakeLiveSource("google_flights", respond)
    ctx.live_sources = [src]
    shortlist.run(ctx)
    order = [rq_id for rq_id, _ in listed(ctx.engine)]
    assert order[:5] == normal and set(order[5:]) == set(unpriceable)  # kept, retried, just not first
    counts = live_verify.run(ctx)  # does not raise: the stage did not fail
    assert counts["google_flights_ok"] == 5
    assert "google_flights_route_breaker_tripped" not in counts
    assert len(src.calls) == 15  # Google stayed on for every trip


def test_known_unpriceable_failures_never_trip_the_route_breaker_or_back_off(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine))
    unpriceable = [linked_trip(ctx.engine, tid, n) for n in range(25)]
    normal = [linked_trip(ctx.engine, tid, 40 + n) for n in range(3)]
    for rq_id in unpriceable:
        past_check(ctx.engine, rq_id, 1, ok=False, route_specific=True)
    with session_scope(ctx.engine) as s:  # ranked first anyway: live_verify must cope on its own
        for rank, rq_id in enumerate(unpriceable + normal):
            s.add(ShortlistEntry(run_date=RUN, route_query_id=rq_id, rank=rank, reason="explore"))
    bad = {date(2027, 7, 1) + timedelta(days=n) for n in range(25)}

    def respond(q):
        if q.depart_date in bad:
            raise SourceUnavailable("unreadable page", route_specific=True)
        return answering(option(700))(q)

    src = FakeLiveSource("google_flights", respond)
    ctx.live_sources = [src]
    counts = live_verify.run(ctx)
    assert counts["google_flights_ok"] == 3 and len(src.calls) == 28
    assert not {"google_flights_route_breaker_tripped", "backoff_slowed", "backoff_stopped"} & set(counts)


def test_empty_answers_on_never_priced_trips_are_not_pushback(make_ctx):
    src = FakeLiveSource("google_flights", answering())
    ctx = shortlisted(make_ctx, live_sources=[src])
    long_shortlist(ctx, total=30)  # far out, never priced: habitually empty
    counts = live_verify.run(ctx)
    assert len(src.calls) == 30 and counts["no_flights"] == 30
    assert not {"backoff_slowed", "backoff_stopped"} & set(counts)


def test_empty_answers_on_recently_priced_trips_stop_the_run(make_ctx):
    src = FakeLiveSource("google_flights", answering())
    ctx = shortlisted(make_ctx, live_sources=[src])
    long_shortlist(ctx, total=30, priced_days_ago=1)
    counts = live_verify.run(ctx)
    assert len(src.calls) == 20 and counts["backoff_stopped"] == 10


def test_a_priced_answer_older_than_the_lookback_does_not_make_empties_bad(make_ctx):
    src = FakeLiveSource("google_flights", answering())
    ctx = shortlisted(make_ctx, live_sources=[src])
    long_shortlist(ctx, total=30, priced_days_ago=8)
    counts = live_verify.run(ctx)
    assert len(src.calls) == 30 and "backoff_stopped" not in counts
