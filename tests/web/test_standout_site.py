from sqlalchemy import select

from ptopilot.db.models import Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate, set_verdict
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in


def setup(client, emailer, engine) -> int:
    sign_in(client, emailer, engine, "nick@example.com")
    seed_profile(engine, PROFILE_FORM, "nick@example.com")
    with session_scope(engine) as s:
        return s.scalar(select(Tracker.id).order_by(Tracker.id.desc()))


def test_site_shows_duration_and_the_standout_tag(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_baseline(clean_engine, 700)
    add_candidate(clean_engine, t, 603, run_date=TODAY, level="great", go_now=92, expected_days=2)
    later = {"depart": TODAY.replace(day=12), "ret": TODAY.replace(day=21)}
    add_candidate(clean_engine, t, 650, run_date=TODAY, level="good", go_now=60, expected_days=6, **later)
    dash = client.get("/").text
    assert "Rare: likely gone within ~2 days" in dash and "dest-card standout" in dash
    page = client.get(f"/trackers/{t}").text
    assert page.count("Rare: likely gone within ~2 days") == 1
    assert "likely gone within ~6 days" in page and '<tr class="standout">' in page


def test_ruled_out_rows_never_get_the_standout_tag(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 603, run_date=TODAY, level="great", go_now=92, expected_days=2)
    set_verdict(clean_engine, c, "ruled_out", "overnight layover")
    page = client.get(f"/trackers/{t}").text
    assert "Rare:" not in page and "standout" not in page
