"""Fixture follows SerpApi's documented google_flights shape; swap for a real recording once a key exists."""

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from ptopilot.sources.base import ExactQuery, SourceUnavailable
from ptopilot.sources.serpapi import SerpApiSource, parse_google_flights

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "serpapi_ORD_LIS_2027-06-11_2027-06-20.json").read_text(
        encoding="utf-8"
    )
)
QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))


def source_returning(status=200, body=None, text=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body)

    return SerpApiSource("key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_best_and_other_flights():
    result = parse_google_flights(FIXTURE, QUERY)
    assert len(result.options) == 2
    best = result.options[0]
    assert (best.price, best.carrier, best.stops, best.duration_min) == (
        905.0,
        "United, TAP Air Portugal",
        1,
        630,
    )
    assert best.flight_numbers == ("UA 1234", "TP 202")
    assert best.outbound_departure == datetime(2027, 6, 11, 18, 15)
    assert best.overnight_layover is False


def test_overnight_flag_and_cheapest():
    result = parse_google_flights(FIXTURE, QUERY)
    assert result.options[1].overnight_layover is True
    assert result.cheapest().price == 840.0


def test_typical_range_and_link():
    result = parse_google_flights(FIXTURE, QUERY)
    assert result.typical_range == (780.0, 1150.0)
    assert result.deep_link.startswith("https://www.google.com/travel/flights")
    assert result.source == "serpapi"


def test_missing_price_insights_means_no_range():
    payload = {k: v for k, v in FIXTURE.items() if k != "price_insights"}
    assert parse_google_flights(payload, QUERY).typical_range is None


def test_request_params():
    seen = []
    source_returning(body=FIXTURE, seen=seen).exact_search(QUERY)
    params = dict(seen[0].url.params)
    assert params["engine"] == "google_flights"
    assert (params["departure_id"], params["arrival_id"]) == ("ORD", "LIS")
    assert (params["outbound_date"], params["return_date"], params["type"]) == (
        "2027-06-11",
        "2027-06-20",
        "1",
    )
    assert params["api_key"] == "key"


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"status": 401, "text": "Invalid API key"}, "HTTP 401"),
        ({"status": 200, "body": {"error": "Your account has run out of searches."}}, "run out of searches"),
        ({"status": 200, "text": "not json"}, "invalid JSON"),
    ],
)
def test_failures_raise_source_unavailable(kwargs, match):
    with pytest.raises(SourceUnavailable, match=match):
        source_returning(**kwargs).exact_search(QUERY)


def test_empty_key_is_rejected():
    with pytest.raises(ValueError, match="SERPAPI_KEY"):
        SerpApiSource("")


def test_no_results_is_an_empty_result_not_an_outage():
    body = {"error": "Google Flights hasn't returned any results for this query."}
    result = source_returning(body=body).exact_search(QUERY)
    assert result.options == ()
    assert result.cheapest() is None


@pytest.mark.parametrize("body", [[1], "oops"])
def test_non_object_json_is_source_unavailable(body):
    with pytest.raises(SourceUnavailable, match="unexpected"):
        source_returning(body=body).exact_search(QUERY)


OPEN_JAW = ExactQuery("JFK", "OPO", date(2027, 3, 6), date(2027, 3, 21), return_from="SCQ")


def test_open_jaw_is_sent_as_a_multi_city_search():
    seen = []
    source_returning(body=FIXTURE, seen=seen).exact_search(OPEN_JAW)
    params = dict(seen[0].url.params)
    assert params["type"] == "3"
    assert json.loads(params["multi_city_json"]) == [
        {"departure_id": "JFK", "arrival_id": "OPO", "date": "2027-03-06"},
        {"departure_id": "SCQ", "arrival_id": "JFK", "date": "2027-03-21"},
    ]
    assert "outbound_date" not in params and "departure_id" not in params


def test_declares_open_jaw_support():
    assert SerpApiSource.supports_open_jaw is True


def test_serpapi_records_the_longest_layover():
    item = json.loads(json.dumps(FIXTURE["best_flights"][0]))
    item["layovers"] = [
        {"duration": 90, "name": "Newark", "id": "EWR"},
        {"duration": 450, "name": "Madrid", "id": "MAD"},
    ]
    result = parse_google_flights({"best_flights": [item]}, QUERY)
    assert result.options[0].longest_layover_min == 450
    assert result.options[0].longest_layover_airport == "MAD"
    first = parse_google_flights(FIXTURE, QUERY).options[0]
    assert (first.longest_layover_min, first.longest_layover_airport) == (90, "EWR")


def test_sources_tolerate_missing_layover_fields():
    nonstop = json.loads(json.dumps(FIXTURE["best_flights"][0]))
    nonstop["flights"] = nonstop["flights"][:1]
    nonstop.pop("layovers")
    option = parse_google_flights({"best_flights": [nonstop]}, QUERY).options[0]
    assert (option.longest_layover_min, option.longest_layover_airport) == (None, None)

    no_layovers = json.loads(json.dumps(FIXTURE["best_flights"][0]))
    no_layovers.pop("layovers")  # EWR 21:30 -> 23:00
    option = parse_google_flights({"best_flights": [no_layovers]}, QUERY).options[0]
    assert (option.longest_layover_min, option.longest_layover_airport) == (90, "EWR")

    malformed = json.loads(json.dumps(FIXTURE["best_flights"][0]))
    malformed.pop("layovers")
    malformed["flights"][1]["departure_airport"]["time"] = "soon"
    option = parse_google_flights({"best_flights": [malformed]}, QUERY).options[0]
    assert (option.longest_layover_min, option.longest_layover_airport) == (None, None)

    junk = json.loads(json.dumps(FIXTURE["best_flights"][0]))
    junk["layovers"] = [{"duration": "long", "id": "EWR"}, "x", {"id": "EWR"}]
    option = parse_google_flights({"best_flights": [junk]}, QUERY).options[0]
    assert option.longest_layover_min == 90  # junk layovers ignored, legs used instead


def test_one_way_queries_reach_the_sources():
    seen = []
    one_way = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 11), one_way=True)
    source_returning(body=FIXTURE, seen=seen).exact_search(one_way)
    params = dict(seen[0].url.params)
    assert params["type"] == "2"
    assert (params["departure_id"], params["arrival_id"], params["outbound_date"]) == (
        "ORD",
        "LIS",
        "2027-06-11",
    )
    assert "return_date" not in params
