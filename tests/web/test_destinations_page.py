"""The destinations page: search places, add them with a days-away target, remove them."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ptopilot.db.models import Destination, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.settings import Settings
from ptopilot.web.app import create_app
from tests.web.conftest import KEY, PROFILE_FORM, TODAY, sign_in

TOKYO = json.loads(
    (Path(__file__).parents[1] / "sources" / "fixtures" / "real_open_meteo_tokyo_2011_2020.json").read_text(
        encoding="utf-8"
    )
)


def fake_climate(lat, lon):
    return TOKYO


def failing_climate(lat, lon):
    raise httpx.ConnectError("offline")


@pytest.fixture
def make_client(clean_engine, emailer):
    clients = []

    def make(climate=fake_climate):
        settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
        app = create_app(settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY, climate=climate)
        c = TestClient(app, follow_redirects=False)
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def signed_in(make_client, emailer, clean_engine):
    c = make_client()
    sign_in(c, emailer, clean_engine)
    assert c.post("/profile", data=PROFILE_FORM).status_code == 303
    return c


def tracker_for(engine, code):
    with session_scope(engine) as s:
        t = s.scalars(select(Tracker).where(Tracker.destination_code == code)).first()
        return (t.id, t.target_days, t.active) if t else None


def add_tokyo(c, days="12"):
    return c.post("/destinations", data={"code": "HND", "airports": ["HND", "NRT"], "target_days": days})


def test_signed_out_visitors_go_home(client):
    r = client.get("/destinations")
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_searching_shows_places_with_nearby_airports(signed_in):
    html = signed_in.get("/destinations?q=Tokyo").text
    assert "Tokyo" in html
    assert 'value="HND" checked' in html
    assert 'value="NRT"' in html
    assert 'value="NRT" checked' not in html


def test_a_search_with_no_results_says_so(signed_in):
    assert "No places found" in signed_in.get("/destinations?q=zzqx").text


def test_adding_tokyo_tracks_it_and_shows_it(signed_in, clean_engine):
    r = add_tokyo(signed_in)
    assert r.status_code == 303
    assert r.headers["location"] == "/destinations"
    assert "Tokyo · 12 days away" in signed_in.get("/destinations").text
    found = tracker_for(clean_engine, "TYO")
    assert found is not None and found[1] == 12 and found[2] is True


def test_removing_a_destination(signed_in, clean_engine):
    add_tokyo(signed_in)
    tracker_id = tracker_for(clean_engine, "TYO")[0]
    r = signed_in.post(f"/destinations/{tracker_id}/remove")
    assert r.status_code == 303
    assert "Tokyo · 12 days away" not in signed_in.get("/destinations").text
    assert tracker_for(clean_engine, "TYO")[2] is False


def test_cannot_remove_someone_elses_destination(make_client, emailer, clean_engine, signed_in):
    add_tokyo(signed_in)
    tracker_id = tracker_for(clean_engine, "TYO")[0]
    other = make_client()
    sign_in(other, emailer, clean_engine, "other@example.com")
    other.post("/profile", data={**PROFILE_FORM, "tracker_dest_0": ""})
    r = other.post(f"/destinations/{tracker_id}/remove")
    assert r.status_code == 404
    assert tracker_for(clean_engine, "TYO")[2] is True


@pytest.mark.parametrize("days", ["1", "61"])
def test_bad_target_is_explained_on_the_page(signed_in, clean_engine, days):
    r = add_tokyo(signed_in, days)
    assert r.status_code == 400
    assert "between 2 and 60" in r.text
    assert tracker_for(clean_engine, "TYO") is None


def test_page_warns_when_a_target_is_shorter_than_the_trip_minimum(signed_in):
    add_tokyo(signed_in, "5")
    assert "Trips here start at 7 days away" in signed_in.get("/destinations").text


def test_a_failed_climate_lookup_still_adds_the_place(make_client, emailer, clean_engine):
    c = make_client(failing_climate)
    sign_in(c, emailer, clean_engine)
    c.post("/profile", data=PROFILE_FORM)
    assert add_tokyo(c).status_code == 303
    assert tracker_for(clean_engine, "TYO") is not None


def test_users_without_a_profile_are_sent_to_create_one(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None
    r = client.get("/destinations")
    assert r.status_code == 303
    assert r.headers["location"] == "/profile"


def test_the_dashboard_links_to_destinations(signed_in):
    assert 'href="/destinations"' in signed_in.get("/").text


def rows_created(engine):
    with session_scope(engine) as s:
        return s.scalars(select(Destination)).all(), s.scalars(select(Tracker)).all()


@pytest.mark.parametrize(
    "data",
    [
        {"code": "HND", "airports": ["JFK"], "target_days": "10"},  # a foreign airport
        {"code": "HND", "airports": ["HND", "JFK"], "target_days": "10"},
        {"code": "HND", "airports": ["NRT"], "target_days": "10"},  # the picked code is missing
        {"code": "ZZZ", "airports": ["ZZZ"], "target_days": "10"},  # an unknown code
        {"airports": ["HND"], "target_days": "10"},  # no code
        {"code": "HND", "target_days": "10"},  # no airports
    ],
)
def test_bad_posts_are_refused_and_create_nothing(signed_in, clean_engine, data):
    before_dest, before_trackers = rows_created(clean_engine)
    r = signed_in.post("/destinations", data=data)
    assert r.status_code == 400
    after_dest, after_trackers = rows_created(clean_engine)
    assert len(after_dest) == len(before_dest)
    assert len(after_trackers) == len(before_trackers)


def test_a_non_numeric_target_is_a_400_and_creates_nothing(signed_in, clean_engine):
    before = rows_created(clean_engine)
    assert add_tokyo(signed_in, "lots").status_code == 400
    after = rows_created(clean_engine)
    assert (len(after[0]), len(after[1])) == (len(before[0]), len(before[1]))


def test_re_adding_a_removed_destination_reactivates_it(signed_in, clean_engine):
    add_tokyo(signed_in)
    tracker_id = tracker_for(clean_engine, "TYO")[0]
    signed_in.post(f"/destinations/{tracker_id}/remove")
    add_tokyo(signed_in, "14")
    assert tracker_for(clean_engine, "TYO") == (tracker_id, 14, True)


def test_the_search_text_is_echoed_escaped(signed_in):
    html = signed_in.get("/destinations?q=<script>").text
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_an_orphaned_place_is_listed_and_removable(signed_in, clean_engine):
    with session_scope(clean_engine) as s:
        uid = s.scalar(select(User.id))
        s.add(Destination(code="ZQX_PT", name="Lost Place", kind="city", airports=["ZZZ"]))
        s.flush()
        s.add(
            Tracker(user_id=uid, destination_code="ZQX_PT", target_days=9, min_stay_days=6, max_stay_days=11)
        )
    html = signed_in.get("/destinations").text
    assert "Lost Place · 9 days away" in html
    tracker_id = tracker_for(clean_engine, "ZQX_PT")[0]
    assert signed_in.post(f"/destinations/{tracker_id}/remove").status_code == 303
    assert "Lost Place" not in signed_in.get("/destinations").text


def test_same_city_airports_are_prechecked(signed_in):
    html = signed_in.get("/destinations?q=Rome").text
    forms = html.split('<form class="match"')[1:]
    assert any('value="FCO" checked' in f and 'value="CIA" checked' in f for f in forms)


def test_the_trip_minimum_warning_uses_the_smallest_minimum_across_home_airports(signed_in, clean_engine):
    add_tokyo(signed_in, "5")
    assert "Trips here start at 7 days away" in signed_in.get("/destinations").text
    with session_scope(clean_engine) as s:
        s.scalar(select(User)).nearby_airports = ["HND"]  # next door to Tokyo: a short trip is fine
    assert "Trips here start" not in signed_in.get("/destinations").text
