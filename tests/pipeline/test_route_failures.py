"""A route Google can't parse is that route's problem: it must not switch Google off for everyone else."""

import pytest

from ptopilot.pipeline import expand, live_verify, shortlist
from ptopilot.pipeline.context import StageFailed
from ptopilot.sources.base import SourceUnavailable
from tests.pipeline.conftest import FakeLiveSource, add_tracker, add_user, answering, option


def shortlisted(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)  # no history -> 6 exploration entries
    return ctx


def route_failing(query):
    raise SourceUnavailable("google_flights: TypeError: 'NoneType' object", route_specific=True)


def test_route_specific_failures_never_trip_the_breaker(make_ctx):
    google = FakeLiveSource("google_flights", route_failing)
    ctx = shortlisted(make_ctx, live_sources=[google])
    with pytest.raises(StageFailed):  # nothing priced at all is still a failed stage
        live_verify.run(ctx)
    assert len(google.calls) == 6  # but every route was tried: the breaker never tripped


def test_route_specific_failures_are_counted_separately(make_ctx):
    google = FakeLiveSource("google_flights", route_failing)
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    counts = live_verify.run(shortlisted(make_ctx, live_sources=[google, fallback]))
    assert counts["google_flights_route_failed"] == 6
    assert "google_flights_failed" not in counts and "google_flights_breaker_tripped" not in counts
    assert counts["serpapi_ok"] == 6  # the fallback still prices each route


def test_route_failures_neither_count_toward_nor_reset_the_breaker(make_ctx):
    outcomes = iter(["outage", "route", "outage", "outage", "ok", "ok"])

    def flaky(query):
        kind = next(outcomes)
        if kind == "outage":
            raise SourceUnavailable("google_flights: HTTP 429")
        if kind == "route":
            raise SourceUnavailable("google_flights: IndexError", route_specific=True)
        return answering(option(700))(query)

    google = FakeLiveSource("google_flights", flaky)
    with pytest.raises(StageFailed, match="'google_flights_breaker_tripped': 1"):
        live_verify.run(shortlisted(make_ctx, live_sources=[google]))
    # outage, route (ignored), outage, outage -> three outages in a row trip the breaker on call 4
    assert len(google.calls) == 4
