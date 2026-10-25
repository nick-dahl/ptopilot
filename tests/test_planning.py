"""Planning years: starting one, open ranges, planned trips, targets, and the target conversion."""

from datetime import date

import pytest
from sqlalchemy import select

from ptopilot import planning
from ptopilot.data import load_geo
from ptopilot.db.models import PlannedTrip, Tracker, TravelWindow
from tests.db.test_models import make_user

TODAY = date(2026, 10, 25)


@pytest.fixture(autouse=True)
def _empty_tables(clean_engine):
    """Other test files commit rows; start from empty tables so the user's email is free."""


def make_tracker(s, user, code="LIS", **kw):
    t = Tracker(user_id=user.id, destination_code=code, min_stay_days=7, max_stay_days=11, **kw)
    s.add(t)
    s.flush()
    return t


def test_set_ranges_merges_overlaps_and_touching(session):
    user = make_user(session)
    session.add(TravelWindow(user_id=user.id, start_date=date(2028, 1, 1), end_date=date(2028, 1, 5)))
    saved = planning.set_ranges(
        session,
        user,
        2027,
        [
            (date(2027, 3, 10), date(2027, 3, 20)),
            (date(2027, 3, 1), date(2027, 3, 9)),
            (date(2027, 8, 1), date(2027, 8, 3)),
        ],
    )
    assert saved == [(date(2027, 3, 1), date(2027, 3, 20)), (date(2027, 8, 1), date(2027, 8, 3))]
    assert planning.year_ranges(session, user, 2027) == saved
    assert planning.year_ranges(session, user, 2028) == [(date(2028, 1, 1), date(2028, 1, 5))]
    planning.set_ranges(session, user, 2027, [])
    assert planning.year_ranges(session, user, 2027) == []
    assert planning.year_ranges(session, user, 2028) != []


def test_set_ranges_rejects_a_range_outside_the_year(session):
    user = make_user(session)
    with pytest.raises(ValueError, match="range 1"):
        planning.set_ranges(session, user, 2027, [(date(2028, 1, 1), date(2028, 1, 5))])
    with pytest.raises(ValueError, match="range 2"):
        planning.set_ranges(
            session,
            user,
            2027,
            [(date(2027, 1, 1), date(2027, 1, 5)), (date(2027, 2, 5), date(2027, 2, 1))],
        )


def test_starting_a_year_twice_is_a_no_op(session):
    user = make_user(session)
    first = planning.start_year(session, user, 2027, 20, 3, [], today=TODAY)
    again = planning.start_year(session, user, 2027, 5, 0, [], today=TODAY)
    assert again is first
    assert (again.pto_days, again.other_time_off) == (20, 3)
    assert len(planning.planning_years(session, user)) == 1


def test_start_year_carries_only_the_users_active_trackers(session):
    user = make_user(session)
    stranger = make_user(session, email="other@example.com")
    mine = make_tracker(session, user, "LIS")
    inactive = make_tracker(session, user, "TYO", active=False)
    theirs = make_tracker(session, stranger, "LIS")
    planning.start_year(session, user, 2027, 20, 0, [mine.id, inactive.id, theirs.id], today=TODAY)
    assert [t.id for t in planning.year_trackers(session, user, 2027)] == [mine.id]
    assert session.scalars(select(PlannedTrip).where(PlannedTrip.user_id == stranger.id)).all() == []


def test_start_year_rejects_years_out_of_reach_and_bad_pto(session):
    user = make_user(session)
    for year in (2025, 2026 + 5):
        with pytest.raises(ValueError):
            planning.start_year(session, user, year, 20, 0, [], today=TODAY)
    for pto, other in ((-1, 0), (20, 21), (20, -1), (1000, 0)):
        with pytest.raises(ValueError):
            planning.start_year(session, user, 2027, pto, other, [], today=TODAY)
    assert planning.planning_years(session, user) == []
    planning.start_year(session, user, 2026, 20, 0, [], today=TODAY)
    with pytest.raises(ValueError):
        planning.set_year_pto(session, user, 2026, 5, 6)
    planning.set_year_pto(session, user, 2026, 25, 4)
    assert planning.current_year(session, user, TODAY).pto_days == 25


