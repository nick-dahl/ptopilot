"""Fixture follows the documented prices_for_dates fields; swap for a real recording once a token exists."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from ptopilot.sources.base import SourceUnavailable
from ptopilot.sources.travelpayouts import API_URL, TravelpayoutsSource, parse_prices_for_dates

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "travelpayouts_ORD_LIS_2027-06.json").read_text())


def source_returning(status=200, body=None, text=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    return TravelpayoutsSource("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_maps_fields_and_skips_zero_prices():
    quotes = parse_prices_for_dates(FIXTURE, "ORD", "LIS")
    assert len(quotes) == 2
    q = quotes[0]
    assert (q.origin, q.dest_airport) == ("ORD", "LIS")
    assert (q.depart_date, q.return_date) == (date(2027, 6, 11), date(2027, 6, 20))
    assert (q.price, q.currency) == (612.0, "USD")
    assert (q.airline, q.flight_number, q.stops, q.return_stops) == ("TP", "TP 246", 1, 1)
    assert q.duration_min == 760
    assert q.deep_link.startswith("https://www.aviasales.com/search/CHI1106LIS20061")
    assert q.source == "travelpayouts"


def test_departure_date_is_local_not_utc():
    # 18:15 at -05:00 is 23:15 UTC same day; a late flight must not shift to the next day.
    late = {
        "success": True,
        "currency": "usd",
        "data": [{**FIXTURE["data"][0], "departure_at": "2027-06-11T23:30:00-05:00"}],
    }
    assert parse_prices_for_dates(late, "ORD", "LIS")[0].depart_date == date(2027, 6, 11)


def test_month_scan_sends_expected_request():
    seen = []
    src = source_returning(body=FIXTURE, seen=seen)
    quotes = src.month_scan("ORD", "LIS", date(2027, 6, 1), market="US", currency="USD")
    assert len(quotes) == 2
    req = seen[0]
    assert str(req.url).startswith(API_URL)
    assert req.headers["X-Access-Token"] == "tok"
    params = dict(req.url.params)
    assert params["departure_at"] == "2027-06"
    assert (params["origin"], params["destination"], params["market"], params["currency"]) == (
        "ORD",
        "LIS",
        "us",
        "usd",
    )
    assert params["one_way"] == "false"


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"status": 401, "text": "Unauthorized"}, "HTTP 401"),
        ({"status": 200, "text": "<html>oops</html>"}, "invalid JSON"),
        ({"status": 200, "body": {"success": False, "error": "quota"}}, "success=false"),
    ],
)
def test_failures_raise_source_unavailable(kwargs, match):
    with pytest.raises(SourceUnavailable, match=match):
        source_returning(**kwargs).month_scan("ORD", "LIS", date(2027, 6, 1), "us", "usd")


def test_network_error_raises_source_unavailable():
    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    src = TravelpayoutsSource("tok", client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(SourceUnavailable, match="ConnectTimeout"):
        src.month_scan("ORD", "LIS", date(2027, 6, 1), "us", "usd")


def test_empty_token_is_rejected():
    with pytest.raises(ValueError, match="TRAVELPAYOUTS_TOKEN"):
        TravelpayoutsSource("")
