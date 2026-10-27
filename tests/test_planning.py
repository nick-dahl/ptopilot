"""Planning years: starting one, open ranges, planned trips, targets, and the target conversion."""

import threading
import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot import planning
from ptopilot.data import load_geo
from ptopilot.db.models import (
    Candidate,
    PlannedTrip,
    PlanningYear,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    TravelWindow,
    User,
)
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


def test_set_ranges_rejects_an_end_far_beyond_the_year(session):
    user = make_user(session)
    for end in (date(9999, 12, 31), date(2072, 3, 15), date(2029, 1, 1)):
        with pytest.raises(ValueError, match="range 1"):
            planning.set_ranges(session, user, 2027, [(date(2027, 3, 1), end)])
    assert planning.set_ranges(session, user, 2027, [(date(2027, 12, 18), date(2028, 1, 3))]) == [
        (date(2027, 12, 18), date(2028, 1, 3))
    ]


def test_start_year_rejects_a_wild_year_before_querying(session):
    user = make_user(session)
    for year in (40000, 2**40, 10**20):
        with pytest.raises(ValueError, match="year must be"):
            planning.start_year(session, user, year, 5, 0, [], today=TODAY)


def test_a_concurrent_second_start_returns_the_existing_year(clean_engine):
    with Session(clean_engine) as s:
        s.add(
            User(
                email="race@example.com",
                home_airport="ORD",
                country="US",
                holiday_calendar="US",
                pto_days_total=15,
                max_trip_days=16,
            )
        )
        s.commit()
        uid = s.scalar(select(User.id))
    out = {}

    def first():
        with Session(clean_engine) as s:
            planning.start_year(s, s.get(User, uid), 2027, 20, 0, [], today=TODAY)
            out["flushed"] = True
            time.sleep(1.0)
            s.commit()

    def second():
        while not out.get("flushed"):
            time.sleep(0.01)
        with Session(clean_engine) as s:
            try:
                row = planning.start_year(s, s.get(User, uid), 2027, 5, 0, [], today=TODAY)
                s.commit()
                out["second"] = (row.year, row.pto_days)
            except Exception as exc:  # noqa: BLE001
                out["second"] = type(exc).__name__

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert out["second"] == (2027, 20)
    with Session(clean_engine) as s:
        assert s.scalar(select(PlanningYear.pto_days)) == 20


# --- bookings ---


def planned(s, user, tracker, year=2027):
    s.add(PlannedTrip(user_id=user.id, year=year, tracker_id=tracker.id))
    s.flush()


def test_book_trip_computes_pto_from_the_calendar(session):
    user = make_user(session)
    t = make_tracker(session, user)
    planned(session, user, t)
    trip = planning.book_trip(session, user, t.id, 2027, date(2027, 5, 28), date(2027, 5, 31), geo=load_geo())
    assert trip.booked_pto == 1
    assert trip.booked is True
    assert trip.booked_at is not None
    assert trip.booked_price is None


def test_booking_again_replaces_the_booking(session):
    user = make_user(session)
    t = make_tracker(session, user)
    planned(session, user, t)
    geo = load_geo()
    planning.book_trip(session, user, t.id, 2027, date(2027, 5, 28), date(2027, 5, 31), geo=geo)
    trip = planning.book_trip(
        session,
        user,
        t.id,
        2027,
        date(2027, 5, 29),
        date(2027, 6, 4),
        price=Decimal("512.50"),
        currency="USD",
        pto_cost=4,
        geo=geo,
    )
    assert (trip.booked_depart, trip.booked_return) == (date(2027, 5, 29), date(2027, 6, 4))
    assert (trip.booked_price, trip.booked_currency, trip.booked_pto) == (Decimal("512.50"), "USD", 4)
    assert len(planning.booked_trips(session, user, geo=geo)) == 1


def test_overlapping_bookings_are_refused(session):
    user = make_user(session)
    a, b = make_tracker(session, user, "LIS"), make_tracker(session, user, "TH")
    planned(session, user, a)
    planned(session, user, b)
    geo = load_geo()
    planning.book_trip(session, user, a.id, 2027, date(2027, 3, 12), date(2027, 3, 21), geo=geo)
    with pytest.raises(ValueError, match=r"Overlaps your booked .+ trip\."):
        planning.book_trip(session, user, b.id, 2027, date(2027, 3, 21), date(2027, 3, 25), geo=geo)
    planning.book_trip(session, user, b.id, 2027, date(2027, 3, 22), date(2027, 3, 25), geo=geo)
    assert len(planning.booked_trips(session, user, [2027], geo=geo)) == 2


