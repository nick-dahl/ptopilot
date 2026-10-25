import yaml

from ptopilot.core.airports import AirportCatalog, CatalogAirport, zone_for
from ptopilot.core.geo import Destination, Geo, TravelRule
from ptopilot.data import DATA_DIR

CATALOG = AirportCatalog.load()
GEO = Geo.from_dict(yaml.safe_load((DATA_DIR / "geo.yaml").read_text(encoding="utf-8")), CATALOG)


def destination_at(code: str) -> Destination:
    a = CATALOG.get(code)
    return Destination(code, a.city, "city", (code,), a.country, zone_for(a.country, a.continent))


def test_a_zone_pair_in_geo_yaml_still_wins():
    tokyo = destination_at("HND")
    assert GEO.travel_rule("JFK", tokyo) == TravelRule(2.5, 7)  # the NA-E_ASIA pair


def test_without_a_zone_pair_distance_decides():
    cape_town = destination_at("CPT")  # NA-AFRICA has no pair; JFK-CPT is about 12,600 km
    assert GEO.travel_rule("JFK", cape_town) == TravelRule(3.0, 9)
    lima = destination_at("LIM")  # NA-S_AMERICA pair exists
    assert GEO.travel_rule("JFK", lima) == TravelRule(3.0, 9)


def test_catalog_airports_resolve_even_when_not_in_geo_yaml():
    assert GEO.airport("BDA").country == "BM"


class StubCatalog:
    def __init__(self, *airports):
        self._by_code = {a.code: a for a in airports}

    def get(self, code):
        return self._by_code.get(code.strip().upper())


def _stub_airport(code, lon):
    return CatalogAirport(code, code, code, "ZZ", "AF", 0.0, lon, "large")


def _stub_geo(catalog):
    data = {
        "airports": {"AAA": {"country": "ZZ", "zone": "OTHER"}},
        "destinations": {},
        "travel": {"default": {"overhead_days": 1, "min_trip_days": 2}, "pairs": []},
    }
    return Geo.from_dict(data, catalog)


def _stub_dest(code):
    return Destination(code, code, "city", (code,), "ZZ", "OTHER")


def test_exactly_1500_km_uses_the_first_band(monkeypatch):
    catalog = StubCatalog(_stub_airport("AAA", 0.0), _stub_airport("BBB", 10.0))
    monkeypatch.setattr("ptopilot.core.geo.distance_km", lambda a, b: 1500.0)
    assert _stub_geo(catalog).travel_rule("AAA", _stub_dest("BBB")) == TravelRule(1.0, 3)


def test_an_airport_missing_from_the_catalog_gets_the_default_rule():
    catalog = StubCatalog(_stub_airport("AAA", 0.0))
    assert _stub_geo(catalog).travel_rule("AAA", _stub_dest("BBB")) == TravelRule(1.0, 2)


def test_without_a_catalog_the_default_rule_is_kept():
    geo = _stub_geo(None)
    assert geo.travel_rule("AAA", _stub_dest("BBB")) == TravelRule(1.0, 2)
