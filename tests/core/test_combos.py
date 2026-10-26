"""Combinations of fantastic trips that fit together."""

import time
from datetime import date, timedelta
from decimal import Decimal

from ptopilot.core.combos import Combination, Leg, eligible, find_combinations
from ptopilot.core.fit import BookedTrip


def leg(
    tracker, depart, days=7, *, price=700, typical=1000, pto=3, confidence="normal", season="good", cid=None
):
    return Leg(
        tracker_id=tracker,
        destination=f"D{tracker}",
        candidate_id=cid or tracker * 1000 + depart.toordinal() % 1000,
        depart=depart,
        ret=depart + timedelta(days=days - 1),
        pto_cost=pto,
        price=Decimal(price),
        typical=Decimal(typical),
        currency="USD",
        confidence=confidence,
        season_rating=season,
        deep_link=None,
    )


A = leg(1, date(2027, 3, 1))
B = leg(2, date(2027, 6, 1))


def booking(depart, ret):
    return BookedTrip(9, "Rome", depart.year, depart, ret, 4, None, None)


def test_pct_below_and_savings():
    x = leg(1, date(2027, 3, 1), price=802, typical=1000)
    assert x.pct_below == 20 and x.savings == Decimal(198)


def test_a_combination_needs_every_leg_fantastic():
    weak = leg(2, date(2027, 6, 1), price=850)  # 15% below
    assert find_combinations([A, weak], [], 20) == []
    got = find_combinations([A, B], [], 20)
    assert len(got) == 1 and isinstance(got[0], Combination)
    assert [x.tracker_id for x in got[0].legs] == [1, 2]
    assert (got[0].pto, got[0].price, got[0].savings) == (6, Decimal(1400), Decimal(600))


def test_shoulder_season_or_low_confidence_legs_never_count():
    assert not eligible(leg(1, date(2027, 3, 1), season="shoulder"))
    assert not eligible(leg(1, date(2027, 3, 1), confidence="low"))
    assert find_combinations([A, leg(2, date(2027, 6, 1), season="shoulder")], [], 20) == []
    assert find_combinations([A, leg(2, date(2027, 6, 1), confidence="low")], [], 20) == []


def test_legs_never_overlap_each_other_or_a_booking():
    clash = leg(2, date(2027, 3, 7))  # shares 7 Mar with A
    assert find_combinations([A, clash], [], 20) == []
    assert find_combinations([A, B], [booking(date(2027, 6, 7), date(2027, 6, 9))], 20) == []
    assert find_combinations([A, B], [booking(date(2027, 6, 8), date(2027, 6, 9))], 20) != []


def test_total_pto_must_fit_the_remaining_pto():
    assert find_combinations([A, B], [], 5) == []
    assert len(find_combinations([A, B], [], 6)) == 1


def test_single_fantastic_trip_is_not_a_combination():
    assert find_combinations([A], [], 20) == []
    assert find_combinations([A, leg(1, date(2027, 8, 1))], [], 20) == []  # same tracker twice


def test_ranking_prefers_more_legs_then_savings_and_one_per_tracker_set():
    c = leg(3, date(2027, 9, 1), price=600)
    b_cheap = leg(2, date(2027, 6, 1), price=650, cid=77)
    got = find_combinations([A, B, b_cheap, c], [], 30)
    assert [len(x.legs) for x in got] == [3, 2, 2]
    assert {leg_.candidate_id for leg_ in got[0].legs} == {
        A.candidate_id,
        b_cheap.candidate_id,
        c.candidate_id,
    }
    sets = [frozenset(x.tracker_id for x in g.legs) for g in got]
    assert len(set(sets)) == len(sets)
    assert got[1].savings >= got[2].savings
    assert len(find_combinations([A, B, b_cheap, c], [], 30, max_shown=1)) == 1


def test_search_is_fast_enough():
    legs = [
        leg(t, date(2027, 1, 1) + timedelta(days=(t * 5 + k) * 7), days=5, price=700 - k, pto=1)
        for t in range(1, 11)
        for k in range(5)
    ]
    start = time.perf_counter()
    got = find_combinations(legs, [], 50)
    assert time.perf_counter() - start < 1
    assert len(got[0].legs) == 10