def test_booked_trips_fall_back_to_the_code_for_unknown_destinations(session):
    user = make_user(session)
    t = make_tracker(session, user, "ZZ-NOWHERE")
    planned(session, user, t)
    geo = load_geo()
    planning.book_trip(session, user, t.id, 2027, date(2027, 3, 12), date(2027, 3, 14), geo=geo)
    assert [b.destination for b in planning.booked_trips(session, user, geo=geo)] == ["ZZ-NOWHERE"]
    assert planning.booked_trips(session, user, [2028], geo=geo) == []


def test_book_trip_validates_dates(session):
    user = make_user(session)
    t = make_tracker(session, user)
    planned(session, user, t)
    geo = load_geo()
    with pytest.raises(ValueError):
        planning.book_trip(session, user, t.id, 2027, date(2028, 1, 5), date(2028, 1, 9), geo=geo)
    with pytest.raises(ValueError):
        planning.book_trip(session, user, t.id, 2027, date(2027, 5, 9), date(2027, 5, 5), geo=geo)
    with pytest.raises(ValueError):
        planning.book_trip(session, user, t.id, 2027, date(2027, 1, 1), date(2027, 3, 2), geo=geo)
    with pytest.raises(LookupError):
        planning.book_trip(session, user, t.id, 2028, date(2028, 5, 5), date(2028, 5, 9), geo=geo)
    other = make_user(session, email="other@example.com")
    with pytest.raises(LookupError):
        planning.book_trip(session, other, t.id, 2027, date(2027, 5, 5), date(2027, 5, 9), geo=geo)


def add_candidate(s, user, tracker, depart, ret, *, evening=False, pto=3, price="450"):
    rq = RouteQuery(
        origin="ORD", dest_airport="LIS", return_airport="LIS", depart_date=depart, return_date=ret
    )
    s.add(rq)
    s.flush()
    run = date(2026, 10, 25)
    s.add(
        TrackerRouteLink(
            tracker_id=tracker.id,
            route_query_id=rq.id,
            run_date=run,
            evening_departure=evening,
            pto_cost=pto,
            days_away=(ret - depart).days + 1,
            efficiency=2.0,
            month=depart.month,
            season_rating="good",
            days_off=[],
        )
    )
    c = Candidate(
        user_id=user.id,
        tracker_id=tracker.id,
        route_query_id=rq.id,
        run_date=run,
        evening_departure=evening,
        price=Decimal(price),
        currency="EUR",
        deal_level="good",
        go_now=50,
        confidence="normal",
        verified=True,
    )
    s.add(c)
    s.flush()
    return c


def test_booking_from_a_candidate_is_scoped_and_checked(session):
    user = make_user(session)
    other = make_user(session, email="other@example.com")
    t = make_tracker(session, user)
    geo = load_geo()
    c = add_candidate(session, user, t, date(2027, 5, 28), date(2027, 6, 5), evening=True, pto=2)
    with pytest.raises(LookupError):  # no planned trip for 2027 yet
        planning.book_from_candidate(session, user, c.id, geo=geo)
    planned(session, user, t)
    with pytest.raises(LookupError):  # someone else's candidate
        planning.book_from_candidate(session, other, c.id, geo=geo)
    with pytest.raises(LookupError):
        planning.book_from_candidate(session, user, 999999, geo=geo)
    trip = planning.book_from_candidate(session, user, c.id, geo=geo)
    assert (trip.booked_depart, trip.booked_return) == (date(2027, 5, 28), date(2027, 6, 5))
    assert trip.booked_pto == 2  # the link's cost, not the calendar's
    assert (trip.booked_price, trip.booked_currency) == (Decimal("450.00"), "EUR")


def test_cancel_booking_clears_it(session):
    user = make_user(session)
    other = make_user(session, email="other@example.com")
    t = make_tracker(session, user)
    planned(session, user, t)
    geo = load_geo()
    planning.book_trip(
        session, user, t.id, 2027, date(2027, 5, 28), date(2027, 5, 31), price=Decimal("10"), geo=geo
    )
    assert planning.cancel_booking(session, other, t.id, 2027) is False
    assert planning.cancel_booking(session, user, t.id, 2027) is True
    trip = session.scalar(select(PlannedTrip).where(PlannedTrip.tracker_id == t.id))
    assert trip.booked is False
    assert all(
        v is None
        for v in (
            trip.booked_depart,
            trip.booked_return,
            trip.booked_price,
            trip.booked_currency,
            trip.booked_pto,
            trip.booked_at,
        )
    )
    assert planning.cancel_booking(session, user, t.id, 2030) is False


def test_unplan_refuses_a_booked_trip(session):
    user = make_user(session)
    t = make_tracker(session, user)
    planned(session, user, t)
    planning.book_trip(session, user, t.id, 2027, date(2027, 5, 28), date(2027, 5, 31), geo=load_geo())
    with pytest.raises(ValueError, match="Cancel the booking first."):
        planning.unplan_trip(session, user, t.id, 2027, today=TODAY)
    assert t.active is True
    assert len(planning.booked_trips(session, user, geo=load_geo())) == 1
