"""The destinations page's related places: suggestions, accept, dismiss and remove."""

from sqlalchemy import select

from ptopilot.db.models import DestinationSeason, RelatedLink
from ptopilot.db.session import session_scope
from tests.web import test_destinations_page as base
from tests.web.conftest import PROFILE_FORM, sign_in

add_tokyo, failing_climate, tracker_for = base.add_tokyo, base.failing_climate, base.tracker_for
make_client, signed_in = base.make_client, base.signed_in  # the page tests' fixtures


def add_prague(c):
    return c.post("/destinations", data={"code": "PRG", "airports": ["PRG"], "target_days": "10"})


def statuses(engine):
    with session_scope(engine) as s:
        return [
            (link.airport, link.status) for link in s.scalars(select(RelatedLink).order_by(RelatedLink.id))
        ]


def test_the_page_lists_suggestions_and_accepted_places(signed_in, clean_engine):
    add_prague(signed_in)
    tid = tracker_for(clean_engine, "PRG_CZ")[0]
    html = signed_in.get("/destinations").text
    assert "Budapest" in html and "Central European capitals" in html
    assert f'action="/destinations/{tid}/related"' in html
    r = signed_in.post(f"/destinations/{tid}/related", data={"airport": "BUD", "action": "accept"})
    assert (r.status_code, r.headers["location"]) == (303, "/destinations")
    html = signed_in.get("/destinations").text
    assert statuses(clean_engine) == [("BUD", "accepted")]
    assert "Remove" in html and "Budapest" in html
    assert 'value="BUD"' in html  # the Remove form
    signed_in.post(f"/destinations/{tid}/related", data={"airport": "VIE", "action": "dismiss"})
    assert "Vienna" not in signed_in.get("/destinations").text


def test_a_failed_climate_lookup_is_retried_on_view(make_client, emailer, clean_engine):
    c = make_client(failing_climate)
    sign_in(c, emailer, clean_engine)
    c.post("/profile", data=PROFILE_FORM)
    add_tokyo(c)
    add_prague(c)
    tid = tracker_for(clean_engine, "PRG_CZ")[0]
    c.post(f"/destinations/{tid}/related", data={"airport": "BUD", "action": "accept"})
    with session_scope(clean_engine) as s:
        assert s.get(DestinationSeason, "BUD_HU") is None
    working = make_client()
    sign_in(working, emailer, clean_engine)
    assert working.get("/destinations").status_code == 200
    with session_scope(clean_engine) as s:
        assert s.get(DestinationSeason, "BUD_HU") is not None


def test_only_one_missing_climate_is_retried_per_view(make_client, emailer, clean_engine):
    c = make_client(failing_climate)
    sign_in(c, emailer, clean_engine)
    c.post("/profile", data=PROFILE_FORM)
    add_tokyo(c)
    add_prague(c)
    tid = tracker_for(clean_engine, "PRG_CZ")[0]
    for airport in ("BUD", "VIE"):
        c.post(f"/destinations/{tid}/related", data={"airport": airport, "action": "accept"})
    lookups = []

    def counting(lat, lon):
        lookups.append((lat, lon))
        return base.fake_climate(lat, lon)

    working = make_client(counting)
    sign_in(working, emailer, clean_engine)
    assert working.get("/destinations").status_code == 200
    assert len(lookups) == 1
    assert working.get("/destinations").status_code == 200
    assert len(lookups) == 2
    working.get("/destinations")
    assert len(lookups) == 2  # nothing left to retry


def test_another_users_tracker_gets_404(make_client, emailer, clean_engine, signed_in):
    add_prague(signed_in)
    tid = tracker_for(clean_engine, "PRG_CZ")[0]
    other = make_client()
    sign_in(other, emailer, clean_engine, "other@example.com")
    assert other.post("/profile", data=PROFILE_FORM).status_code == 303
    r = other.post(f"/destinations/{tid}/related", data={"airport": "BUD", "action": "accept"})
    assert r.status_code == 404
    assert statuses(clean_engine) == []


def test_signed_out_and_bad_input(client, signed_in, clean_engine):
    add_prague(signed_in)
    tid = tracker_for(clean_engine, "PRG_CZ")[0]
    assert (
        client.post(f"/destinations/{tid}/related", data={"airport": "BUD", "action": "accept"}).status_code
        == 303
    )
    assert (
        signed_in.post(f"/destinations/{tid}/related", data={"airport": "BUD", "action": "nope"}).status_code
        == 400
    )
    assert (
        signed_in.post(
            f"/destinations/{tid}/related", data={"airport": "QQQ", "action": "accept"}
        ).status_code
        == 400
    )
    assert statuses(clean_engine) == []
