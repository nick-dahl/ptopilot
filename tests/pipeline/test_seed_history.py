"""Stage `seed_history`: one SerpApi call per baseline key gives it ~60 days of Google's price history."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import LiveCheck, PriceObservation, RouteBaseline, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, expand, live_verify, seed_history, shortlist
from ptopilot.pipeline.context import StageSkipped
from ptopilot.pipeline.queries import cached_prices, rq_baseline_key, todays_route_queries
from ptopilot.sources.base import ExactResult, SourceUnavailable
from tests.pipeline.conftest import RUN, FakeLiveSource, add_tracker, add_user, answering, failing, option


def history(days=30, price=1000.0, end=RUN):
    return tuple((end - timedelta(days=i), price + (i % 5) * 10) for i in range(days))


def with_history(points):
    def respond(q):
        return ExactResult("serpapi", q, "USD", (option(990),), "https://serp.example/x", (900, 1100), points)

    return respond


def serpapi(respond):
    src = FakeLiveSource("serpapi", respond)
    src.provides_history = True
    return src


MAY_AND_JUNE = ((date(2027, 5, 1), date(2027, 5, 31)), (date(2027, 6, 1), date(2027, 6, 30)))


def expanded(make_ctx, **ctx_fields):
    """Lisbon and Madeira trackers over May and June: several baseline keys (route x month x length)."""
    ctx = make_ctx(**ctx_fields)
    user = add_user(ctx.engine, windows=MAY_AND_JUNE)
    add_tracker(ctx.engine, user)
    add_tracker(ctx.engine, user, code="MADEIRA")
    expand.run(ctx)
    return ctx


def keys(ctx):
    with session_scope(ctx.engine) as s:
        groups = defaultdict(list)
        for rq in todays_route_queries(s, ctx.run_date):
            groups[rq_baseline_key(rq)].append((rq.depart_date, rq.id))
        return {k: sorted(v) for k, v in groups.items()}


def history_rows(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(PriceObservation).where(PriceObservation.source == "google_history")))


def test_skipped_without_a_source_that_provides_history(make_ctx):
    ctx = expanded(make_ctx, live_sources=[FakeLiveSource("google_flights", answering(option(700)))])
    with pytest.raises(StageSkipped):
        seed_history.run(ctx)


def test_one_call_per_key_on_its_earliest_trip(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = expanded(make_ctx, live_sources=[src])
    wanted = keys(ctx)
    counts = seed_history.run(ctx)
    assert counts["keys_needing_seed"] == len(wanted) == counts["seeded"] == len(src.calls)
    assert {(q.depart_date) for q in src.calls} == {trips[0][0] for trips in wanted.values()}


def test_history_points_are_stored_unverified_on_their_own_dates(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 3, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history(days=5)))])
    counts = seed_history.run(ctx)  # 3 a day, 2 kept for open-jaw: one call
    assert counts["seeded"] == 1 and counts["points_stored"] == 5 and counts["options_stored"] == 1
    rows = history_rows(ctx.engine)
    assert sorted(r.observed_at for r in rows) == [
        datetime.combine(RUN - timedelta(days=i), time(12), UTC) for i in range(4, -1, -1)
    ]
    assert all(not r.verified and r.carrier is None and r.deep_link is None for r in rows)
    with session_scope(ctx.engine) as s:
        live = s.scalars(select(PriceObservation).where(PriceObservation.verified.is_(True))).all()
        checks = s.scalars(select(LiveCheck)).all()
    assert [r.price for r in live] == [990] and [(c.source, c.ok, c.options) for c in checks] == [
        ("serpapi", True, 1)
    ]


def test_points_outside_the_baseline_window_are_dropped(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 3, "per_month": 250})
    old = ((RUN - timedelta(days=config.BASELINE_WINDOW_DAYS + 1), 500.0),)
    future = ((RUN + timedelta(days=1), 500.0),)
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(old + history(days=3) + future))])
    assert seed_history.run(ctx)["points_stored"] == 3


def test_a_seeded_key_reaches_normal_confidence(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history(days=30)))])
    seed_history.run(ctx)
    baselines.run(ctx)
    with session_scope(ctx.engine) as s:
        confidences = {b.confidence for b in s.scalars(select(RouteBaseline))}
    assert confidences == {"normal"}


def test_seeding_keeps_two_calls_a_day_for_open_jaw(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 4, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = expanded(make_ctx, live_sources=[src])
    counts = seed_history.run(ctx)
    assert len(src.calls) == 2 and counts["budget_exhausted"] == counts["keys_needing_seed"] - 2


def add_confident_baseline(engine, key):
    origin, dest, ret, month, bucket = key
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin=origin, dest_airport=dest, return_airport=ret, month=month, length_bucket=bucket,
                median=1000, sigma=50, n=20, confidence="normal",
            )
        )  # fmt: skip


def add_history_point(engine, rq_id, days_ago=10):
    with session_scope(engine) as s:
        rq = s.get(RouteQuery, rq_id)
        s.add(
            PriceObservation(
                origin=rq.origin, dest_airport=rq.dest_airport, return_airport=rq.return_airport,
                depart_date=rq.depart_date, return_date=rq.return_date, month=rq.depart_date.replace(day=1),
                source="google_history", price=1000, currency="USD", verified=False,
                observed_at=datetime.combine(RUN - timedelta(days=days_ago), time(12), UTC),
            )
        )  # fmt: skip


def add_serpapi_check(engine, rq_id, days_ago):
    with session_scope(engine) as s:
        s.add(
            LiveCheck(
                run_date=RUN - timedelta(days=days_ago),
                route_query_id=rq_id,
                source="serpapi",
                ok=True,
                options=0,
            )
        )


def test_confident_seeded_and_recently_tried_keys_are_skipped(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = expanded(make_ctx, live_sources=[src])
    all_keys = list(keys(ctx).items())
    (confident, _), (_, seeded_trips), (_, tried_trips) = all_keys[:3]
    add_confident_baseline(ctx.engine, confident)
    add_history_point(ctx.engine, seeded_trips[-1][1])  # any trip of the key counts
    add_serpapi_check(ctx.engine, tried_trips[0][1], days_ago=5)
    counts = seed_history.run(ctx)
    assert counts["keys_needing_seed"] == len(all_keys) - 3 == len(src.calls)


def test_history_older_than_the_window_does_not_count_as_seeded(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history()))])
    all_keys = keys(ctx)
    for trips in all_keys.values():
        add_history_point(ctx.engine, trips[0][1], days_ago=config.BASELINE_WINDOW_DAYS + 1)
    assert seed_history.run(ctx)["keys_needing_seed"] == len(all_keys)


def test_a_key_tried_without_history_is_retried_after_30_days(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history()))])
    all_keys = keys(ctx)
    for trips in all_keys.values():
        add_serpapi_check(ctx.engine, trips[0][1], days_ago=config.SEED_RETRY_DAYS)
    assert seed_history.run(ctx)["keys_needing_seed"] == len(all_keys)


def test_open_jaw_and_far_routes_are_not_seeded(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = make_ctx(live_sources=[src])
    far = (date(2028, 3, 1), date(2028, 3, 31))  # well past the live horizon
    user = add_user(ctx.engine, home_airport="JFK", windows=((date(2027, 6, 1), date(2027, 6, 30)), far))
    add_tracker(ctx.engine, user, code="CAMINO_PORTUGUES", min_stay=11, max_stay=14)
    add_tracker(ctx.engine, user, code="LIS")
    expand.run(ctx)
    seed_history.run(ctx)
    assert src.calls and all(q.dest_airport == "LIS" and not q.open_jaw for q in src.calls)
    assert all((q.depart_date - RUN).days <= config.LIVE_HORIZON_DAYS for q in src.calls)


def test_a_same_day_rerun_makes_no_new_calls(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(()))  # no history: keys stay unseeded, but count as tried
    ctx = expanded(make_ctx, live_sources=[src])
    first = seed_history.run(ctx)
    calls = len(src.calls)
    assert first["no_history"] == calls > 0
    assert seed_history.run(ctx)["keys_needing_seed"] == 0 and len(src.calls) == calls


def test_three_failures_in_a_row_stop_the_stage(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(failing("HTTP 500"))
    counts = seed_history.run(expanded(make_ctx, live_sources=[src]))
    assert len(src.calls) == 3 and counts["serpapi_failed"] == 3 and counts["breaker_tripped"] == 1


def test_route_specific_failures_do_not_stop_the_stage(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})

    def route_failing(q):
        raise SourceUnavailable("serpapi: odd payload", route_specific=True)

    src = serpapi(route_failing)
    ctx = expanded(make_ctx, live_sources=[src])
    assert seed_history.run(ctx)["serpapi_failed"] == len(src.calls) == len(keys(ctx))


def test_history_never_becomes_a_cached_price(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history()))])
    seed_history.run(ctx)
    with session_scope(ctx.engine) as s:
        exact, monthly = cached_prices(s, todays_route_queries(s, RUN), RUN)
    assert exact == {} and monthly == {}


def test_live_verify_fallbacks_keep_history_too(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    google = FakeLiveSource("google_flights", failing("429"))
    ctx = expanded(make_ctx, live_sources=[google, serpapi(with_history(history(days=4)))])
    shortlist.run(ctx)
    counts = live_verify.run(ctx)
    assert counts["serpapi_ok"] > 0 and len(history_rows(ctx.engine)) == 4 * counts["serpapi_ok"]
