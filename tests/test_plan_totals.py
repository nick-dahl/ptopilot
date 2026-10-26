"""A planning year's totals: booked trips at their real PTO, planned trips at an estimate."""

from datetime import date

import pytest

from ptopilot import plan_totals, planning
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import PlannedTrip, PlanningYear, Tracker
from tests.db.test_models import make_user

YEAR = 2027


@pytest.fixture(autouse=True)
def _empty_tables(clean_engine):
    """Other test files commit rows; start from empty tables so the user's email is free."""


def trip(s, user, code, year=YEAR, priority=2):
    t = Tracker(
        user_id=user.id,
        destination_code=code,
        min_stay_days=7,
        max_stay_days=11,
        target_days=9,
        priority=priority,
    )
    s.add(t)
    s.flush()
    s.add(PlannedTrip(user_id=user.id, year=year, tracker_id=t.id))
    s.flush()
    return t


def test_year_totals_counts_booked_and_planned(session, monkeypatch):
    user = make_user(session)
    session.add(PlanningYear(user_id=user.id, year=YEAR, pto_days=15, other_time_off=0))
    booked = trip(session, user, "LIS")
    trip(session, user, "AZORES")
    trip(session, user, "MADEIRA")
    geo = load_geo()
    planning.book_trip(
        session, user, booked.id, YEAR, date(2027, 5, 28), date(2027, 6, 5), pto_cost=5, geo=geo
    )
    estimates = {"AZORES": 6, "MADEIRA": 9}
    monkeypatch.setattr(
        "ptopilot.plan_totals.estimate_pto", lambda profile, spec, *a, **k: estimates[spec.destination_code]
    )
    totals = plan_totals.year_totals(session, user, YEAR, geo, load_seasons())
    assert (totals.booked, totals.planned) == (5, 15)
    assert (totals.available, totals.remaining, totals.left) == (15, 10, -5)
    assert plan_totals.year_totals(session, user, 2030, geo, load_seasons()) is None


def test_trip_estimates_skip_booked_trips(session, monkeypatch):
    user = make_user(session)
    session.add(PlanningYear(user_id=user.id, year=YEAR, pto_days=15, other_time_off=0))
    booked = trip(session, user, "LIS")
    other = trip(session, user, "AZORES")
    geo = load_geo()
    planning.book_trip(session, user, booked.id, YEAR, date(2027, 5, 28), date(2027, 6, 5), geo=geo)
    monkeypatch.setattr("ptopilot.plan_totals.estimate_pto", lambda *a, **k: 4)
    got = plan_totals.trip_estimates(session, user, YEAR, geo, load_seasons())
    assert got == {other.id: 4}


def test_remaining_by_year_subtracts_booked_pto_and_omits_unplanned_years(session):
    user = make_user(session)
    session.add(PlanningYear(user_id=user.id, year=YEAR, pto_days=20, other_time_off=3))
    session.add(PlanningYear(user_id=user.id, year=2028, pto_days=10, other_time_off=0))
    t = trip(session, user, "LIS")
    planning.book_trip(
        session, user, t.id, YEAR, date(2027, 5, 28), date(2027, 6, 5), pto_cost=5, geo=load_geo()
    )
    assert plan_totals.remaining_by_year(session, user, [YEAR, 2028, 2030]) == {YEAR: 12, 2028: 10}
