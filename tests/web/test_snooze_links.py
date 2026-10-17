from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ptopilot.db.models import Tracker, TrackerExclusion
from ptopilot.db.session import session_scope
from ptopilot.links import Action, action_token
from tests.digest.conftest import add_tracker, add_user
from tests.web.conftest import KEY

TRIP = (date(2027, 3, 5), date(2027, 3, 14))


def tracker(engine) -> int:
    return add_tracker(engine, add_user(engine))


def test_opening_a_link_only_shows_a_confirmation(client, clean_engine):
    tid = tracker(clean_engine)
    token = action_token(KEY, Action(tid, "snooze30"))
    page = client.get(f"/s/{token}")
    assert page.status_code == 200 and "Azores: Snooze 30 days?" in page.text and "Confirm" in page.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).snoozed_until is None  # a mail scanner's GET changes nothing


def test_confirming_applies_the_action_without_signing_in(client, clean_engine):
    tid = tracker(clean_engine)
    token = action_token(KEY, Action(tid, "trip", *TRIP))
    done = client.post(f"/s/{token}")
    assert done.status_code == 200 and "Mar 5 → Mar 14 won&#39;t be suggested again" in done.text
    with session_scope(clean_engine) as s:
        rows = list(s.scalars(select(TrackerExclusion)))
        assert [(r.tracker_id, r.depart_date, r.return_date) for r in rows] == [(tid, *TRIP)]


def test_only_if_under_asks_for_a_price(client, clean_engine):
    tid = tracker(clean_engine)
    token = action_token(KEY, Action(tid, "under", *TRIP))
    assert 'name="price"' in client.get(f"/s/{token}").text
    bad = client.post(f"/s/{token}", data={"price": "cheap"})
    assert bad.status_code == 400 and "between $1 and $99,999" in bad.text
    ok = client.post(f"/s/{token}", data={"price": "$1,200"})
    assert ok.status_code == 200 and "$1,200" in ok.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).max_price == Decimal("1200")


def test_tampered_or_stale_links_are_refused(client, clean_engine):
    tid = tracker(clean_engine)
    forged = action_token("wrong-key", Action(tid, "snooze30"))
    assert client.get(f"/s/{forged}").status_code == 400
    assert client.post(f"/s/{forged}").status_code == 400
    gone = action_token(KEY, Action(9999, "snooze30"))
    response = client.get(f"/s/{gone}")
    assert response.status_code == 400 and "no longer exists" in response.text
