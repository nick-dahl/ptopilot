"""Starting a planning year, and onboarding into it."""

from datetime import date

from sqlalchemy import select

from ptopilot.db.models import PlannedTrip, PlanningYear, Tracker, TravelWindow
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, seed_profile, sign_in

TWO_TRIPS = {**PROFILE_FORM, "tracker_dest_1": "MADEIRA", "tracker_min_1": "6", "tracker_max_1": "9"}


def tracker_ids(engine) -> dict[str, int]:
    with session_scope(engine) as s:
        return {t.destination_code: t.id for t in s.scalars(select(Tracker))}


def test_new_year_page_loads(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    assert client.get("/plan/new").status_code == 200


def test_start_planning_carries_checked_trips_and_starts_with_no_ranges(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine, TWO_TRIPS)
    ids = tracker_ids(clean_engine)
    data = {"year": "2028", "pto_days": "20", "other_time_off": "2", "tracker_ids": [ids["AZORES"]]}
    response = client.post("/plan/new", data=data)
    assert (response.status_code, response.headers["location"]) == (303, "/plan/2028")
    with session_scope(clean_engine) as s:
        row = s.scalar(select(PlanningYear).where(PlanningYear.year == 2028))
        assert (row.pto_days, row.other_time_off) == (20, 2)
        trips = s.scalars(select(PlannedTrip.tracker_id).where(PlannedTrip.year == 2028)).all()
        assert trips == [ids["AZORES"]]
        assert s.scalars(select(TravelWindow).where(TravelWindow.start_date >= date(2028, 1, 1))).all() == []


def test_posting_start_twice_redirects_to_the_year(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    data = {"year": "2028", "pto_days": "20", "other_time_off": "0"}
    first = client.post("/plan/new", data=data)
    again = client.post("/plan/new", data={**data, "pto_days": "5"})
    assert first.headers["location"] == again.headers["location"] == "/plan/2028"
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlanningYear.pto_days).where(PlanningYear.year == 2028)) == 20


def test_a_bad_start_rerenders_with_the_reason(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    response = client.post("/plan/new", data={"year": "2028", "pto_days": "5", "other_time_off": "9"})
    assert response.status_code == 400
    assert "Start planning" in response.text and "PTO must satisfy" in response.text
    late = client.post("/plan/new", data={"year": "2040", "pto_days": "5", "other_time_off": "0"})
    assert late.status_code == 400


def test_new_year_page_defaults_and_prefills(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine, TWO_TRIPS)  # has a 2027 year with 22 PTO days
    page = client.get("/plan/new").text
    assert "Start planning 2028" in page
    assert '<option value="2028" selected>' in page and 'value="2027"' not in page
    assert 'name="pto_days"' in page and 'value="22"' in page
    assert 'name="other_time_off"' in page and 'value="0"' in page
    assert page.count('name="tracker_ids"') == 2 and page.count("checked") == 2
    assert "Open ranges start empty. You&#39;ll drag them on the next page." in page or (
        "Open ranges start empty. You'll drag them on the next page." in page
    )
    assert "Want somewhere new? Add destinations any time." in page


def test_new_traveler_goes_from_profile_to_start_planning(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    saved = client.post("/profile", data=PROFILE_FORM)
    assert (saved.status_code, saved.headers["location"]) == (303, "/plan/new")
    page = client.get("/plan/new").text  # no years yet: this year, PTO from the profile
    assert "Start planning 2027" in page and 'value="22"' in page
    again = client.post("/profile", data=PROFILE_FORM)
    assert again.headers["location"] == "/?saved=1"
