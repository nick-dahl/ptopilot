"""Pure logic for the planning year: open ranges, the month grid and PTO allocation."""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from datetime import date, timedelta


def merge_ranges(ranges: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    """Sort ranges and merge those that overlap or touch (one ends the day before the next starts)."""
    merged: list[tuple[date, date]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def month_grid(year: int, month: int) -> list[list[date | None]]:
    """The month as weeks of seven cells starting on Sunday; None pads the first and last weeks."""
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    return [[d if d.month == month else None for d in week] for week in weeks]


def allocate_pto(trips: Sequence[tuple[int, int | None]], available: int) -> dict[int, int | None]:
    """For each trip that does not fit in the PTO left by the earlier fitting trips, the PTO that was left.

    `trips` are (key, estimated PTO) pairs in planner order. A trip that fits has no entry, and a
    trip with no estimate never fails to fit. A trip that does not fit uses none of the PTO.
    """
    left = available
    over: dict[int, int | None] = {}
    for key, est in trips:
        if est is None:
            continue
        if est > left:
            over[key] = max(left, 0)
        else:
            left -= est
    return over
