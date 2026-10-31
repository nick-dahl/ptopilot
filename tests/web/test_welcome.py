"""The /welcome flow (spec §3.2): four steps that build a new traveler's profile, then the planner."""

from html.parser import HTMLParser

import pytest
from sqlalchemy import select

from ptopilot.db.models import PlannedTrip, PlanningYear, Tracker, User
from ptopilot.db.session import session_scope
from tests.web.conftest import TODAY, seed_profile, sign_in
from tests.web.test_destinations_page import make_client  # noqa: F401  (fixture)

JSON = {"Accept": "application/json"}
HEADINGS = (
    "Where do you fly from?",
    "Your time off",
    "How you like to travel",
    "Where would you love to go?",
)
TIME_OFF = {"pto_days_total": "20", "holiday_calendar": "US", "ignored_holidays": "", "extra_days_off": ""}
TRAVEL = {
    "min_trip_days": "4",
    "max_trip_days": "12",
    "ideal_trip_days": "8",
    "weather_tolerance": "strict",
    "max_stops_short": "0",
    "max_stops_long": "1",
    "allow_overnight_layover": "on",
    "friday_evening_min_time": "17:30",
}


@pytest.fixture
def newcomer(make_client, emailer, clean_engine):  # noqa: F811
    c = make_client()
    sign_in(c, emailer, clean_engine)
    return c


def user(engine, email="nick@example.com"):
    with session_scope(engine) as s:
        u = s.scalar(select(User).where(User.email == email))
        if u is not None:
            s.expunge(u)
        return u


def test_a_new_sign_in_lands_on_welcome(newcomer):
    for url in ("/", "/profile"):
        r = newcomer.get(url)
        assert (r.status_code, r.headers["location"]) == (303, "/welcome"), url
    r = newcomer.get("/welcome")
    assert (r.status_code, r.headers["location"]) == (303, "/welcome/1")
    page = newcomer.get("/welcome/1").text
    assert HEADINGS[0] in page and "Step 1 of 4" in page
    assert "Skip for now" not in page  # nothing to skip to before there is a profile
    assert newcomer.get("/welcome/3").headers["location"] == "/welcome/1"  # no jumping ahead


def test_step_one_creates_the_user_from_airport_chips(newcomer, clean_engine):
    r = newcomer.post("/welcome/1", data={"airports": "phl, JFK"})
    assert (r.status_code, r.headers["location"]) == (303, "/welcome/2")
    u = user(clean_engine)
    assert (u.home_airport, u.nearby_airports, u.country, u.holiday_calendar) == ("PHL", ["JFK"], "US", "US")
    assert (u.pto_days_total, u.max_trip_days, u.min_trip_days, u.weather_tolerance) == (15, 14, 3, "normal")
    assert (u.onboarded_at, u.welcome_step) == (None, 1)
    assert newcomer.get("/").headers["location"] == "/welcome"  # still onboarding


def test_step_one_explains_a_bad_airport_and_saves_nothing(newcomer, clean_engine):
    r = newcomer.post("/welcome/1", data={"airports": "XQZ"})
    assert r.status_code == 400 and "XQZ" in r.text and HEADINGS[0] in r.text
    assert newcomer.post("/welcome/1", data={"airports": ""}).status_code == 400
    assert user(clean_engine) is None
    bad = newcomer.post("/welcome/1", data={"airports": "XQZ"}, headers=JSON)
    assert bad.status_code == 400 and bad.json()["ok"] is False and bad.json()["errors"]


def test_onboarding_resumes_at_the_next_step(newcomer, emailer, clean_engine):
    assert newcomer.post("/welcome/1", data={"airports": "PHL"}).status_code == 303
    r = newcomer.post("/welcome/2", data=TIME_OFF)
    assert (r.status_code, r.headers["location"]) == (303, "/welcome/3")
    assert user(clean_engine).pto_days_total == 20
    newcomer.cookies.clear()  # a new browser, the same person
    sign_in(newcomer, emailer, clean_engine)
    assert newcomer.get("/").headers["location"] == "/welcome"
    assert newcomer.get("/welcome").headers["location"] == "/welcome/3"
    page = newcomer.get("/welcome/3").text
    assert HEADINGS[2] in page and "Step 3 of 4" in page and 'href="/welcome/2"' in page  # Back
    # Going back to an earlier step and saving it again never moves the bookmark backwards.
    assert newcomer.post("/welcome/1", data={"airports": "PHL, EWR"}).headers["location"] == "/welcome/2"
    assert user(clean_engine).welcome_step == 2 and user(clean_engine).nearby_airports == ["EWR"]


