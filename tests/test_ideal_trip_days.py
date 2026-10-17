"""The optional preferred trip length: profile YAML, database column, and the profile form."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ptopilot.data import load_geo
from ptopilot.db.models import User
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.web.forms import form_to_profile, profile_to_form
from tests.web.conftest import PROFILE_FORM

GEO = load_geo()
EXAMPLE = yaml.safe_load((Path(__file__).resolve().parents[1] / "profiles" / "example.yaml").read_text())


def test_ideal_trip_days_is_optional_and_defaults_to_none():
    data = {k: v for k, v in EXAMPLE.items() if k != "ideal_trip_days"}
    assert parse_profile(data, GEO).user["ideal_trip_days"] is None


def test_example_profile_sets_an_ideal_length():
    assert parse_profile(EXAMPLE, GEO).user["ideal_trip_days"] == 10


@pytest.mark.parametrize("bad", [6, 17, "ten", True])
def test_ideal_trip_days_must_be_a_whole_number_between_min_and_max(bad):
    data = {**EXAMPLE, "min_trip_days": 7, "max_trip_days": 16, "ideal_trip_days": bad}
    with pytest.raises(ValueError, match="ideal_trip_days: "):
        parse_profile(data, GEO)


def test_loading_a_profile_without_an_ideal_clears_a_stored_one(session):
    apply_profile(session, parse_profile(EXAMPLE, GEO))
    data = {k: v for k, v in EXAMPLE.items() if k != "ideal_trip_days"}
    apply_profile(session, parse_profile(data, GEO))
    assert session.scalar(select(User.ideal_trip_days).where(User.email == EXAMPLE["email"])) is None


def test_database_rejects_an_ideal_outside_the_trip_range(session):
    session.add(
        User(
            email="x@example.com",
            home_airport="JFK",
            country="US",
            holiday_calendar="US",
            pto_days_total=10,
            min_trip_days=7,
            max_trip_days=16,
            ideal_trip_days=20,
        )
    )
    with pytest.raises(IntegrityError, match="ideal_trip_days"):
        session.flush()


def test_form_blank_means_no_preference_and_a_number_is_kept():
    blank = form_to_profile({**PROFILE_FORM, "ideal_trip_days": ""}, "a@example.com")
    assert blank.get("ideal_trip_days") is None
    ten = form_to_profile({**PROFILE_FORM, "ideal_trip_days": "10"}, "a@example.com")
    assert ten["ideal_trip_days"] == 10


def test_form_shows_the_stored_ideal_or_blank(session):
    apply_profile(session, parse_profile(EXAMPLE, GEO))
    user = session.scalar(select(User).where(User.email == EXAMPLE["email"]))
    assert profile_to_form(session, user)["ideal_trip_days"] == "10"
    user.ideal_trip_days = None
    assert profile_to_form(session, user)["ideal_trip_days"] == ""
    assert profile_to_form(session, None)["ideal_trip_days"] == ""
