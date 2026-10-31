"""The destination page's date grid, Google Flights' idea in our terms: depart weeks down the side, trip
lengths (days away) across the top, and in each cell the best price for that week and length today.

Each cell links to its trip's row in the list below (#trip-{option_key}), so it works without JavaScript.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ptopilot import config
from ptopilot.web.history import TripOption

MAX_WEEKS = 12


@dataclass(frozen=True)
class GridCell:
    price: Decimal
    level: str  # the trip's deal level: 'great', 'good' or 'none'
    dimmed: bool  # every trip here is ruled out, snoozed or excluded
    option_key: str


@dataclass(frozen=True)
class DateGrid:
    weeks: list[date]  # the Monday of each depart week, earliest first
    lengths: list[int]  # days away
    cells: dict[tuple[date, int], GridCell]


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def grid_band(options: list[TripOption], target: int | None) -> tuple[int, int]:
    """The columns: target +/- TARGET_TOLERANCE_DAYS days away; without a target, the lengths on show."""
    if target:
        return target - config.TARGET_TOLERANCE_DAYS, target + config.TARGET_TOLERANCE_DAYS
    lengths = [o.days_away for o in options] or [0]
    return min(lengths), max(lengths)


def date_grid(options: list[TripOption], band: tuple[int, int]) -> DateGrid:
    """The grid for days away within band (inclusive). A cell holds its cheapest trip that is not dimmed,
    else its cheapest dimmed one. Open-jaw trips share the axes. At most MAX_WEEKS weeks, the earliest."""
    lengths = list(range(band[0], band[1] + 1))
    best: dict[tuple[date, int], TripOption] = {}
    for o in options:
        if o.days_away not in lengths:
            continue
        key = (week_of(o.depart_date), o.days_away)
        held = best.get(key)
        if held is None or (o.dimmed, o.price) < (held.dimmed, held.price):
            best[key] = o
    weeks = sorted({week for week, _ in best})[:MAX_WEEKS]
    cells = {
        key: GridCell(o.price, o.deal_level, o.dimmed, o.option_key)
        for key, o in best.items()
        if key[0] in weeks
    }
    return DateGrid(weeks, lengths, cells)
