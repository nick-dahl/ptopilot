from datetime import date, timedelta

from sqlalchemy import select

from ptopilot.db.models import Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from ptopilot.web.forms import form_to_profile
from tests.digest.conftest import add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, sign_in


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


def test_new_traveler_fills_in_the_profile_and_lands_on_the_dashboard(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    form_page = client.get("/profile")
    assert form_page.status_code == 200 and "Your travel profile" in form_page.text
    saved = client.post("/profile", data=PROFILE_FORM)
    assert (saved.status_code, saved.headers["location"]) == (303, "/?saved=1")
    with session_scope(clean_engine) as s:
        user = s.scalar(select(User).where(User.email == "nick@example.com"))
        assert (user.home_airport, user.pto_days_total, user.pto_committed) == ("JFK", 22, 7)
        assert [t.destination_code for t in s.scalars(select(Tracker))] == ["AZORES"]
        assert len(list(s.scalars(select(TravelWindow)))) == 1
    dashboard = client.get("/?saved=1")
    assert "Profile saved" in dashboard.text and "15</b> days available" in dashboard.text
    assert "Azores" in dashboard.text and "No prices yet" in dashboard.text


def test_invalid_profile_lists_every_problem_and_saves_nothing(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    bad = {**PROFILE_FORM, "pto_committed": "30", "home_airport": "XXX", "window_end_0": "2027-02-01"}
    response = client.post("/profile", data=bad)
    assert response.status_code == 400
    for fragment in ("Please fix 3 things", "pto_committed", "XXX", "before it starts"):
        assert fragment in response.text
    assert 'value="XXX"' in response.text  # the submitted values are kept
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None


def test_existing_profile_is_prefilled(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    page = client.get("/profile").text
    assert 'value="JFK"' in page and 'value="EWR, PHL"' in page and 'value="2027-03-01"' in page
    assert '<option value="AZORES" selected>' in page


def test_dashboard_shows_prices_and_snooze_controls(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    add_candidate(clean_engine, tracker_id, 603, level="good", run_date=TODAY)
    page = client.get("/").text
    assert "$603" in page and "Good deal" in page and "See flights" in page
    assert client.post(f"/trackers/{tracker_id}/snooze", data={"days": "30"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until == TODAY + timedelta(days=30)
    assert "snoozed to" in client.get("/").text
    client.post(f"/trackers/{tracker_id}/unsnooze")
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until is None


def test_cannot_touch_someone_elses_tracker(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine, "owner@example.com")
    client.post("/profile", data=PROFILE_FORM)
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
