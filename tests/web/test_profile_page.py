"""The profile form: grouped sections and the preferred trip length."""

from sqlalchemy import select

from ptopilot.db.models import PlannedTrip, PlanningYear, Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, seed_profile, sign_in


def test_profile_is_grouped_into_sections(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    page = client.get("/profile").text
    sections = ("Airports", "Time off", "Travel style")
    assert all(f"<h2>{heading}</h2>" in page for heading in sections)
    assert 'name="ideal_trip_days"' in page and 'aria-current="page"' in page


def test_saving_an_ideal_length_stores_it_and_shows_it_again(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "10"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User.ideal_trip_days)) == 10
    assert (
        'name="ideal_trip_days" type="number" inputmode="numeric" min="1" value="10"'
        in client.get("/profile").text
    )


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


def plan_state(s):
    return (
        s.scalars(select(TravelWindow.id)).all(),
        s.scalars(select(Tracker.id)).all(),
        s.scalars(select(PlannedTrip.tracker_id)).all(),
        s.scalars(select(PlanningYear.year)).all(),
    )


def test_profile_form_no_longer_has_windows_or_bucket_list(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    page = client.get("/profile").text
    for gone in ("window_start", "tracker_dest", "pto_committed", "Travel windows", "Bucket list"):
        assert gone not in page
    assert "PTO days per year" in page and "Used to start each new planning year." in page
    with session_scope(clean_engine) as s:
        before = plan_state(s)
    form = {k: v for k, v in PROFILE_FORM.items() if not k.startswith(("window_", "tracker_"))}
    changed = {
        **form,
        "home_airport": "ewr",
        "nearby_airports": "PHL",
        "min_trip_days": "5",
        "pto_committed": "20",
    }
    assert client.post("/profile", data={**changed, "weather_tolerance": "relaxed"}).status_code == 303
    with session_scope(clean_engine) as s:
        user = s.scalar(select(User))
        assert (user.home_airport, user.min_trip_days, user.weather_tolerance) == ("EWR", 5, "relaxed")
        assert user.pto_committed == 7  # the profile never changes it
        assert plan_state(s) == before
