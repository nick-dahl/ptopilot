"""Real Google Flights results scripts recorded 2026-10-18 (fast-flights 3.1).

PHL->PUQ: Google returned no itineraries at all, which fast-flights' parser crashes on
(TypeError: 'NoneType' object is not subscriptable). JFK->PUQ, same dates, has flights.
"""

from datetime import date
from pathlib import Path

import pytest

from ptopilot.sources.base import ExactQuery, SourceUnavailable
from ptopilot.sources.google_flights import GoogleFlightsSource, flights_from_script, parse_flights

FIXTURES = Path(__file__).parent / "fixtures"
EMPTY = (FIXTURES / "real_google_page_PHL_PUQ_2027-03-05_2027-03-14.js").read_text(encoding="utf-8")
FULL = (FIXTURES / "real_google_page_JFK_PUQ_2027-03-05_2027-03-14.js").read_text(encoding="utf-8")
QUERY = ExactQuery("PHL", "PUQ", date(2027, 3, 5), date(2027, 3, 14))


def test_a_page_with_no_itineraries_means_no_flights():
    assert flights_from_script(EMPTY) == []


def test_a_page_with_itineraries_still_parses():
    options = parse_flights(flights_from_script(FULL))
    assert options and all(o.price > 0 for o in options)


def raising(exc):
    def search(query):
        raise exc

    return search


@pytest.mark.parametrize("exc", [TypeError("'NoneType' object"), IndexError("x"), KeyError("k")])
def test_parse_errors_are_route_specific(exc):
    with pytest.raises(SourceUnavailable) as info:
        GoogleFlightsSource(search=raising(exc)).exact_search(QUERY)
    assert info.value.route_specific is True


@pytest.mark.parametrize("exc", [TimeoutError("timeout"), ConnectionError("reset"), RuntimeError("blocked")])
def test_outages_are_not_route_specific(exc):
    with pytest.raises(SourceUnavailable) as info:
        GoogleFlightsSource(search=raising(exc)).exact_search(QUERY)
    assert info.value.route_specific is False


def test_source_unavailable_defaults_to_an_outage():
    assert SourceUnavailable("serpapi: HTTP 500").route_specific is False
