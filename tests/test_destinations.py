"""User-added destinations: stored in the database, merged into geo and seasons, added and removed."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ptopilot.core.airports import AirportCatalog
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Base, Destination, DestinationSeason, Tracker
from ptopilot.destinations import add_destination, remove_destination
from ptopilot.sources.base import SourceUnavailable
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


def tokyo_climate(lat, lon):
    return TOKYO


def fail_if_called(lat, lon):
    raise AssertionError("the climate service should not be called")


def raising(lat, lon):
    raise SourceUnavailable("open-meteo: down")


def test_adding_osaka_creates_the_place_its_seasons_and_a_tracker(session):
    user = make_user(session)
    t = add_destination(session, user, CAT.search("Osaka")[0], ["KIX", "ITM"], 12, climate=tokyo_climate)
    assert (t.destination_code, t.target_days, t.active) == ("KIX_JP", 12, True)
    d = session.get(Destination, "KIX_JP")
    assert (d.name, d.airports, d.added_by) == ("Osaka", ["KIX", "ITM"], user.id)
    assert session.get(DestinationSeason, "KIX_JP").months[0] == "avoid"


@pytest.fixture
def committed_engine(clean_engine):
    """Like clean_engine, but empties the tables again afterwards: the test commits real rows."""
    yield clean_engine
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with clean_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def test_added_places_load_into_geo_and_seasons(committed_engine):
    clean_engine = committed_engine
    with Session(clean_engine) as s:
        user = make_user(s)
        add_destination(s, user, CAT.search("Osaka")[0], ["KIX", "ITM"], 12, climate=tokyo_climate)
        s.commit()
    dest = load_geo(clean_engine).destination("KIX_JP")
    assert dest.airports == ("KIX", "ITM")
    assert (dest.country, dest.zone) == ("JP", "E_ASIA")
    assert load_seasons(clean_engine).rating(("KIX_JP", "JP"), 5) == "good"
    assert load_geo().destination("AZORES").airports == ("PDL",)  # built-ins stay


def test_adding_tokyo_reuses_the_built_in_code(session):
    # geo.yaml's TYO already covers exactly HND + NRT, so no database place or climate lookup is needed.
    t = add_destination(
        session, make_user(session), CAT.search("Tokyo")[0], ["HND", "NRT"], 12, climate=fail_if_called
    )
    assert t.destination_code == "TYO"


def test_adding_a_built_in_place_reuses_its_code(session):
    t = add_destination(
        session, make_user(session), CAT.search("Ponta Delgada")[0], ["PDL"], 9, climate=fail_if_called
    )
    assert t.destination_code == "AZORES"  # geo.yaml's code; no climate call, seasons.yaml applies
    assert session.get(Destination, "AZORES") is None


def test_re_adding_reactivates_the_same_tracker(session):
    user = make_user(session)
    first = add_destination(session, user, CAT.search("Osaka")[0], ["KIX"], 12, climate=tokyo_climate)
    assert remove_destination(session, user, first.id) and not first.active
    again = add_destination(session, user, CAT.search("Osaka")[0], ["KIX"], 14, climate=fail_if_called)
    assert again.id == first.id and again.active and again.target_days == 14


def test_adding_works_when_climate_lookup_fails(session):
    t = add_destination(session, make_user(session), CAT.search("Bermuda")[0], ["BDA"], 5, climate=raising)
    assert t.active and session.get(DestinationSeason, t.destination_code) is None


def test_removing_someone_elses_or_a_missing_tracker_does_nothing(session):
    user = make_user(session)
    other = make_user(session, email="other@example.com")
    t = add_destination(session, user, CAT.search("Osaka")[0], ["KIX"], 12, climate=tokyo_climate)
    assert remove_destination(session, other, t.id) is False
    assert t.active is True
    assert remove_destination(session, user, 999_999) is False


@pytest.mark.parametrize("bad", [1, 61])
def test_target_days_must_be_between_2_and_60(session, bad):
    user = make_user(session)
    session.add(
        Tracker(user_id=user.id, destination_code="AZORES", min_stay_days=1, max_stay_days=5, target_days=bad)
    )
    with pytest.raises(IntegrityError):
        session.flush()
