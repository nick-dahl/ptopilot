"""The type-ahead endpoints behind the chip inputs: airports, places and a calendar's holiday names."""

from ptopilot.core.airports import AirportCatalog
from tests.web.conftest import sign_in

JSON = {"Accept": "application/json"}
CATALOG = AirportCatalog.load()


def test_airport_search_needs_two_characters(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    for q in ("", "p", " p "):
        response = client.get("/api/airports", params={"q": q}, headers=JSON)
        assert (response.status_code, response.json()) == (200, [])


def test_airport_search_finds_city_and_code_nearest_first(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    rows = client.get("/api/airports", params={"q": "new", "near": "PHL"}, headers=JSON).json()
    codes = [r["code"] for r in rows]
    assert len(rows) <= 6 and "EWR" in codes and "LGA" in codes
    assert codes.index("EWR") < codes.index("LGA")
    assert all(CATALOG.get(c).size in ("large", "medium") for c in codes)
    assert set(rows[0]) == {"code", "name", "city", "country", "km"}
    assert rows[0] == {
        "code": "EWR",
        "name": CATALOG.get("EWR").name,
        "city": "Newark",
        "country": "US",
        "km": 128,
    }
    kms = [r["km"] for r in rows]
    assert kms == sorted(kms)  # one match kind here (city), so nearest first throughout
    by_code = client.get("/api/airports", params={"q": "phl", "near": "JFK"}, headers=JSON).json()
    assert by_code[0]["code"] == "PHL"  # an exact code leads
    far = client.get("/api/airports", params={"q": "new"}, headers=JSON).json()
    assert far and all(r["km"] is None for r in far)  # no `near`, no distance


def test_place_search_reuses_the_destination_search(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    rows = client.get("/api/places", params={"q": "lisbon"}, headers=JSON).json()
    first = rows[0]
    assert (first["code"], first["name"], first["country"]) == ("LIS", "Lisbon", "Portugal")
    assert first["airports"][0] == {"code": "LIS", "name": CATALOG.get("LIS").name}
    assert len(rows) <= 6
    assert client.get("/api/places", params={"q": "l"}, headers=JSON).json() == []


def test_holiday_names_come_from_the_calendar(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    names = client.get("/api/holidays", params={"calendar": "US"}, headers=JSON).json()
    assert "Columbus Day" in names and "Veterans Day" in names
    assert len(names) == len(set(names)) and not any("observed" in n for n in names)
    assert client.get("/api/holidays", params={"calendar": "ZZ"}, headers=JSON).json() == []


def test_api_needs_sign_in(client):
    for url in ("/api/airports?q=new", "/api/places?q=lisbon", "/api/holidays?calendar=US"):
        response = client.get(url, headers=JSON)
        assert response.status_code == 401, url
        assert response.json()["ok"] is False
        plain = client.get(url)
        assert (plain.status_code, plain.headers["location"]) == (303, "/"), url
