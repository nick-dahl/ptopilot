"""SerpApi round-trip results carry Google's own daily price history for the searched dates."""

import json
from datetime import date
from pathlib import Path

from ptopilot.sources.base import ExactQuery
from ptopilot.sources.serpapi import parse_google_flights, parse_price_history

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


REAL = load("real_serpapi_ORD_LIS_2027-06-12_2027-06-20.json")
MULTI = load("real_serpapi_multicity_JFK-OPO_SCQ-JFK_2027-03.json")
QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 12), date(2027, 6, 20))


def test_real_response_carries_61_days_of_history():
    history = parse_google_flights(REAL, QUERY).price_history
    assert len(history) == 61
    assert [d for d, _ in history] == sorted(d for d, _ in history)
    assert history[-1] == (date(2026, 10, 16), 1098.0)


def test_history_points_are_utc_dates():
    assert parse_price_history({"price_history": [[1792126800, 1098]]}) == ((date(2026, 10, 16), 1098.0),)


def test_malformed_points_are_skipped():
    insights = {"price_history": [[1792126800, 1098], ["x", 5], [1792126800], None, [1792213200, "n/a"]]}
    assert parse_price_history(insights) == ((date(2026, 10, 16), 1098.0),)


def test_missing_history_is_empty():
    assert parse_price_history(None) == ()
    assert parse_price_history({}) == ()
    assert parse_price_history({"price_history": "nope"}) == ()


def test_multi_city_results_have_no_history():
    query = ExactQuery("JFK", "OPO", date(2027, 3, 5), date(2027, 3, 19), return_from="SCQ")
    assert parse_google_flights(MULTI, query).price_history == ()
