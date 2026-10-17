"""The 0-100 "go now" score combining deal strength, weather, PTO efficiency, trip length, and timing."""

from __future__ import annotations

from ptopilot import config
from ptopilot.core.seasons import Rating


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def deal_component(z: float | None) -> float:
    if z is None:
        return 0.0
    return _clamp(-z / config.DEAL_Z_FOR_FULL_SCORE)


def efficiency_component(efficiency: float) -> float:
    return _clamp((efficiency - 1) / 2)


def length_fit(days_away: int, ideal: int | None) -> float:
    """1.0 at the preferred length, fading to 0 at LENGTH_FIT_SPAN days off it. No preference fits all."""
    if ideal is None:
        return 1.0
    return max(0.0, 1 - abs(days_away - ideal) / config.LENGTH_FIT_SPAN)


def timing_component(days_until_departure: int, international: bool) -> float:
    lo, hi = config.SWEET_SPOT_DAYS["international" if international else "domestic"]
    return 1.0 if lo <= days_until_departure <= hi else config.OFF_SWEET_SPOT_TIMING


def go_now(
    z: float | None,
    rating: Rating,
    efficiency: float,
    days_until_departure: int,
    international: bool,
    length_fit: float = 1.0,
) -> int:
    w = config.GO_NOW_WEIGHTS
    total = (
        w["deal"] * deal_component(z)
        + w["weather"] * config.WEATHER_SCORES[rating]
        + w["efficiency"] * efficiency_component(efficiency)
        + w["length"] * _clamp(length_fit)
        + w["timing"] * timing_component(days_until_departure, international)
    )
    return round(100 * total)
