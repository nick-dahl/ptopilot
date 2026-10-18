"""Fixes from the Plan 8 whole-branch review: the audit gets real pairs, a seeded trip can't fake deals,
a Google-wide format change stops after a few routes, and live_verify stays inside the job's time."""

from datetime import date, timedelta
from itertools import count

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import RouteBaseline, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, expand, live_verify, seed_history, shortlist
from ptopilot.pipeline.health import audit_lines
from ptopilot.sources.base import ExactResult, SourceUnavailable
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    add_observation,
    add_tracker,
    add_user,
    answering,
    option,
)


def seeding_serpapi():
    def respond(q):
        points = tuple((RUN - timedelta(days=i), 1000.0) for i in range(30))
        return ExactResult("serpapi", q, "USD", (option(990),), "https://serp.example/x", None, points)

    src = FakeLiveSource("serpapi", respond)
    src.provides_history = True
    return src


def shortlisted(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)
    return ctx


def test_google_still_prices_seeded_trips_so_the_audit_gets_real_pairs(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    google = FakeLiveSource("google_flights", answering(option(1010)))
    ctx = shortlisted(make_ctx, live_sources=[google, seeding_serpapi()])
    seeded = seed_history.run(ctx)["seeded"]
    live_verify.run(ctx)
    with session_scope(ctx.engine) as s:
        today = audit_lines(s, RUN)[0]
    assert seeded > 0 and today.startswith(f"Audit (fast-flights vs SerpApi, today): {seeded} trips")


def test_a_baseline_dominated_by_one_trip_gets_a_wider_spread(make_ctx):
    """60 days of one trip's flat price must not make a normal price on another trip look like a deal."""
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    with session_scope(ctx.engine) as s:
        trips = sorted((rq.depart_date, rq.return_date) for rq in s.scalars(select(RouteQuery)))
    week = [t for t in trips if 7 <= (t[1] - t[0]).days + 1 <= 10]
    seeded_trip, other_trip = week[0], week[-1]
    for i in range(60):  # one trip's history: flat around $1000
        add_observation(ctx.engine, *seeded_trip, 1000 + (i % 3) * 5, observed=RUN - timedelta(days=i))
    add_observation(ctx.engine, *other_trip, 960, observed=RUN)
    baselines.run(ctx)
    with session_scope(ctx.engine) as s:
        b = s.scalars(select(RouteBaseline).where(RouteBaseline.length_bucket == "week")).one()
    assert float(b.sigma) >= config.SINGLE_TRIP_SIGMA_FLOOR_FRACTION * float(b.median) - 0.01
    assert (960 - float(b.median)) / float(b.sigma) > config.GOOD_DEAL_Z  # $960 vs ~$1000 is not a deal


def test_a_baseline_from_many_trips_keeps_the_normal_floor(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    with session_scope(ctx.engine) as s:
        trips = sorted((rq.depart_date, rq.return_date) for rq in s.scalars(select(RouteQuery)))
    week = [t for t in trips if 7 <= (t[1] - t[0]).days + 1 <= 10]
    for i in range(20):
        add_observation(ctx.engine, *week[i % len(week)], 1000, observed=RUN - timedelta(days=i))
    baselines.run(ctx)
    with session_scope(ctx.engine) as s:
        b = s.scalars(select(RouteBaseline).where(RouteBaseline.length_bucket == "week")).one()
    assert len(week) >= 3 and float(b.sigma) == config.SIGMA_FLOOR_FRACTION * float(b.median)


def test_many_route_specific_failures_with_no_success_disable_the_source(make_ctx):
    def format_changed(q):
        raise SourceUnavailable("google_flights: KeyError: 3", route_specific=True)

    google = FakeLiveSource("google_flights", format_changed)
    ctx = make_ctx(live_sources=[google])
    user = add_user(ctx.engine, windows=((date(2027, 5, 1), date(2027, 6, 30)),))
    add_tracker(ctx.engine, user)
    add_tracker(ctx.engine, user, code="MADEIRA")
    expand.run(ctx)
    shortlist.run(ctx)
    try:
        live_verify.run(ctx)
    except Exception:
        pass  # nothing priced: the stage fails, which is right
    assert len(google.calls) == config.ROUTE_FAILURE_LIMIT


def test_live_verify_stops_starting_checks_when_its_time_is_up(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_VERIFY_BUDGET_S", 100)
    ticks = count(0, 40)  # every clock read is 40 s later
    google = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[google], clock=lambda: next(ticks))
    counts = live_verify.run(ctx)
    assert 0 < len(google.calls) < 6 and counts["out_of_time"] == 6 - len(google.calls)
