"""Does a cheap related fare fit the user's year? Pure checks; no database."""

from datetime import date

from ptopilot.core.fit import BookedTrip
from ptopilot.core.related import fits

RANGES = [(date(2027, 6, 1), date(2027, 6, 30))]


def check(depart=date(2027, 6, 5), ret=date(2027, 6, 12), **overrides) -> bool:
    fields = {
        "ranges": RANGES,
        "pto_cost": 5,
        "pto_remaining": 10,
        "band": (6, 10),
        "rating": "good",
        "booked": (),
    } | overrides
    return fits(depart, ret, **fields)


def booked(depart, ret) -> BookedTrip:
    return BookedTrip(1, "Lisbon", depart.year, depart, ret, 3, None, None)


def test_fit_needs_the_whole_trip_inside_a_range_and_pto_left():
    assert check()
    assert not check(date(2027, 6, 24), date(2027, 7, 1))  # return = range end + 1
    assert not check(date(2027, 5, 31), date(2027, 6, 7))  # departs the day before the range
    assert not check(pto_cost=11)  # remaining + 1
    assert check(date(2027, 6, 21), date(2027, 6, 30), pto_cost=10)  # both at the edge
    assert check(ranges=[(date(2027, 1, 1), date(2027, 1, 9)), *RANGES])  # any range will do


def test_fit_needs_the_days_away_in_the_target_band():
    assert check(date(2027, 6, 5), date(2027, 6, 10), band=(6, 10))  # 6 days away
    assert not check(date(2027, 6, 5), date(2027, 6, 9), band=(6, 10))  # 5
    assert check(date(2027, 6, 5), date(2027, 6, 14), band=(6, 10))  # 10
    assert not check(date(2027, 6, 5), date(2027, 6, 15), band=(6, 10))  # 11


def test_fit_needs_a_good_season_and_no_booked_overlap():
    assert not check(rating="shoulder")
    assert not check(rating="avoid")
    assert not check(rating=None)  # no ratings for the place: never surfaced
    assert not check(booked=[booked(date(2027, 6, 12), date(2027, 6, 20))])  # shares the return day
    assert check(booked=[booked(date(2027, 6, 13), date(2027, 6, 20))])
