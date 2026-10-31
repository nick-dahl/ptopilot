from datetime import date, timedelta

from sqlalchemy import select

from ptopilot.db.models import Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from ptopilot.web.forms import form_to_profile
from tests.digest.conftest import add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in


def test_form_to_profile_maps_fields_and_skips_blank_rows():
    data = form_to_profile(PROFILE_FORM, "nick@example.com")
    assert data["home_airport"] == "JFK" and data["nearby_airports"] == ["EWR", "PHL"]
    assert data["pto_days_total"] == 22 and data["allow_overnight_layover"] is True
    assert data["windows"] == [{"start": "2027-03-01", "end": "2027-03-31"}]
    assert data["trackers"] == [{"destination": "AZORES", "min_stay": 7, "max_stay": 10, "priority": 1}]
    assert (
        form_to_profile({**PROFILE_FORM, "pto_days_total": "lots"}, "x@example.com")["pto_days_total"]
        == "lots"
    )


def test_a_whole_profile_from_a_new_traveler_is_still_taken(client, emailer, clean_engine):
    """New people start at /welcome; the old single profile form still works for them (and onboards them)."""
    sign_in(client, emailer, clean_engine)
    assert client.get("/profile").headers["location"] == "/welcome"
    saved = client.post("/profile", data=PROFILE_FORM)
    assert (saved.status_code, saved.headers["location"]) == (303, "/plan/new")
    with session_scope(clean_engine) as s:
        user = s.scalar(select(User).where(User.email == "nick@example.com"))
        assert (user.home_airport, user.pto_days_total, user.pto_committed) == ("JFK", 22, 0)
        assert list(s.scalars(select(Tracker))) == [] and list(s.scalars(select(TravelWindow))) == []
    dashboard = client.get("/?saved=1")
    assert "Profile saved" in dashboard.text and "22</b> PTO days left" in dashboard.text


def test_invalid_profile_lists_every_problem_and_saves_nothing(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    bad = {**PROFILE_FORM, "pto_days_total": "-3", "home_airport": "XXX", "max_trip_days": "2"}
    response = client.post("/profile", data=bad)
    assert response.status_code == 400
    friendly = ("PTO days per year can&#39;t be below 0", "XXX", "longer than the longest")
    for fragment in ("Please fix 3 things", *friendly):
        assert fragment in response.text
    assert 'value="XXX"' in response.text  # the submitted values are kept
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None


def test_existing_profile_is_prefilled(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    page = client.get("/profile").text
    assert 'value="JFK"' in page and 'value="EWR, PHL"' in page and 'value="22"' in page


def test_dashboard_shows_prices_and_snooze_controls(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    add_candidate(clean_engine, tracker_id, 603, level="good", run_date=TODAY)
    page = client.get("/").text
    assert "$603" in page and f'href="/trackers/{tracker_id}"' in page
    assert client.post(f"/trackers/{tracker_id}/snooze", data={"days": "30"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until == TODAY + timedelta(days=30)
    snoozed = client.get("/").text
    assert "Snoozed until Sat Apr 3" in snoozed and f'action="/trackers/{tracker_id}/unsnooze"' in snoozed
    client.post(f"/trackers/{tracker_id}/unsnooze")
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until is None


def test_cannot_touch_someone_elses_tracker(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine, "owner@example.com")
    seed_profile(clean_engine, email="owner@example.com")
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    client.post("/logout")
    sign_in(client, emailer, clean_engine, "intruder@example.com")
    assert client.post(f"/trackers/{tracker_id}/snooze", data={"days": "30"}).status_code == 404
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until is None


def test_dashboard_pto_bar_handles_zero_pto(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data={**PROFILE_FORM, "pto_days_total": "0", "pto_committed": "0"})
    assert client.get("/").status_code == 200


def test_unused_date_helper():
    assert date(2027, 3, 4) == TODAY
