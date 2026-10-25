from ptopilot import config
from ptopilot.core.airports import AirportCatalog, distance_km, zone_for

CAT = AirportCatalog.load()


def test_search_by_city_puts_its_airport_first_and_offers_nearby_ones():
    first = CAT.search("Tokyo")[0]
    assert first.airport.code == "HND" and "NRT" in {a.code for a in first.nearby}


def test_search_by_country_lists_its_main_airports():
    codes = [m.airport.code for m in CAT.search("Japan")]
    assert codes and all(CAT.get(c).country == "JP" for c in codes) and {"HND", "NRT"} <= set(codes)


def test_search_by_iata_code_and_island_names():
    assert CAT.search("BDA")[0].airport.code == "BDA"
    assert CAT.search("bermuda")[0].airport.country == "BM"


def test_search_with_no_match_is_empty():
    assert CAT.search("zzqx") == [] and CAT.search("  ") == []


def test_search_is_capped_and_large_airports_come_first():
    results = CAT.search("international")
    assert len(results) == config.SEARCH_LIMIT
    sizes = [m.airport.size for m in results]
    assert sizes == sorted(sizes, key=["large", "medium", "small"].index)


def test_nearby_uses_distance_not_city_names():  # Narita's city is "Narita", not "Tokyo"
    assert "NRT" in {a.code for a in CAT.nearby("HND")}
    assert "KIX" not in {a.code for a in CAT.nearby("HND")}  # Osaka is ~400 km away


def test_distance_and_zones():
    assert 10_700 < distance_km(CAT.get("JFK"), CAT.get("HND")) < 10_950
    assert zone_for("JP", "AS") == "E_ASIA" and zone_for("TH", "AS") == "SE_ASIA"
    assert zone_for("BM", "NA") == "NA" and zone_for("PT", "EU") == "EUROPE"
    assert zone_for("CL", "SA") == "S_AMERICA" and zone_for("ZA", "AF") == "AFRICA"


def test_search_ignores_accents():
    assert CAT.search("cancun")[0].airport.code == "CUN"
    assert "GRU" in {m.airport.code for m in CAT.search("sao paulo")}
    assert CAT.search("sao")


def test_exact_city_match_beats_longer_city_names():
    assert CAT.search("Porto")[0].airport.code == "OPO"
    for query, code in [("Tokyo", "HND"), ("Lisbon", "LIS"), ("Paris", "CDG")]:
        assert CAT.search(query)[0].airport.code == code


def test_name_matches_need_a_whole_word():
    assert "SAL" not in {m.airport.code for m in CAT.search("Rome")}


def test_place_match_carries_country_name():
    assert CAT.search("HND")[0].country_name == "Japan"