def test_default_new_year(session):
    user = make_user(session)
    assert planning.default_new_year(session, user, date(2026, 10, 1)) == 2027
    assert planning.default_new_year(session, user, date(2026, 6, 1)) == 2026
    planning.start_year(session, user, 2027, 20, 0, [], today=TODAY)
    assert planning.default_new_year(session, user, date(2026, 6, 1)) == 2028


def test_current_year_is_the_earliest_not_past(session):
    user = make_user(session)
    planning.start_year(session, user, 2026, 20, 0, [], today=TODAY)
    planning.start_year(session, user, 2027, 20, 0, [], today=TODAY)
    assert planning.current_year(session, user, date(2026, 12, 1)).year == 2026
    assert planning.current_year(session, user, date(2027, 1, 2)).year == 2027
    assert planning.current_year(session, user, date(2028, 1, 2)) is None


def test_unplanning_the_last_year_deactivates_the_tracker(session):
    user = make_user(session)
    t = make_tracker(session, user)
    planning.plan_trip(session, user, t, 2027)
    planning.plan_trip(session, user, t, 2027)  # idempotent
    assert planning.unplan_trip(session, user, t.id, 2027, today=TODAY) is True
    assert t.active is False
    assert planning.year_trackers(session, user, 2027) == []


def test_unplanning_one_of_two_years_keeps_tracking(session):
    user = make_user(session)
    t = make_tracker(session, user)
    planning.plan_trip(session, user, t, 2027)
    planning.plan_trip(session, user, t, 2028)
    assert planning.unplan_trip(session, user, t.id, 2027, today=TODAY) is True
    assert t.active is True
    assert [x.id for x in planning.year_trackers(session, user, 2028)] == [t.id]


def test_unplan_refuses_another_users_tracker(session):
    user = make_user(session)
    stranger = make_user(session, email="other@example.com")
    t = make_tracker(session, stranger)
    planning.plan_trip(session, stranger, t, 2027)
    assert planning.unplan_trip(session, user, t.id, 2027, today=TODAY) is False
    assert t.active is True


def test_year_trackers_are_ordered_by_priority_then_id(session):
    user = make_user(session)
    a = make_tracker(session, user, "LIS", priority=3)
    b = make_tracker(session, user, "TYO", priority=1)
    c = make_tracker(session, user, "TH", priority=1)
    for t in (a, b, c):
        planning.plan_trip(session, user, t, 2027)
    assert [t.id for t in planning.year_trackers(session, user, 2027)] == [b.id, c.id, a.id]


def test_set_target_updates_target_and_stay(session):
    user = make_user(session)
    t = make_tracker(session, user)
    assert planning.set_target(session, user, t.id, 12) is True
    assert (t.target_days, t.min_stay_days, t.max_stay_days) == (12, 9, 14)
    for bad in (1, 61):
        with pytest.raises(ValueError):
            planning.set_target(session, user, t.id, bad)
    stranger = make_user(session, email="other@example.com")
    assert planning.set_target(session, stranger, t.id, 10) is False


def test_convert_targets_sets_the_midpoint_of_days_away(session):
    user = make_user(session)  # home ORD; Lisbon is 2 days of overhead away
    todo = make_tracker(session, user, "LIS")
    done = make_tracker(session, user, "TYO", target_days=5)
    unknown = make_tracker(session, user, "NOWHERE")
    assert planning.convert_targets(session, load_geo()) == 1
    assert todo.target_days == 11  # floor((7 + 11) / 2 + 2.0 + 0.5)
    assert done.target_days == 5
    assert unknown.target_days is None
