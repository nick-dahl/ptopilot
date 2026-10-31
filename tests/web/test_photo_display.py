"""Cover photos on the site: card covers with a gradient fallback, the credits page, and place search."""

import re
from datetime import UTC, datetime

from sqlalchemy import select

from ptopilot.db.models import Destination, PlacePhotoRow, PlannedTrip, PlanningYear, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.photos import builtin_photos
from tests.web.conftest import seed_profile, sign_in

JSON = {"Accept": "application/json"}
BCN_PHOTO = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Barcelona.jpg/1280px-Barcelona.jpg"


def add_barcelona(engine):
    """An added place the signed-in user tracks; it has no photo yet."""
    with session_scope(engine) as s:
        s.add(Destination(code="BCN_ES", name="Barcelona", kind="city", airports=["BCN"]))
        user = s.scalars(select(User)).one()
        tracker = Tracker(user_id=user.id, destination_code="BCN_ES", min_stay_days=5, max_stay_days=9)
        s.add(tracker)
        s.flush()
        for year in s.scalars(select(PlanningYear.year).where(PlanningYear.user_id == user.id)):
            s.add(PlannedTrip(user_id=user.id, year=year, tracker_id=tracker.id))


def add_photo(engine, code="BCN_ES", status="ok"):
    found = {
        "image_url": BCN_PHOTO,
        "width": 1280,
        "height": 853,
        "author": "Ana Gómez",
        "licence": "CC BY-SA 4.0",
        "source_url": "https://commons.wikimedia.org/wiki/File:Barcelona.jpg",
    }
    with session_scope(engine) as s:
        s.add(
            PlacePhotoRow(
                code=code, status=status, fetched_at=datetime.now(UTC), **(found if status == "ok" else {})
            )
        )


def card(page: str, name: str) -> str:
    [found] = [c for c in page.split('class="dest-card')[1:] if f"<h2>{name}</h2>" in c]
    return found


def test_cards_fall_back_to_the_gradient_without_a_photo(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)  # tracks the Azores, a built-in with a hand-picked photo
    add_barcelona(clean_engine)
    azores = builtin_photos()["AZORES"]

    page = client.get("/").text
    plain = card(page, "Barcelona")
    assert 'class="cover' in plain and "--cover" not in plain and "Photo:" not in plain
    pictured = card(page, "Azores")
    assert "has-photo" in pictured and f"--cover:url({azores.image_url})" in pictured
    assert f"Photo: {azores.author} · {azores.licence}" in pictured

    add_photo(clean_engine, status="none")
    assert "--cover" not in card(client.get("/").text, "Barcelona")  # a `none` row is no photo


def test_a_found_photo_shows_on_the_card(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    add_barcelona(clean_engine)
    add_photo(clean_engine)
    barcelona = card(client.get("/").text, "Barcelona")
    assert f"--cover:url({BCN_PHOTO})" in barcelona and "Photo: Ana Gómez · CC BY-SA 4.0" in barcelona


def test_credits_lists_shown_photos(client, clean_engine):
    add_photo(clean_engine)
    add_photo(clean_engine, code="ATH_GR", status="none")
    with session_scope(clean_engine) as s:
        s.add(Destination(code="BCN_ES", name="Barcelona", kind="city", airports=["BCN"]))

    response = client.get("/credits")  # public: no sign-in
    assert response.status_code == 200
    page = response.text
    for photo in builtin_photos().values():
        assert photo.author in page and photo.licence in page and photo.source_url in page
    assert "Barcelona" in page and "Ana Gómez" in page
    assert "ATH_GR" not in page
    assert 'loading="lazy"' in page
    assert re.search(r'href="/credits"', client.get("/").text)  # the footer links to it


def test_place_search_results_carry_a_photo(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    rows = client.get("/api/places", params={"q": "lisbon"}, headers=JSON).json()
    lisbon = next(r for r in rows if r["code"] == "LIS")
    assert lisbon["photo"] == builtin_photos()["LIS"].image_url

    rows = client.get("/api/places", params={"q": "barcelona"}, headers=JSON).json()
    assert rows and all(r["photo"] is None for r in rows)
    with session_scope(clean_engine) as s:
        s.add(Destination(code="BCN_ES", name="Barcelona", kind="city", airports=["BCN"]))
    add_photo(clean_engine)
    rows = client.get("/api/places", params={"q": "barcelona"}, headers=JSON).json()
    assert next(r for r in rows if r["code"] == "BCN")["photo"] == BCN_PHOTO


def test_the_place_dropdown_shows_a_small_square_photo():
    from pathlib import Path

    static = Path(__file__).resolve().parents[2] / "ptopilot" / "web" / "static"
    js = (static / "chips.js").read_text(encoding="utf-8")
    assert "photo" in js and '"lazy"' in js
    assert ".chip-thumb" in (static / "app.css").read_text(encoding="utf-8")