def test_existing_users_are_never_sent_to_welcome(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    assert user(clean_engine).onboarded_at is not None
    assert client.get("/").status_code == 200
    assert client.get("/profile").status_code == 200
    assert client.get("/welcome").status_code == 303  # still reachable when opened on purpose


def test_start_planning_creates_the_year_and_opens_the_planner(newcomer, clean_engine):
    newcomer.post("/welcome/1", data={"airports": "JFK"})
    newcomer.post("/welcome/2", data=TIME_OFF)
    r = newcomer.post("/welcome/3", data=TRAVEL)
    assert (r.status_code, r.headers["location"]) == (303, "/welcome/4")
    u = user(clean_engine)
    assert (u.min_trip_days, u.max_trip_days, u.ideal_trip_days, u.weather_tolerance) == (4, 12, 8, "strict")
    assert (u.max_stops_short, u.max_stops_long, u.allow_overnight_layover) == (0, 1, True)
    page = newcomer.get("/welcome/4").text
    assert HEADINGS[3] in page and "Start planning" in page
    # Start planning needs at least one place.
    empty = newcomer.post("/welcome/4", data={})
    assert empty.status_code == 400 and "Add at least one place" in empty.text
    added = newcomer.post("/welcome/4", data={"code": "HND", "airports": ["HND", "NRT"], "target_days": "12"})
    assert (added.status_code, added.headers["location"]) == (303, "/welcome/4")
    assert "Tokyo" in newcomer.get("/welcome/4").text
    done = newcomer.post("/welcome/4", data={})
    year = TODAY.year
    assert (done.status_code, done.headers["location"]) == (303, f"/plan/{year}")
    with session_scope(clean_engine) as s:
        py = s.get(PlanningYear, (u.id, year))
        assert (py.pto_days, py.other_time_off) == (20, 0)
        tracker = s.scalar(select(Tracker).where(Tracker.user_id == u.id))
        planned = s.scalars(select(PlannedTrip.tracker_id).where(PlannedTrip.user_id == u.id)).all()
        assert planned == [tracker.id]
    finished = user(clean_engine)
    assert finished.onboarded_at is not None and finished.welcome_step == 4
    assert newcomer.get("/").status_code == 200
    assert newcomer.get(f"/plan/{year}").status_code == 200


def test_step_four_takes_at_most_five_places(newcomer, clean_engine):
    newcomer.post("/welcome/1", data={"airports": "JFK"})
    newcomer.post("/welcome/2", data=TIME_OFF)
    newcomer.post("/welcome/3", data=TRAVEL)
    for code in ("HND", "LIS", "CDG", "FCO", "BCN"):
        r = newcomer.post("/welcome/4", data={"code": code, "airports": [code], "target_days": "9"})
        assert r.status_code == 303, code
    sixth = newcomer.post("/welcome/4", data={"code": "ATH", "airports": ["ATH"], "target_days": "9"})
    assert sixth.status_code == 400 and "five" in sixth.text
    with session_scope(clean_engine) as s:
        assert len(s.scalars(select(Tracker.id)).all()) == 5


def test_skip_for_now_finishes_onboarding(newcomer, clean_engine):
    newcomer.post("/welcome/1", data={"airports": "JFK"})
    page = newcomer.get("/welcome/2").text
    assert "Skip for now" in page
    r = newcomer.post("/welcome/2", data={"skip": "1"})
    assert (r.status_code, r.headers["location"]) == (303, "/")
    assert user(clean_engine).onboarded_at is not None
    assert newcomer.get("/").status_code == 200
    assert newcomer.get("/profile").status_code == 200


class Forms(HTMLParser):
    """Every form on a page with the names of its fields: what a browser without JS would submit."""

    def __init__(self):
        super().__init__()
        self.forms = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"action": a.get("action"), "method": a.get("method", "get"), "fields": set()})
        elif tag in ("input", "select", "button", "textarea") and self.forms and a.get("name"):
            if "disabled" not in a:
                self.forms[-1]["fields"].add(a["name"])


def forms_on(page: str) -> list[dict]:
    parser = Forms()
    parser.feed(page)
    return parser.forms


def test_welcome_steps_post_without_js(newcomer, clean_engine):
    step1 = [f for f in forms_on(newcomer.get("/welcome/1").text) if f["action"] == "/welcome/1"]
    assert step1 and step1[0]["method"] == "post" and "airports" in step1[0]["fields"]
    newcomer.post("/welcome/1", data={"airports": "JFK"})
    step2 = [f for f in forms_on(newcomer.get("/welcome/2").text) if f["action"] == "/welcome/2"]
    names = set().union(*(f["fields"] for f in step2))
    assert {"pto_days_total", "holiday_calendar", "extra_days_off", "skip"} <= names
    newcomer.post("/welcome/2", data=TIME_OFF)
    step3 = [f for f in forms_on(newcomer.get("/welcome/3").text) if f["action"] == "/welcome/3"]
    names = set().union(*(f["fields"] for f in step3))
    assert {"min_trip_days", "max_trip_days", "weather_tolerance", "max_stops_short"} <= names
    newcomer.post("/welcome/3", data=TRAVEL)
    # Step 4 without JS: the search reloads the page with matches, each its own add form.
    page = newcomer.get("/welcome/4?q=Tokyo").text
    adds = [f for f in forms_on(page) if f["action"] == "/welcome/4" and "airports" in f["fields"]]
    assert adds and {"code", "target_days"} <= adds[0]["fields"]
    search = [f for f in forms_on(page) if f["action"] == "/welcome/4" and f["method"] == "get"]
    assert search
    # And the same step answers JSON for the script.
    ok = newcomer.post(
        "/welcome/4", data={"code": "HND", "airports": ["HND"], "target_days": "9"}, headers=JSON
    )
    assert ok.status_code == 200 and ok.json()["ok"] is True


def test_welcome_needs_sign_in(client):
    for url in ("/welcome", "/welcome/1", "/welcome/4"):
        r = client.get(url)
        assert (r.status_code, r.headers["location"]) == (303, "/"), url
    assert client.post("/welcome/1", data={"airports": "JFK"}).headers["location"] == "/"
    assert client.post("/welcome/1", data={"airports": "JFK"}, headers=JSON).status_code == 401
    assert client.get("/welcome/9").status_code == 400
