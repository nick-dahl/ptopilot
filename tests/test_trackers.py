from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from ptopilot.db.models import Tracker, TrackerExclusion, User
from ptopilot.links import Action
from ptopilot.trackers import apply_action

TODAY = date(2026, 10, 20)


@pytest.fixture
def tracker(session):
    user = User(
        email="t@example.com",
        home_airport="JFK",
        country="US",
        holiday_calendar="US",
        pto_days_total=15,
        max_trip_days=16,
    )
    session.add(user)
    session.flush()
    t = Tracker(user_id=user.id, destination_code="AZORES", min_stay_days=7, max_stay_days=10)
    session.add(t)
    session.flush()
    return t


def test_not_this_trip_adds_an_exclusion_once(session, tracker):
    action = Action(tracker.id, "trip", date(2027, 3, 5), date(2027, 3, 14))
    apply_action(session, tracker, action, TODAY)
    message = apply_action(session, tracker, action, TODAY)  # clicking twice is harmless
    rows = list(session.scalars(select(TrackerExclusion).where(TrackerExclusion.tracker_id == tracker.id)))
    assert [(r.depart_date, r.return_date) for r in rows] == [(date(2027, 3, 5), date(2027, 3, 14))]
    assert "Mar 5 → Mar 14" in message


def test_snooze_30_days_and_not_this_year(session, tracker):
    apply_action(session, tracker, Action(tracker.id, "snooze30"), TODAY)
    assert tracker.snoozed_until == date(2026, 11, 19)
    apply_action(session, tracker, Action(tracker.id, "year", date(2027, 3, 5), date(2027, 3, 14)), TODAY)
    assert tracker.snoozed_until == date(2027, 12, 31)  # the trip's year, not today's


def test_only_if_under_sets_max_price(session, tracker):
    message = apply_action(session, tracker, Action(tracker.id, "under"), TODAY, price=Decimal("750"))
    assert tracker.max_price == Decimal("750") and "$750" in message
    with pytest.raises(ValueError, match="above zero"):
        apply_action(session, tracker, Action(tracker.id, "under"), TODAY, price=Decimal("0"))


def test_trip_action_needs_dates(session, tracker):
    with pytest.raises(ValueError, match="no trip"):
        apply_action(session, tracker, Action(tracker.id, "trip"), TODAY)
