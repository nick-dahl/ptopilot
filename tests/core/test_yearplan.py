"""Year planning logic: merging open ranges, the month grid, and PTO allocation."""

from datetime import date

from ptopilot.core.yearplan import allocate_pto, merge_ranges, month_grid


def test_merge_ranges_merges_overlaps_and_touching():
    ranges = [
        (date(2027, 3, 10), date(2027, 3, 20)),
        (date(2027, 3, 1), date(2027, 3, 9)),
        (date(2027, 3, 15), date(2027, 3, 25)),
        (date(2027, 10, 1), date(2027, 10, 5)),
    ]
    assert merge_ranges(ranges) == [
        (date(2027, 3, 1), date(2027, 3, 25)),
        (date(2027, 10, 1), date(2027, 10, 5)),
    ]


def test_month_grid_starts_weeks_on_sunday():
    grid = month_grid(2027, 3)
    assert grid[0] == [None] + [date(2027, 3, d) for d in range(1, 7)]
    assert all(len(week) == 7 for week in grid)
    assert [d for week in grid for d in week if d] == [date(2027, 3, d) for d in range(1, 32)]


def test_allocate_pto_marks_trips_past_the_limit():
    assert allocate_pto([(1, 5), (2, 6), (3, 9), (4, None)], 15) == {3: 4}


def test_allocate_pto_a_trip_that_does_not_fit_consumes_nothing():
    assert allocate_pto([(1, 5), (2, 9), (3, 3)], 8) == {2: 3}
    assert allocate_pto([(1, 5)], 0) == {1: 0}
