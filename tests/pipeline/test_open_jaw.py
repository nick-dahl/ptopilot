"""Open-jaw routes (fly into Porto, home from Santiago) through the pipeline."""

from datetime import date

from sqlalchemy import select

from ptopilot.db.models import Candidate, PriceObservation, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import broad_scan, expand, live_verify, runner, shortlist
from tests.pipeline.conftest import FakeLiveSource, FakeMonthSource, add_tracker, add_user, answering, option

MARCH = ((date(2027, 3, 1), date(2027, 3, 31)),)


def camino(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    uid = add_user(ctx.engine, home_airport="JFK", windows=MARCH, weather_tolerance="relaxed")
    add_tracker(ctx.engine, uid, code="CAMINO_PORTUGUES", min_stay=11, max_stay=14)
    return ctx


def route_queries(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(RouteQuery)))


def test_expand_creates_open_jaw_route_queries(make_ctx):
    ctx = camino(make_ctx)
    expand.run(ctx)
    rqs = route_queries(ctx.engine)
    assert rqs
    assert {(rq.origin, rq.dest_airport, rq.return_airport) for rq in rqs} == {("JFK", "OPO", "SCQ")}


def test_broad_scan_skips_open_jaw_routes(make_ctx):
    source = FakeMonthSource()
    ctx = camino(make_ctx, month_source=source)
    expand.run(ctx)
    assert broad_scan.run(ctx) == {}
    assert source.calls == []


def test_open_jaw_goes_only_to_capable_sources_without_tripping_the_breaker(make_ctx):
    google = FakeLiveSource("google_flights", answering(option(800)))
    serp = FakeLiveSource("serpapi", answering(option(959), source="serpapi"), supports_open_jaw=True)
    ctx = camino(make_ctx, live_sources=[google, serp])
    expand.run(ctx)
    shortlist.run(ctx)
    counts = live_verify.run(ctx)
    assert google.calls == []
    assert "google_flights_breaker_tripped" not in counts
    assert counts["serpapi_ok"] >= 1
    assert all(q.return_from == "SCQ" and q.open_jaw for q in serp.calls)
    with session_scope(ctx.engine) as s:
        assert {o.return_airport for o in s.scalars(select(PriceObservation))} == {"SCQ"}


def test_open_jaw_without_a_capable_source_is_counted_not_failed(make_ctx):
    google = FakeLiveSource("google_flights", answering(option(800)))
    ctx = camino(make_ctx, live_sources=[google])
    expand.run(ctx)
    shortlist.run(ctx)
    counts = live_verify.run(ctx)
    assert google.calls == []
    assert counts["no_open_jaw_source"] >= 1


def test_open_jaw_end_to_end_produces_candidates(make_ctx):
    serp = FakeLiveSource("serpapi", answering(option(959), source="serpapi"), supports_open_jaw=True)
    ctx = camino(make_ctx, live_sources=[serp])
    statuses = {r.stage: r.status for r in runner.run_pipeline(ctx)}
    assert statuses["score"] == "ok"
    with session_scope(ctx.engine) as s:
        rows = s.execute(select(Candidate, RouteQuery).join(RouteQuery)).all()
    assert rows
    assert all(rq.return_airport == "SCQ" and c.verified and c.price == 959 for c, rq in rows)
