"""Real API responses recorded 2026-10-16, checked for secrets before saving. Guards against provider format drift."""

import json
from datetime import date, datetime
from pathlib import Path

from ptopilot.sources.base import ExactQuery
from ptopilot.sources.serpapi import parse_google_flights
from ptopilot.sources.travelpayouts import parse_prices_for_dates

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_real_travelpayouts_city_pair_response():
    quotes = parse_prices_for_dates(load("real_travelpayouts_NYC_LON_2026-12.json"), "NYC", "LON")
    assert len(quotes) == 10
    first = quotes[0]
    assert (first.origin, first.dest_airport) == ("EWR", "LHR")  # city query returns real airports
    assert (first.depart_date, first.return_date) == (date(2026, 12, 1), date(2026, 12, 9))
    assert (first.price, first.currency, first.flight_number, first.stops) == (562.0, "USD", "SK 910", 1)
    assert first.deep_link.startswith("https://www.aviasales.com/search/")
    assert all(q.currency == "USD" and q.return_date for q in quotes)


def test_real_serpapi_round_trip_response():
    query = ExactQuery("ORD", "LIS", date(2027, 6, 12), date(2027, 6, 20))
    result = parse_google_flights(load("real_serpapi_ORD_LIS_2027-06-12_2027-06-20.json"), query)
    assert len(result.options) == 11
    assert result.typical_range == (1100.0, 1400.0)
    assert result.deep_link.startswith("https://www.google.com/travel/flights")
    best = result.cheapest()
    assert (best.price, best.carrier, best.stops, best.duration_min) == (1098.0, "Tap Air Portugal", 0, 490)
    assert best.flight_numbers == ("TP 244",)
    assert best.outbound_departure == datetime(2027, 6, 12, 17, 45)
