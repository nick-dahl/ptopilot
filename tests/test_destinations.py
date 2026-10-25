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


def add_orphan(engine, code="ZQX_PT", airports=("ZZZ",)):
    with Session(engine) as s:
        s.add(Destination(code=code, name="Lost Place", kind="city", airports=list(airports)))
        s.commit()


def test_a_place_whose_airports_left_the_catalog_still_loads(committed_engine):
    add_orphan(committed_engine)
    dest = load_geo(committed_engine).destination("ZQX_PT")
    assert (dest.name, dest.country, dest.zone) == ("Lost Place", "PT", "OTHER")
    assert load_geo(committed_engine).travel_rule("JFK", dest).min_trip_days >= 2  # default rule


def test_a_place_keeps_the_airports_the_catalog_still_has(committed_engine):
    add_orphan(committed_engine, "ITM_JP", ("ZZZ", "KIX"))
    dest = load_geo(committed_engine).destination("ITM_JP")
    assert (dest.country, dest.zone) == ("JP", "E_ASIA")


def test_digests_still_build_for_every_user_with_an_orphaned_place(committed_engine):
    from datetime import date

    from ptopilot.digest.select import build_digests
    from tests.digest.conftest import RUN, add_candidate, add_tracker, add_user

    add_orphan(committed_engine)
    t1 = add_tracker(committed_engine, add_user(committed_engine), code="ZQX_PT")
    add_candidate(committed_engine, t1, 600, dest="ZZZ")
    t2 = add_tracker(committed_engine, add_user(committed_engine, "b@example.com"))
    add_candidate(committed_engine, t2, 600, depart=date(2027, 3, 5))
    build_digests(committed_engine, load_geo(committed_engine), load_seasons(committed_engine), RUN)


def test_geo_yaml_wins_over_a_database_place_with_the_same_code(committed_engine):
    add_orphan(committed_engine, "AZORES", ("KIX",))
    assert load_geo(committed_engine).destination("AZORES").airports == ("PDL",)


def test_seasons_yaml_wins_over_a_database_season_with_the_same_code(committed_engine):
    add_orphan(committed_engine, "AZORES", ("KIX",))
    with Session(committed_engine) as s:
        s.add(DestinationSeason(code="AZORES", months=["avoid"] * 12, notes={}, source="open-meteo"))
        s.commit()
    assert load_seasons(committed_engine).rating(("AZORES",), 7) == load_seasons().rating(("AZORES",), 7)
    assert load_seasons().rating(("AZORES",), 7) != "avoid"


def test_a_malformed_season_row_is_skipped(committed_engine):
    add_orphan(committed_engine, "BAD_XX")
    add_orphan(committed_engine, "OK_XX")
    with Session(committed_engine) as s:
        s.add(DestinationSeason(code="BAD_XX", months=["good"] * 5, notes={}, source="open-meteo"))
        s.add(DestinationSeason(code="OK_XX", months=["good"] * 12, notes={}, source="open-meteo"))
        s.commit()
    table = load_seasons(committed_engine)
    assert "BAD_XX" not in table.ratings and "OK_XX" in table.ratings


def test_any_error_from_the_climate_lookup_still_adds_the_place(session):
    def broken(lat, lon):
        raise ValueError("bad payload")

    t = add_destination(session, make_user(session), CAT.search("Bermuda")[0], ["BDA"], 5, climate=broken)
    assert t.active and session.get(DestinationSeason, t.destination_code) is None


def test_prefetched_climate_is_looked_up_once_before_the_add(session):
    from ptopilot.destinations import prefetch_climate

    calls = []

    def counting(lat, lon):
        calls.append((lat, lon))
        return TOKYO

    osaka = CAT.search("Osaka")[0]
    fetched = prefetch_climate(session, osaka, ["KIX", "ITM"], counting)
    assert len(calls) == 1
    add_destination(session, make_user(session), osaka, ["KIX", "ITM"], 12, climate=fetched)
    assert len(calls) == 1 and session.get(DestinationSeason, "KIX_JP") is not None
    # nothing to fetch for a built-in place
    assert prefetch_climate(session, CAT.search("Tokyo")[0], ["HND", "NRT"], fail_if_called)


def test_the_climate_fetch_uses_a_ten_second_timeout(monkeypatch):
    import httpx

    from ptopilot import config
    from ptopilot.sources import climate

    seen = {}

    class Boom(Exception):
        pass

    class FakeClient:
        def __init__(self, timeout):
            seen["timeout"] = timeout
            raise Boom

    monkeypatch.setattr(climate.httpx, "Client", FakeClient)
    with pytest.raises(Boom):
        climate.fetch_climate(0.0, 0.0)
    assert seen["timeout"] == config.CLIMATE_TIMEOUT_S == 10
    assert httpx  # imported for the patched module
