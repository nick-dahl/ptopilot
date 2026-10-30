"""How long a deal like today's usually lasts, judged from the trip's own price history (pure, no I/O)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from ptopilot import config

_EPS = 1e-9


def _depth(price: float, day: date, points: list[tuple[date, float]]) -> float | None:
    """`price` relative to the median of the points in the DURATION_WINDOW_DAYS before `day`.

    None when fewer than TRIP_HISTORY_MIN points fall in that window (too thin to call a dip).
    """
    first = day - timedelta(days=config.DURATION_WINDOW_DAYS)
    window = [p for d, p in points if first <= d < day]
    if len(window) < config.TRIP_HISTORY_MIN:
        return None
    return price / median(window) - 1


@dataclass(frozen=True)
class DurationEstimate:
    days: int | None
    thin: bool  # a dip today, but too little history to say how long it lasts


def expected_days(
    series: list[tuple[date, float]], today: date, today_price: float, days_to_departure: int
) -> int | None:
    """Typical days a dip as deep as today's lasts; None when unknown (see `duration_estimate`)."""
    return duration_estimate(series, today, today_price, days_to_departure).days


def duration_estimate(
    series: list[tuple[date, float]], today: date, today_price: float, days_to_departure: int
) -> DurationEstimate:
    """Typical days a dip as deep as today's lasts, capped by the days left to departure.

    `series` is the trip's daily price before `today` (ruled-out days already excluded). A past dip is a
    maximal run of consecutive calendar days each at least as far below its own trailing median as
    today is below its; a missing day ends the run, and so does a day without enough history to judge.
    The run that ends yesterday is today's own dip, so it is not a past dip. days is None with thin=False
    when there is no dip today, and None with thin=True when there is one (or today cannot be judged for
    lack of history) but fewer than DURATION_MIN_DIPS past dips.
    """
    today_depth = _depth(today_price, today, series)
    if today_depth is None:
        return DurationEstimate(None, True)
    if today_depth >= 0:
        return DurationEstimate(None, False)
    runs: list[tuple[date, int]] = []  # (last day, length)
    for day, price in sorted(series):
        depth = _depth(price, day, series)
        if depth is None or depth > today_depth + _EPS:
            continue
        if runs and runs[-1][0] == day - timedelta(days=1):
            runs[-1] = (day, runs[-1][1] + 1)
        else:
            runs.append((day, 1))
    lengths = [n for last, n in runs if last != today - timedelta(days=1)]
    if len(lengths) < config.DURATION_MIN_DIPS:
        return DurationEstimate(None, True)
    return DurationEstimate(max(1, min(math.ceil(median(lengths)), days_to_departure)), False)


def duration_label(days: int | None, dips_found: bool = True) -> str | None:
    """Wording for an expected duration; `dips_found=False` marks "None because of thin history"."""
    if days is None:
        return None if dips_found else "not enough history yet"
    if days > config.DURATION_LONG_DAYS:
        return "likely to hold for a week or more"
    return f"likely gone within ~{days} {'day' if days == 1 else 'days'}"
