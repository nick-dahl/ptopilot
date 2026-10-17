from datetime import date, time
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from ptopilot.data import load_geo
from ptopilot.db.models import Invite, Tracker, TravelWindow, User
from ptopilot.profiles import apply_profile, parse_profile

GEO = load_geo()
EXAMPLE = yaml.safe_load((Path(__file__).resolve().parents[1] / "profiles" / "example.yaml").read_text())
EMAIL = "you@example.com"


def mine(model):
    """Rows belonging to the example profile's user (other tests may have committed their own users)."""
    owner = select(User.id).where(User.email == EMAIL).scalar_subquery()
    return select(model).where(model.user_id == owner)


def test_example_profile_is_valid():
    p = parse_profile(EXAMPLE, GEO)
    assert p.email == "you@example.com"
    assert p.user["pto_days_total"] - p.user["pto_committed"] == 15
    assert p.windows == [(date(2027, 3, 1), date(2027, 3, 31)), (date(2027, 10, 1), date(2027, 10, 31))]
    assert [t.destination for t in p.trackers] == ["PATAGONIA", "AZORES", "MADEIRA", "CAMINO_PORTUGUES"]
    assert p.friday_evening_min_time == time(17, 0)


def test_every_problem_is_reported_at_once():
    bad = {
        **EXAMPLE,
        "home_airport": "XXX",
        "ignored_holidays": ["Columbo Day"],
        "windows": [{"start": "2027-03-31", "end": "2027-03-01"}],
        "trackers": [
            {"destination": "ATLANTIS", "min_stay": 5, "max_stay": 9},
            {"destination": "AZORES", "min_stay": 9, "max_stay": 5},
        ],
    }
    with pytest.raises(ValueError) as exc:
        parse_profile(bad, GEO)
    message = str(exc.value)
    for fragment in ("XXX", "Columbo Day", "ends 2027-03-01 before", "ATLANTIS", "AZORES"):
        assert fragment in message


def test_missing_fields_and_typos_are_rejected():
    with pytest.raises(ValueError, match="email") as exc:
        parse_profile({"home_airprot": "JFK"}, GEO)
    assert "home_airprot" in str(exc.value)


def test_apply_creates_then_updates_idempotently(session):
    profile = parse_profile(EXAMPLE, GEO)
    assert apply_profile(session, profile) == {
        "user": "created",
        "windows": 2,
        "trackers_added": 4,
        "trackers_updated": 0,
        "trackers_deactivated": 0,
    }
    first_ids = {t.destination_code: t.id for t in session.scalars(mine(Tracker))}
    assert apply_profile(session, profile)["user"] == "updated"
    assert {t.destination_code: t.id for t in session.scalars(mine(Tracker))} == first_ids  # history kept
    assert session.scalar(select(User.ignored_holidays).where(User.email == EMAIL)) == [
        "Columbus Day",
        "Veterans Day",
    ]
    assert len(list(session.scalars(mine(TravelWindow)))) == 2
    assert session.scalar(select(Invite.email).where(Invite.email == EMAIL)) == EMAIL


def test_trackers_removed_from_the_file_are_deactivated_not_deleted(session):
    apply_profile(session, parse_profile(EXAMPLE, GEO))
    fewer = {**EXAMPLE, "trackers": EXAMPLE["trackers"][:2]}
    summary = apply_profile(session, parse_profile(fewer, GEO))
    assert summary["trackers_deactivated"] == 2
    active = {t.destination_code: t.active for t in session.scalars(mine(Tracker))}
    assert active == {"PATAGONIA": True, "AZORES": True, "MADEIRA": False, "CAMINO_PORTUGUES": False}
