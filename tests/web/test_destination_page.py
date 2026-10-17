"""The destination page: every date option from the latest scan, and the cheapest fare over 30 days."""

from datetime import timedelta

from sqlalchemy import select

from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, sign_in

CAMINO = {**PROFILE_FORM, "tracker_dest_0": "CAMINO_PORTUGUES", "tracker_min_0": "11", "tracker_max_0": "14"}


def setup(client, emailer, engine, form=PROFILE_FORM, email="nick@example.com") -> int:
    sign_in(client, emailer, engine, email)
    client.post("/profile", data=form)
    with session_scope(engine) as s:
        return s.scalar(select(Tracker.id).order_by(Tracker.id.desc()))


def test_lists_every_trip_from_the_latest_scan_cheapest_first(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    later = {"depart": TODAY.replace(day=12), "ret": TODAY.replace(day=21)}
    add_candidate(clean_engine, t, 700, run_date=TODAY, **later)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    add_baseline(clean_engine, 700)
    page = client.get(f"/trackers/{t}")
    assert page.status_code == 200
    text = page.text
    assert "<h1>Azores</h1>" in text and "7–10 days on the ground" in text
    assert text.index("$603") < text.index("$700")
    assert "Fri Mar 5 → Sun Mar 14" in text and "Tap Air Portugal · 1 stop" in text
    assert 'href="https://www.google.com/travel/flights/search?tfs=X"' in text and "View flights" in text
    assert "14% below typical" in text


def test_open_jaw_trips_say_where_they_fly_home_from(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine, CAMINO)
    add_candidate(clean_engine, t, 852, run_date=TODAY, dest="OPO", return_airport="SCQ")
    assert "into OPO · home from SCQ" in client.get(f"/trackers/{t}").text


def test_excluded_trips_stay_visible_but_dimmed(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 603, run_date=TODAY)
    with session_scope(clean_engine) as s:
        s.get(Candidate, c).state = "excluded"
    assert '<tr class="dimmed">' in client.get(f"/trackers/{t}").text


def test_trend_needs_a_few_scans_before_it_draws(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    page = client.get(f"/trackers/{t}").text
    assert "Price history fills in after a few daily scans" in page and "<svg" not in page
    for days_ago, price in [(1, 640), (2, 660)]:
        add_candidate(clean_engine, t, price, run_date=TODAY - timedelta(days=days_ago))
    page = client.get(f"/trackers/{t}").text
    assert 'class="trend"' in page and "Cheapest fare, last 30 days" in page
    assert "Tue Mar 2" in page and "Thu Mar 4" in page  # first and last scan days


def test_no_scan_yet_says_so(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert "First prices after the next daily scan" in client.get(f"/trackers/{t}").text


def test_snooze_from_the_destination_page(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert f'action="/trackers/{t}/snooze"' in client.get(f"/trackers/{t}").text
    client.post(f"/trackers/{t}/snooze", data={"days": "30"})
    assert f'action="/trackers/{t}/unsnooze"' in client.get(f"/trackers/{t}").text


def test_someone_elses_or_a_missing_tracker_is_not_found(client, emailer, clean_engine):
    theirs = setup(client, emailer, clean_engine, email="owner@example.com")
    client.post("/logout")
    setup(client, emailer, clean_engine, email="intruder@example.com")
    assert client.get(f"/trackers/{theirs}").status_code == 404
    assert client.get("/trackers/999999").status_code == 404


def test_signed_out_visitors_go_home(client):
    response = client.get("/trackers/1")
    assert (response.status_code, response.headers["location"]) == (303, "/")
