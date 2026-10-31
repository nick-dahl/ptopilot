"""Behaviour that matters because the app is public: revoked access, link floods, odd input."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.digest.send import deliver
from ptopilot.links import Action, action_token
from ptopilot.settings import Settings
from ptopilot.web.app import create_app
from tests.digest.conftest import add_candidate, add_tracker, add_user
from tests.web.conftest import (
    KEY,
    PROFILE_FORM,
    TODAY,
    CapturingEmailer,
    invite,
    is_landing,
    seed_profile,
    sign_in,
)


def test_dashboard_still_shows_deals_after_they_were_emailed(client, emailer, clean_engine):
    from ptopilot.data import load_geo, load_seasons
    from ptopilot.digest.select import build_digests

    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    add_candidate(clean_engine, tracker_id, 700, level="good", go_now=90, run_date=TODAY)
    add_candidate(clean_engine, tracker_id, 603, level="good", go_now=40, run_date=TODAY,
                  depart=TODAY.replace(day=12), ret=TODAY.replace(day=21))  # fmt: skip
    digests = build_digests(clean_engine, load_geo(), load_seasons(), TODAY)
    deliver(clean_engine, digests, TODAY, emailer=CapturingEmailer())  # both deals now count as "sent"
    page = client.get("/").text
    assert "$603" in page  # the destination's best trip, although it was emailed already


def test_removing_an_invite_ends_the_session(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    assert is_landing(client.get("/"))
    assert client.get("/profile").headers["location"] == "/"


def test_a_removed_traveler_cannot_recreate_themselves(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    response = client.post("/profile", data=PROFILE_FORM)
    assert response.headers["location"] == "/"
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None and s.scalar(select(Invite)) is None


def test_a_sign_in_link_for_a_revoked_invite_does_not_work(client, emailer, clean_engine):
    invite(clean_engine, "nick@example.com")
    client.post("/login", data={"email": "nick@example.com"})
    link = emailer.last_link().replace("http://testserver", "")
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    assert client.get(link).status_code == 400


def test_sign_in_links_are_rate_limited_per_address(clean_engine):
    clock = {"t": 1000.0}
    emailer = CapturingEmailer()
    settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
    app = create_app(
        settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY, now=lambda: clock["t"]
    )
    invite(clean_engine, "nick@example.com")
    with TestClient(app, follow_redirects=False) as c:
        for _ in range(5):
            assert "If that address is invited" in c.post("/login", data={"email": "nick@example.com"}).text
        assert len(emailer.sent) == 1
        clock["t"] += 121
        c.post("/login", data={"email": "nick@example.com"})
        assert len(emailer.sent) == 2


@pytest.mark.parametrize("price", ["NaN", "sNaN", "Infinity", "-5", "1e20", "1e999999999", "0"])
def test_only_if_under_rejects_odd_prices_with_a_message(client, clean_engine, price):
    tid = add_tracker(clean_engine, add_user(clean_engine))
    token = action_token(KEY, Action(tid, "under"))
    response = client.post(f"/s/{token}", data={"price": price})
    assert response.status_code == 400 and "between $1 and $99,999" in response.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).max_price is None


def test_unknown_paths_get_the_styled_not_found_page(client):
    page = client.get("/foo")
    assert page.status_code == 404 and "text/html" in page.headers["content-type"]
    assert 'href="/static/app.css?v=' in page.text and "Not found" in page.text
    assert client.get("/healthz").json() == {"ok": True}
