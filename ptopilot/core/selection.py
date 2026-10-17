"""Filtering trip shapes against a traveler's limits, and picking the best few."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ptopilot import config
from ptopilot.core.scoring import length_fit
from ptopilot.core.shapes import TripShape


@dataclass(frozen=True)
class ShapeConstraints:
    min_days_away: int
    max_days_away: int
    min_ground_days: int
    max_ground_days: int
    travel_overhead_days: float
    pto_available: int


def ground_days(shape: TripShape, travel_overhead_days: float) -> float:
    """Days actually at the destination after subtracting round-trip travel time."""
    return shape.days_away - travel_overhead_days


def satisfies(shape: TripShape, c: ShapeConstraints) -> bool:
    if not c.min_days_away <= shape.days_away <= c.max_days_away:
        return False
    if not c.min_ground_days <= ground_days(shape, c.travel_overhead_days) <= c.max_ground_days:
        return False
    return shape.pto_cost <= c.pto_available


def select_top(
    shapes: Iterable[TripShape],
    n: int = 6,
    max_per_length: int = 2,
    max_per_week: int | None = None,
    ideal_days: int | None = None,
) -> list[TripShape]:
    """Best n shapes by PTO efficiency, boosted near the preferred length (ideal_days; None = no boost),
    with diversity limits: at most max_per_length per trip length,
    at most max_per_week per departure week (ISO week; None = unlimited), and at most one per
    (depart, return) pair so an evening variant never duplicates its regular twin.

    Ties: fewer PTO days, then earlier departure, then the non-evening variant. Without a weekly limit,
    windows with no holidays (where every week ties) would only ever get trips from their first weeks.
    """

    def rank(s: TripShape) -> float:
        return s.efficiency * (1 + config.LENGTH_SELECTION_BONUS * length_fit(s.days_away, ideal_days))

    ranked = sorted(shapes, key=lambda s: (-rank(s), s.pto_cost, s.depart_date, s.evening_departure))
    picked: list[TripShape] = []
    per_length: Counter[int] = Counter()
    per_week: Counter[tuple[int, int]] = Counter()
    seen_dates: set[tuple[date, date]] = set()
    for s in ranked:
        dates = (s.depart_date, s.return_date)
        week = s.depart_date.isocalendar()[:2]
        if per_length[s.days_away] >= max_per_length or dates in seen_dates:
            continue
        if max_per_week is not None and per_week[week] >= max_per_week:
            continue
        picked.append(s)
        per_length[s.days_away] += 1
        per_week[week] += 1
        seen_dates.add(dates)
        if len(picked) == n:
            break
    return picked
