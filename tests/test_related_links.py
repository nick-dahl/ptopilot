"""Accepting and dismissing related places: the links, the places they create, and what is suggested."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ptopilot.core.airports import AirportCatalog
from ptopilot.data import _geo_destination, load_geo
from ptopilot.db.models import Destination, DestinationSeason, RelatedLink, Tracker
from ptopilot.destinations import add_destination
from ptopilot.related_links import accept, accepted_links, dismiss, suggestions_for
from tests.db.test_models import make_user

CAT = AirportCatalog.load()
TOKYO = json.loads(
    (Path(__file__).parent / "sources" / "fixtures" / "real_open_meteo_tokyo_2011_2020.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(autouse=True)
def _empty_tables(clean_engine):
    """Other test files commit rows; start from empty tables so make_user's email is free."""


def climate(lat, lon):
    return TOKYO


def track(session, user, place, days=10):
    return add_destination(
        session, user, CAT.search(place)[0], [CAT.search(place)[0].airport.code], days, climate=climate
    )


def tracker_count(session):
    return session.scalar(select(func.count()).select_from(Tracker))


def airports(session, user, tracker):
    rows = session.scalars(select(Destination)).all()
    geo = load_geo().with_destinations({r.code: _geo_destination(r, CAT) for r in rows})
    return [s.airport for s in suggestions_for(session, user, tracker, geo, CAT)]


def test_places_the_user_tracks_are_not_suggested(session):
    user = make_user(session)
    azores = Tracker(user_id=user.id, destination_code="AZORES", min_stay_days=5, max_stay_days=10)
    madeira = Tracker(user_id=user.id, destination_code="MADEIRA", min_stay_days=5, max_stay_days=10)
    session.add_all([azores, madeira])
    session.flush()
    out = airports(session, user, azores)
    assert "FNC" not in out and "TFS" in out
    madeira.active = False
    assert "FNC" in airports(session, user, azores)


def test_accept_creates_the_place_without_a_tracker(session):
    user = make_user(session)
    prague = track(session, user, "Prague")
    before = tracker_count(session)
    link = accept(session, user, prague.id, "BUD", climate=climate)
    assert (link.status, link.airport, link.place_code) == ("accepted", "BUD", "BUD_HU")
    place = session.get(Destination, "BUD_HU")
    assert (place.kind, place.airports, place.added_by) == ("city", ["BUD"], user.id)
    assert session.get(DestinationSeason, "BUD_HU") is not None
    assert tracker_count(session) == before
    assert accepted_links(session, user.id) == [link]
    assert "BUD" not in airports(session, user, prague)


def test_accept_uses_a_built_in_place_when_one_exists(session):
    user = make_user(session)
    madeira = Tracker(user_id=user.id, destination_code="MADEIRA", min_stay_days=5, max_stay_days=10)
    session.add(madeira)
    session.flush()
    link = accept(session, user, madeira.id, "PDL", climate=climate)
    assert link.place_code == "AZORES"
    assert session.get(Destination, "AZORES") is None


def test_dismissed_links_are_not_suggested_again(session):
    user = make_user(session)
    prague = track(session, user, "Prague")
    assert "BUD" in airports(session, user, prague)
    dismiss(session, user, prague.id, "BUD")
    assert "BUD" not in airports(session, user, prague)
    assert accepted_links(session, user.id) == []
    assert session.get(Destination, "BUD_HU") is None


def test_re_accepting_a_dismissed_link_flips_it(session):
    user = make_user(session)
    prague = track(session, user, "Prague")
    dismiss(session, user, prague.id, "BUD")
    link = accept(session, user, prague.id, "BUD", climate=climate)
    assert link.status == "accepted"
    assert session.scalar(select(func.count()).select_from(RelatedLink)) == 1
    dismiss(session, user, prague.id, "BUD")  # removes an accepted link too
    assert session.scalars(select(RelatedLink.status)).all() == ["dismissed"]


def test_another_users_tracker_is_refused(session):
    owner = make_user(session)
    other = make_user(session, email="other@example.com")
    prague = track(session, owner, "Prague")
    with pytest.raises(LookupError):
        accept(session, other, prague.id, "BUD", climate=climate)
    with pytest.raises(LookupError):
        dismiss(session, other, prague.id, "BUD")
