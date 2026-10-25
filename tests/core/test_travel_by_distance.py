import yaml

from ptopilot.core.airports import AirportCatalog, zone_for
from ptopilot.core.geo import Destination, Geo, TravelRule
from ptopilot.data import DATA_DIR

CATALOG = AirportCatalog.load()
GEO = Geo.from_dict(yaml.safe_load((DATA_DIR / "geo.yaml").read_text()), CATALOG)


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
