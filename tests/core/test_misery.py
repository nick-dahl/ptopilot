from types import SimpleNamespace

import pytest

from ptopilot.core.airports import AirportCatalog, CatalogAirport
from ptopilot.core.geo import Destination, Geo
from ptopilot.core.misery import Problem, assess, format_duration, problems
from ptopilot.data import _geo_destination, load_geo


def found(**kw):
    args = dict(
        longest_layover_min=None,
        layover_city=None,
        duration_min=None,
        fastest_min=None,
        ground_min=None,
        destination_name="Tokyo",
    )
    return problems(**{**args, **kw})


def kinds(found_problems):
    return [(p.kind, p.severity) for p in found_problems]


def test_layover_lines():
    assert found(longest_layover_min=300) == ()
    assert kinds(found(longest_layover_min=301)) == [("layover", "moderate")]
    assert kinds(found(longest_layover_min=541)) == [("layover", "severe")]


def test_duration_lines():
    assert found(duration_min=1390, fastest_min=1000) == ()
    assert kinds(found(duration_min=1400, fastest_min=1000)) == [("duration", "moderate")]
    assert kinds(found(duration_min=2000, fastest_min=1000)) == [("duration", "severe")]


def test_ground_lines():
    assert found(ground_min=59) == ()
    assert kinds(found(ground_min=60)) == [("ground", "moderate")]
    assert kinds(found(ground_min=120)) == [("ground", "severe")]


def test_missing_details_never_count_as_problems():
    assert found() == ()
    assert found(duration_min=3000) == ()
    assert found(fastest_min=1000) == ()
    assert found(duration_min=0, fastest_min=0) == ()


def test_verdicts():
    severe = found(longest_layover_min=600)
    two = found(longest_layover_min=400, ground_min=70)
    assert assess((), price=500, typical_median=1000, typical_confident=True).verdict == "ok"
    assert assess((), price=500, typical_median=1000, typical_confident=True).note is None
    assert assess(severe, price=100, typical_median=1000, typical_confident=True).verdict == "ruled_out"
    assert assess(two, price=400, typical_median=1000, typical_confident=True).verdict == "ruled_out"


def test_forgiveness_needs_forty_percent_on_a_normal_baseline():
    moderate = found(longest_layover_min=400, layover_city="Madrid")
    a = assess(moderate, price=590, typical_median=1000, typical_confident=True)
    assert a.verdict == "forgiven"
    assert a.note == "6h 40m layover in Madrid (worth it at 41% below typical)"
    assert assess(moderate, price=610, typical_median=1000, typical_confident=True).verdict == "ruled_out"
    assert assess(moderate, price=500, typical_median=1000, typical_confident=False).verdict == "ruled_out"
    assert assess(moderate, price=500, typical_median=None, typical_confident=True).verdict == "ruled_out"
    assert assess(moderate, price=600, typical_median=1000, typical_confident=True).verdict == "forgiven"


def test_copy_patterns():
    assert found(longest_layover_min=540, layover_city="Madrid")[0].text == "9h layover in Madrid"
    assert found(longest_layover_min=390, layover_city="Madrid")[0].text == "6h 30m layover in Madrid"
    assert found(longest_layover_min=540)[0].text == "9h layover"
    assert found(duration_min=2280, fastest_min=1086)[0].text == "38h journey, 2.1× the fastest"
    assert found(ground_min=75)[0].text == "Lands ~1h 15m from Tokyo"
    two = found(longest_layover_min=540, layover_city="Madrid", ground_min=75)
    assert assess(two, price=1, typical_median=None, typical_confident=False).note == (
        "9h layover in Madrid · Lands ~1h 15m from Tokyo"
    )
    assert format_duration(540) == "9h"
    assert format_duration(390) == "6h 30m"


def test_problem_is_a_value():
    assert Problem("layover", "moderate", "x") == Problem("layover", "moderate", "x")


def _airport(code, city, lat, lon=0.0):
    return CatalogAirport(code, code, city, "IT", "EU", lat, lon, "medium")


def test_own_airports_have_no_ground_time():
    geo = load_geo()
    tokyo = geo.destination("TYO")
    assert geo.ground_minutes(tokyo, "HND") == 0
    assert geo.ground_minutes(tokyo, "NRT") == 0

    catalog = AirportCatalog(
        [
            _airport("FCO", "Rome", 41.8),
            _airport("CIA", "Rome", 41.9),
            _airport("XXA", "Elsewhere", 41.8 + 0.8094),  # ~90 km north
        ],
        {},
    )
    row = SimpleNamespace(
        code="FCO_IT", name="Rome", kind="city", airports=["FCO", "CIA"], return_airports=None, color=None
    )
    rome = _geo_destination(row, catalog)
    assert rome.own_airports == ("FCO", "CIA")
    geo = Geo({}, {"FCO_IT": rome}, {}, geo._default_rule, catalog)
    assert geo.ground_minutes(rome, "FCO") == 0
    assert geo.ground_minutes(rome, "CIA") == 0

    ticked = _geo_destination(
        SimpleNamespace(
            code="FCO_IT", name="Rome", kind="city", airports=["FCO", "XXA"], return_airports=None, color=None
        ),
        catalog,
    )
    assert ticked.own_airports == ("FCO",)
    assert geo.ground_minutes(ticked, "XXA") == 85
    assert geo.ground_minutes(ticked, "ZZZ") is None


def test_default_own_airports_cover_both_ends():
    d = Destination("X", "X", "city", ("AAA",), "US", "NA", ("BBB",))
    assert d.own_airports == ("AAA", "BBB")


@pytest.mark.parametrize("minutes,expected", [(0, "0h"), (65, "1h 5m")])
def test_format_duration_edges(minutes, expected):
    assert format_duration(minutes) == expected
