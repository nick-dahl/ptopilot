"""Fixture is a real fast-flights 3.1.0 response recorded 2026-10-16 for ORD<->LIS, Jun 11-20 2027."""

import json
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ptopilot.sources.base import ExactQuery, SourceUnavailable
from ptopilot.sources.google_flights import GoogleFlightsSource, parse_flights

FIXTURE_TEXT = (
    Path(__file__).parent / "fixtures" / "google_flights_ORD_LIS_2027-06-11_2027-06-20.json"
).read_text()
QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))


def recorded():
    """Rebuild attribute-style objects like fast-flights returns."""
    return json.loads(FIXTURE_TEXT, object_hook=lambda d: SimpleNamespace(**d))


def test_parse_real_response():
    options = parse_flights(recorded())
    assert len(options) == 7
    first = options[0]
    assert first.price == 1340.0
    assert first.carrier == "SWISS"
    assert first.stops == 1
    # 530 + 175 flying, plus ZRH layover 06:10 -> 12:50 = 400
    assert first.duration_min == 1105
    assert first.outbound_departure == datetime(2027, 6, 11, 14, 20)
    assert first.overnight_layover is False
    assert first.flight_numbers == ()


def test_multi_airline_carrier_is_joined():
    third = parse_flights(recorded())[2]
    assert third.carrier == "American, British Airways"
    assert third.duration_min == 470 + 180 + 130


def test_overnight_layover_detected_when_connection_is_next_day():
    r = recorded()[0]
    r.flights[1].departure.date = [2027, 6, 13]
    assert parse_flights([r])[0].overnight_layover is True


def test_exact_search_wraps_results_and_link():
    src = GoogleFlightsSource(
        search=lambda q: (recorded(), "https://www.google.com/travel/flights/search?tfs=X")
    )
    result = src.exact_search(QUERY)
    assert result.source == "google_flights"
    assert result.cheapest().price == 1340.0
    assert result.deep_link.endswith("tfs=X")
    assert result.typical_range is None


def test_no_flights_is_an_empty_result_not_an_error():
    result = GoogleFlightsSource(search=lambda q: ([], "u")).exact_search(QUERY)
    assert result.options == ()
    assert result.cheapest() is None


def test_any_library_failure_becomes_source_unavailable():
    def blocked(q):
        raise RuntimeError("429 Too Many Requests")

    with pytest.raises(SourceUnavailable, match="429"):
        GoogleFlightsSource(search=blocked).exact_search(QUERY)


@pytest.mark.live
def test_live_google_flights_smoke():
    result = GoogleFlightsSource().exact_search(
        ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))
    )
    assert result.options and result.cheapest().price > 0


def test_hung_search_times_out_as_source_unavailable():
    def hang(q):
        time.sleep(5)
        return [], "u"

    start = time.monotonic()
    with pytest.raises(SourceUnavailable, match="timed out"):
        GoogleFlightsSource(search=hang, timeout_s=0.2).exact_search(QUERY)
    assert time.monotonic() - start < 2
