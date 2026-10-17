"""The profile form: grouped sections and the preferred trip length."""

from sqlalchemy import select

from ptopilot.db.models import User
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, sign_in


def test_profile_is_grouped_into_sections(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    page = client.get("/profile").text
    sections = ("Home and calendar", "PTO and trip length", "Travel windows", "Bucket list", "Preferences")
    assert all(f"<h2>{heading}</h2>" in page for heading in sections)
    assert 'name="ideal_trip_days"' in page and 'aria-current="page"' in page


def test_saving_an_ideal_length_stores_it_and_shows_it_again(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "10"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User.ideal_trip_days)) == 10
    assert 'name="ideal_trip_days" type="text" value="10"' in client.get("/profile").text


def test_clearing_the_ideal_length_removes_the_preference(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "10"})
    client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": ""})
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User.ideal_trip_days)) is None


def test_an_ideal_outside_the_trip_range_is_explained_on_the_page(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    response = client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "30"})
    assert response.status_code == 400
    assert "ideal_trip_days: 30 is outside your trip length 7..16" in response.text
    assert 'class="panel notice-error"' in response.text
