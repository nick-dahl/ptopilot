from datetime import timedelta

from sqlalchemy import select

from ptopilot.data import load_geo
from ptopilot.db.models import Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_candidate
from tests.digest.test_related_digest import add_check
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in

MAIN, PLACE = load_geo().destination("AZORES").name, load_geo().destination("MADEIRA").name


def setup(client, emailer, engine):
    sign_in(client, emailer, engine, "nick@example.com")
    seed_profile(engine, PROFILE_FORM, "nick@example.com")
    with session_scope(engine) as s:
        t = s.scalars(select(Tracker).order_by(Tracker.id.desc())).first()
        t.destination_code = "AZORES"
        return t.id, t.user_id


def test_destination_page_shows_the_related_panel(client, emailer, clean_engine):
    t, uid = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 900, run_date=TODAY, level="none", go_now=0)
    add_check(clean_engine, uid, t, run_date=TODAY)
    html = client.get(f"/trackers/{t}").text
    assert "<h2>Related</h2>" in html
    assert f"{PLACE} instead of {MAIN}" in html and f"36% below {MAIN}'s typical" in html
    assert "Rare" not in html


def test_no_panel_without_todays_confirmed_rows(client, emailer, clean_engine):
    t, uid = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 900, run_date=TODAY, level="none", go_now=0)
    add_check(clean_engine, uid, t, run_date=TODAY, confirmed=False)
    add_check(clean_engine, uid, t, run_date=TODAY - timedelta(days=1), airport="XXA")
    assert "Related" not in client.get(f"/trackers/{t}").text
