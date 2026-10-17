import pytest

from ptopilot.core.geo import Geo, TravelRule, UnknownCodeError

DATA = {
    "airports": {
        "ORD": {"country": "US", "zone": "NA"},
        "LAX": {"country": "US", "zone": "NA"},
        "BKK": {"country": "TH", "zone": "SE_ASIA"},
        "HKT": {"country": "TH", "zone": "SE_ASIA"},
    },
    "destinations": {
        "TH": {"name": "Thailand", "kind": "region", "airports": ["BKK", "HKT"]},
        "LAX": {"name": "Los Angeles", "kind": "city", "airports": ["LAX"]},
    },
    "travel": {
        "default": {"overhead_days": 1, "min_trip_days": 2},
        "pairs": [{"zones": ["NA", "SE_ASIA"], "overhead_days": 3, "min_trip_days": 9}],
    },
}
GEO = Geo.from_dict(DATA)


def test_destination_takes_country_and_zone_from_first_airport():
    th = GEO.destination("TH")
    assert th.airports == ("BKK", "HKT")
    assert (th.country, th.zone) == ("TH", "SE_ASIA")


def test_travel_rule_for_known_pair():
    assert GEO.travel_rule("ORD", GEO.destination("TH")) == TravelRule(3.0, 9)


def test_travel_rule_falls_back_to_default():
    assert GEO.travel_rule("ORD", GEO.destination("LAX")) == TravelRule(1.0, 2)


def test_is_international():
    assert GEO.is_international("ORD", GEO.destination("TH"))
    assert not GEO.is_international("ORD", GEO.destination("LAX"))


def test_unknown_codes_are_clear_errors():
    with pytest.raises(UnknownCodeError, match="ZZZ"):
        GEO.destination("ZZZ")
    with pytest.raises(UnknownCodeError, match="XXX"):
        GEO.airport("XXX")


def test_destination_with_unknown_airport_is_rejected():
    bad = {**DATA, "destinations": {"X": {"name": "X", "kind": "city", "airports": ["NOPE"]}}}
    with pytest.raises(ValueError, match="NOPE"):
        Geo.from_dict(bad)


def test_open_jaw_destination_has_separate_return_airports():
    data = {
        **DATA,
        "airports": {
            **DATA["airports"],
            "OPO": {"country": "PT", "zone": "EUROPE"},
            "SCQ": {"country": "ES", "zone": "EUROPE"},
        },
        "destinations": {
            "CAMINO": {"name": "Camino", "kind": "route", "airports": ["OPO"], "return_airports": ["SCQ"]}
        },
    }
    camino = Geo.from_dict(data).destination("CAMINO")
    assert (camino.airports, camino.home_from, camino.open_jaw) == (("OPO",), ("SCQ",), True)
    assert (camino.country, camino.zone) == ("PT", "EUROPE")


def test_ordinary_destination_flies_home_from_where_it_arrived():
    th = GEO.destination("TH")
    assert th.home_from == ("BKK", "HKT") and th.open_jaw is False


def test_unknown_return_airport_is_rejected():
    bad = {
        **DATA,
        "destinations": {
            "X": {"name": "X", "kind": "route", "airports": ["BKK"], "return_airports": ["NOPE"]}
        },
    }
    with pytest.raises(ValueError, match="NOPE"):
        Geo.from_dict(bad)
