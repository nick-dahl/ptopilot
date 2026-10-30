"""Small actions answer JSON when the page's script asks (Accept: application/json), and keep their
plain POST-then-redirect behaviour otherwise, so every form still works without JavaScript."""

import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from ptopilot.db.models import PlannedTrip, Tracker
from ptopilot.db.session import session_scope
from tests.web.conftest import TODAY, seed_profile, sign_in
from tests.web.test_plan_page import YEAR, add_trip, book_row, start_year
from tests.web.test_plan_page import signed_in as plan_signed_in

JSON = {"Accept": "application/json"}
signed_in = plan_signed_in  # the planner tests' fixture: signed in with a profile, no trips


def my_tracker(client, emailer, engine) -> int:
    sign_in(client, emailer, engine)
    seed_profile(engine)
    with session_scope(engine) as s:
        return s.scalar(select(Tracker.id))


def test_snooze_answers_json_when_asked(client, emailer, clean_engine):
    t = my_tracker(client, emailer, clean_engine)
    r = client.post(f"/trackers/{t}/snooze", data={"days": "30"}, headers=JSON)
    assert r.status_code == 200 and r.json()["ok"] is True
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, t).snoozed_until == TODAY + timedelta(days=30)
    r = client.post(f"/trackers/{t}/unsnooze", headers=JSON)
    assert r.status_code == 200 and r.json() == {"ok": True}
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, t).snoozed_until is None


def test_snooze_still_redirects_without_json(client, emailer, clean_engine):
    t = my_tracker(client, emailer, clean_engine)
    r = client.post(f"/trackers/{t}/snooze", data={"days": "30", "next": f"/trackers/{t}"})
    assert (r.status_code, r.headers["location"]) == (303, f"/trackers/{t}")
    r = client.post(f"/trackers/{t}/unsnooze")
    assert (r.status_code, r.headers["location"]) == (303, "/")


def test_json_errors_are_4xx_with_messages(signed_in, clean_engine):
    uid = start_year(clean_engine)
    first = add_trip(clean_engine, uid, "LIS", 10)
    second = add_trip(clean_engine, uid, "AZORES", 8)
    book_row(clean_engine, first, date(2027, 5, 28), date(2027, 6, 5))
    r = signed_in.post(
        f"/plan/{YEAR}/trips/{second}/book",
        data={"depart": "2027-06-03", "return": "2027-06-10"},
        headers=JSON,
    )
    assert r.status_code == 400
    assert r.json() == {"ok": False, "errors": ["Overlaps your booked Lisbon trip."]}
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.booked_depart).where(PlannedTrip.tracker_id == second)) is None
    missing = signed_in.post(f"/plan/{YEAR}/trips/999999/cancel", headers=JSON)
    assert missing.status_code == 404 and missing.json()["ok"] is False and missing.json()["errors"]
    malformed = signed_in.post("/trackers/1/snooze", data={"days": "lots"}, headers=JSON)
    assert malformed.status_code == 400 and malformed.json()["ok"] is False


def test_plan_actions_answer_json(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    url = f"/plan/{YEAR}/trips/{tid}"
    assert signed_in.post(url, data={"target_days": "9"}, headers=JSON).json()["ok"] is True
    booked = signed_in.post(
        f"{url}/book", data={"depart": "2027-06-01", "return": "2027-06-08"}, headers=JSON
    )
    assert booked.status_code == 200 and booked.json()["ok"] is True
    assert signed_in.post(f"{url}/cancel", headers=JSON).json()["ok"] is True
    assert signed_in.post(f"{url}/remove", headers=JSON).json()["ok"] is True
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.id).where(PlannedTrip.tracker_id == tid)) is None


def test_destination_actions_answer_json(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    bad = signed_in.post(
        f"/destinations/{tid}/related", data={"airport": "QQQ", "action": "accept"}, headers=JSON
    )
    assert bad.status_code == 400 and bad.json()["errors"] == ["Pick a related place to accept or dismiss."]
    r = signed_in.post(f"/destinations/{tid}/remove", headers=JSON)
    assert r.status_code == 200 and r.json()["ok"] is True
    missing = signed_in.post("/destinations/999999/remove", headers=JSON)
    assert missing.status_code == 404 and missing.json()["errors"] == ["No such destination."]
    assert signed_in.post("/destinations/999999/remove").status_code == 404  # the page, as before


def test_in_place_endpoints_need_sign_in(client):
    posts = [
        ("/trackers/1/snooze", {"days": "30"}),
        ("/trackers/1/unsnooze", {}),
        ("/trackers/1/book", {"candidate_id": "1"}),
        ("/plan/2027/trips/1", {"target_days": "9"}),
        ("/plan/2027/trips/1/book", {"depart": "2027-06-01", "return": "2027-06-08"}),
        ("/plan/2027/trips/1/cancel", {}),
        ("/plan/2027/trips/1/remove", {}),
        ("/destinations/1/related", {"airport": "BUD", "action": "accept"}),
        ("/destinations/1/remove", {}),
    ]
    for url, data in posts:
        r = client.post(url, data=data, headers=JSON)
        assert r.status_code == 401, url
        assert r.json()["ok"] is False and r.json()["errors"], url
        plain = client.post(url, data=data)
        assert (plain.status_code, plain.headers["location"]) == (303, "/"), url


def test_pages_load_ui_js_as_a_module(client, emailer, clean_engine):
    t = my_tracker(client, emailer, clean_engine)
    tag = '<script type="module" src="/static/ui.js"></script>'
    for url in ("/", f"/trackers/{t}", "/destinations", "/profile"):
        assert tag in client.get(url).text, url
    js = client.get("/static/ui.js")
    assert js.status_code == 200 and "data-inplace" in js.text and "export function toast" in js.text


def test_small_action_forms_opt_in_to_in_place(client, emailer, clean_engine):
    t = my_tracker(client, emailer, clean_engine)
    html = client.get(f"/trackers/{t}").text
    assert 'data-inplace data-after="reload-section"' in html and 'id="dest-hero"' in html
    assert "data-inplace" in client.get("/destinations").text


STATIC = Path(__file__).resolve().parents[2] / "ptopilot" / "web" / "static"


def test_ui_js_posts_to_the_action_attribute_not_the_shadowable_property():
    """A control named "action" (the related forms' buttons) shadows form.action, so the script must
    read the attribute; form.method is shadowable the same way."""
    js = (STATIC / "ui.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in js.splitlines() if not line.lstrip().startswith("//"))
    assert "fetch(action," in code
    assert not re.search(r"\bform\.(action|method)\b", code)


def test_planner_swaps_the_calendar_and_rebinds_it(signed_in, clean_engine):
    uid = start_year(clean_engine)
    add_trip(clean_engine, uid, "LIS", 10)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert 'data-section="plan-trips combos-panel calendar-panel"' in html and 'id="calendar-panel"' in html
    assert 'new CustomEvent("ui:swapped"' in (STATIC / "ui.js").read_text(encoding="utf-8")
    planner = (STATIC / "planner.js").read_text(encoding="utf-8")
    assert 'addEventListener("ui:swapped"' in planner and "data-planner-bound" in planner
    assert 'removeEventListener("pointerup"' in planner  # the old calendar's window handlers go
