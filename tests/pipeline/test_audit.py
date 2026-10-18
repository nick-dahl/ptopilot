"""The health email compares fast-flights with SerpApi on trips both priced the same day."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline.health import audit_lines, build_report
from ptopilot.pipeline.runner import StageResult
from tests.pipeline.conftest import RUN

TRIP = ("JFK", "PDL", date(2027, 3, 5), date(2027, 3, 14))
OTHER = ("JFK", "FNC", date(2027, 3, 12), date(2027, 3, 21))
THIRD = ("EWR", "PDL", date(2027, 3, 5), date(2027, 3, 15))


def priced(engine, trip, source, *prices, day=RUN):
    origin, dest, depart, ret = trip
    with session_scope(engine) as s:
        for price in prices:
            s.add(
                PriceObservation(
                    origin=origin, dest_airport=dest, return_airport=dest,
                    depart_date=depart, return_date=ret,
                    month=depart.replace(day=1), source=source, price=Decimal(price), currency="USD",
                    verified=True, observed_at=datetime.combine(day, time(9), UTC),
                )
            )  # fmt: skip


def lines(engine, day=RUN):
    with session_scope(engine) as s:
        return audit_lines(s, day)


def test_no_pairs_says_so(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 700)  # only one source priced it
    assert lines(clean_engine) == [
        "Audit (fast-flights vs SerpApi, today): no trips priced by both sources",
        "Audit, last 30 days: no trips priced by both sources",
    ]


def test_counts_cheaper_equal_and_pricier_using_each_sources_cheapest_option(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 760, 740)  # cheapest 740
    priced(clean_engine, TRIP, "serpapi", 603, 650)  # cheapest 603 -> fast-flights pricier by 137
    priced(clean_engine, OTHER, "google_flights", 828)
    priced(clean_engine, OTHER, "serpapi", 825)  # within $5 -> equal
    priced(clean_engine, THIRD, "google_flights", 600)
    priced(clean_engine, THIRD, "serpapi", 650)  # fast-flights cheaper
    today, month = lines(clean_engine)[:2]
    assert today == "Audit (fast-flights vs SerpApi, today): 3 trips, cheaper 1, equal 1, pricier 1"
    assert month == "  median gap +$3 (+0%), worst +$137 (+23%): JFK→PDL Mar 5–14 ($740 vs $603)"


def test_the_30_day_line_pools_earlier_days_and_ignores_older_ones(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 740, day=RUN - timedelta(days=3))
    priced(clean_engine, TRIP, "serpapi", 603, day=RUN - timedelta(days=3))
    priced(clean_engine, OTHER, "google_flights", 900, day=RUN - timedelta(days=30))  # outside the 30 days
    priced(clean_engine, OTHER, "serpapi", 800, day=RUN - timedelta(days=30))
    priced(clean_engine, TRIP, "google_flights", 700)
    priced(clean_engine, TRIP, "serpapi", 700)
    out = lines(clean_engine)
    assert out[0] == "Audit (fast-flights vs SerpApi, today): 1 trips, cheaper 0, equal 1, pricier 0"
    assert out[-1] == "Audit, last 30 days: 2 trips, cheaper 0, equal 1, pricier 1; median gap +$68 (+11%)"


def test_prices_on_different_days_are_not_paired(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 740, day=RUN - timedelta(days=1))
    priced(clean_engine, TRIP, "serpapi", 603)
    assert lines(clean_engine)[-1] == "Audit, last 30 days: no trips priced by both sources"


def test_the_health_report_includes_the_audit(make_ctx):
    ctx = make_ctx()
    priced(ctx.engine, TRIP, "google_flights", 740)
    priced(ctx.engine, TRIP, "serpapi", 603)
    _, text = build_report(ctx, [StageResult("live_verify", "ok", {"google_flights_ok": 1})])
    assert "Audit (fast-flights vs SerpApi, today): 1 trips, cheaper 0, equal 0, pricier 1" in text
