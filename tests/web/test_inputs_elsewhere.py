"""The same inputs on the destinations page, the planner and Start planning."""

# ruff: noqa: F811  (the imported fixtures are used by name)

from sqlalchemy import select

from ptopilot.db.models import PlanningYear, Tracker
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, seed_profile, sign_in
from tests.web.test_destinations_page import (  # noqa: F401  (fixtures)
    fake_climate,
    make_client,
    signed_in,
    tracker_for,
)
from tests.web.test_plan_page import YEAR, add_trip, start_year

JSON = {"Accept": "application/json"}


def test_adding_a_place_returns_its_card_as_json(signed_in, clean_engine):
    r = signed_in.post(
        "/destinations", data={"code": "HND", "airports": ["HND", "NRT"], "target_days": "12"}, headers=JSON
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tracker_id"] == tracker_for(clean_engine, "TYO")[0]
    assert "Tokyo · 12 days away" in signed_in.get("/destinations").text


def test_a_refused_add_is_json_too(signed_in, clean_engine):
    r = signed_in.post(
        "/destinations", data={"code": "HND", "airports": ["NRT"], "target_days": "12"}, headers=JSON
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False and r.json()["errors"]
    assert tracker_for(clean_engine, "TYO") is None


def test_destinations_page_works_without_js(signed_in, clean_engine):
    html = signed_in.get("/destinations").text
    assert 'data-source="places"' in html  # the type-ahead, over a plain GET search form
    assert 'name="q"' in html and 'method="get"' in html
    found = signed_in.get("/destinations?q=Tokyo").text
    assert 'action="/destinations"' in found and 'value="HND" checked' in found
    r = signed_in.post("/destinations", data={"code": "HND", "airports": ["HND", "NRT"], "target_days": "9"})
    assert (r.status_code, r.headers["location"]) == (303, "/destinations")
    assert tracker_for(clean_engine, "TYO")[1] == 9


def test_the_add_card_template_is_on_the_page(signed_in):
    html = signed_in.get("/destinations").text
    assert 'id="add-card"' in html and "data-stepper" in html and "data-error-slot" in html
    assert 'type="module" src="/static/chips.js"' in html and "/static/places.js" in html


def test_planner_pto_saves_in_place(signed_in, clean_engine):
    uid = start_year(clean_engine)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "data-stepper" in html and 'name="pto_days"' in html and "/static/range.js" in html
    r = signed_in.post(f"/plan/{YEAR}/pto", data={"pto_days": "30", "other_time_off": "4"}, headers=JSON)
    assert r.status_code == 200 and r.json()["ok"] is True
    bad = signed_in.post(f"/plan/{YEAR}/pto", data={"pto_days": "3", "other_time_off": "9"}, headers=JSON)
    assert (
        bad.status_code == 400 and bad.json()["ok"] is False and "PTO must satisfy" in bad.json()["errors"][0]
    )
    with session_scope(clean_engine) as s:
        py = s.get(PlanningYear, (uid, YEAR))
        assert (py.pto_days, py.other_time_off) == (30, 4)


def test_planner_target_lengths_are_steppers_saving_in_place(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert f'id="target_days_{tid}"' in html and "data-autosave" in html
    r = signed_in.post(f"/plan/{YEAR}/trips/{tid}", data={"target_days": "13"}, headers=JSON)
    assert r.json()["ok"] is True
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).target_days == 13


def test_plan_new_cards_are_still_checkboxes(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(
        clean_engine,
        {**PROFILE_FORM, "tracker_dest_1": "MADEIRA", "tracker_min_1": "6", "tracker_max_1": "9"},
    )
    html = client.get("/plan/new").text
    assert html.count('type="checkbox" name="tracker_ids"') == 2
    assert html.count('class="seg"') == 2 and "data-stepper" in html
    ids = [t for t in select_ids(clean_engine)]
    r = client.post(
        "/plan/new", data={"year": "2028", "pto_days": "20", "other_time_off": "1", "tracker_ids": ids[:1]}
    )
    assert r.status_code == 303


def select_ids(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(Tracker.id)))


def test_a_json_add_never_redirects(signed_in, clean_engine):
    for data in (
        {"code": "LIS", "airports": ["LIS"], "target_days": "10"},
        {"code": "LIS", "airports": ["LIS", "CAT"], "target_days": "10"},
    ):
        r = signed_in.post("/destinations", data=data, headers=JSON)
        assert r.status_code == 200, (data, r.status_code, r.headers.get("location"), r.text[:200])
        assert r.json()["ok"] is True and "tracker_id" in r.json()
