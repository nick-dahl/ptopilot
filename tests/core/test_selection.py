from datetime import date, timedelta

from ptopilot.core.selection import ShapeConstraints, ground_days, satisfies, select_top
from ptopilot.core.shapes import TripShape

C = ShapeConstraints(
    min_days_away=9,
    max_days_away=16,
    min_ground_days=7,
    max_ground_days=12,
    travel_overhead_days=3,
    pto_available=10,
)


def shape(days_away, pto, start=date(2027, 6, 5), evening=False):
    return TripShape(start, start + timedelta(days=days_away - 1), pto, evening)


def test_ground_days_subtracts_travel_overhead():
    assert ground_days(shape(10, 5), 3) == 7


def test_satisfies_accepts_a_trip_inside_every_limit():
    assert satisfies(shape(10, 5), C)


def test_satisfies_rejects_too_short_trip():
    assert not satisfies(shape(8, 4), C)


def test_satisfies_rejects_too_little_ground_time():
    c = ShapeConstraints(9, 16, 8, 12, 3, 10)
    assert not satisfies(shape(10, 5), c)  # 7 ground days < 8


def test_satisfies_rejects_too_much_ground_time():
    assert not satisfies(shape(16, 10), C)  # 13 ground days > 12


def test_satisfies_rejects_over_budget_pto():
    assert not satisfies(shape(15, 11), C)


def test_select_top_ranks_by_efficiency():
    a, b, c = shape(9, 5), shape(10, 4), shape(12, 8)
    assert select_top([a, b, c], n=2) == [b, a]


def test_select_top_limits_shapes_per_trip_length():
    same_length = [shape(9, 5, date(2027, 6, 5) + timedelta(days=7 * i)) for i in range(4)]
    other = shape(12, 8)
    picked = select_top(same_length + [other], n=6, max_per_length=2)
    assert len(picked) == 3
    assert picked[:2] == same_length[:2]  # earlier departures win ties
    assert picked[2] == other


def test_select_top_prefers_fewer_pto_days_on_equal_efficiency():
    a = shape(10, 5)
    b = shape(8, 4, date(2027, 7, 3))
    assert select_top([a, b], n=1) == [b]


def test_select_top_keeps_one_shape_per_date_pair():
    regular = shape(10, 6)
    evening = shape(10, 5, evening=True)
    assert select_top([regular, evening], n=6) == [evening]


def test_select_top_returns_at_most_n():
    shapes = [shape(9 + i, 5) for i in range(8)]
    assert len(select_top(shapes, n=6)) == 6
