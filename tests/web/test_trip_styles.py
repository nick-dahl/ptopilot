"""Trip styles you love: a multi-select on the profile's Travel style section and onboarding step 3."""

import re

from sqlalchemy import select

from ptopilot.core.trip_styles import STYLES
from ptopilot.db.models import User
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, seed_profile, sign_in
from tests.web.test_destinations_page import make_client  # noqa: F401  (fixture)
from tests.web.test_welcome import TIME_OFF, TRAVEL

JSON = {"Accept": "application/json"}


def styles(engine, email="nick@example.com"):
    with session_scope(engine) as s:
        return list(s.scalar(select(User.trip_styles).where(User.email == email)))


def test_styles_vocabulary_is_exact():
    assert list(STYLES) == [
        "hiking_camping", "city_hopping", "rail", "beach", "islands", "adventure", "food_wine", "culture",
    ]  # fmt: skip
    assert STYLES["rail"] == "\U0001f686 Rail trips"
    assert STYLES["adventure"] == "\U0001f9ed Road trips & adventure"


def test_profile_saves_and_clears_trip_styles(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    assert styles(clean_engine) == []
    r = client.post("/profile", data={"section": "travel", "trip_styles": ["rail", "beach"]}, headers=JSON)
    assert r.status_code == 200 and r.json()["ok"]
    assert styles(clean_engine) == ["rail", "beach"]
    page = client.get("/profile").text
    assert re.search(r'name="trip_styles" value="rail"[^>]*checked', page)
    assert not re.search(r'name="trip_styles" value="culture"[^>]*checked', page)
    # Another section leaves them alone; unticking every chip clears them.
    client.post("/profile", data={"section": "airports", "home_airport": "JFK"}, headers=JSON)
    assert styles(clean_engine) == ["rail", "beach"]
    r = client.post("/profile", data={"section": "travel", "min_trip_days": "3"}, headers=JSON)
    assert r.status_code == 200
    assert styles(clean_engine) == []


def test_unknown_styles_are_refused(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    r = client.post(
        "/profile", data={"section": "travel", "trip_styles": ["rail", "skydiving"]}, headers=JSON
    )
    assert r.status_code == 400
    messages = [e["message"] for e in r.json()["field_errors"] if e["field"] == "trip_styles"]
    assert messages and "skydiving" in messages[0] and "trip_styles" not in messages[0]
    assert styles(clean_engine) == []


def test_welcome_step_three_offers_trip_styles(make_client, emailer, clean_engine):  # noqa: F811
    c = make_client()
    sign_in(c, emailer, clean_engine)
    c.post("/welcome/1", data={"airports": "PHL"})
    c.post("/welcome/2", data=TIME_OFF)
    page = c.get("/welcome/3").text
    assert "Trip styles you love" in page and "Pick any; we'll match hidden gems to them." in page
    for key in STYLES:
        assert f'name="trip_styles" value="{key}"' in page
    r = c.post("/welcome/3", data={**TRAVEL, "trip_styles": ["islands", "food_wine"]})
    assert (r.status_code, r.headers["location"]) == (303, "/welcome/4")
    assert styles(clean_engine) == ["islands", "food_wine"]


def test_trip_styles_post_without_js(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    page = client.get("/profile").text
    assert page.count('type="checkbox" name="trip_styles"') == len(STYLES)
    form = {**PROFILE_FORM, "section": "travel", "trip_styles": ["hiking_camping", "culture"]}
    r = client.post("/profile", data=form)  # a plain form post, no Accept header
    assert (r.status_code, r.headers["location"]) == (303, "/profile?saved=1")
    assert styles(clean_engine) == ["hiking_camping", "culture"]
    bad = client.post("/profile", data={**form, "trip_styles": ["skydiving"]})
    assert bad.status_code == 400 and "skydiving" in bad.text
