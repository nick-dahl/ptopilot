from datetime import date, datetime

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, snippet

QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))


def option(price):
    return FlightOption(
        price=price, carrier="TAP", stops=0, duration_min=480, outbound_departure=datetime(2027, 6, 11, 18)
    )


def test_cheapest_picks_lowest_price():
    result = ExactResult("x", QUERY, "USD", (option(700), option(612), option(650)), "https://link")
    assert result.cheapest().price == 612


def test_cheapest_of_nothing_is_none():
    assert ExactResult("x", QUERY, "USD", (), "https://link").cheapest() is None


def test_query_defaults_to_usd():
    assert QUERY.currency == "USD"


def test_snippet_flattens_and_truncates():
    assert snippet("a\n  b\tc") == "a b c"
    assert snippet("x" * 400, limit=10) == "x" * 10 + "…"
