"""The 0-100 "go now" score combining deal strength, weather, PTO efficiency, and timing."""

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


def timing_component(days_until_departure: int, international: bool) -> float:
    lo, hi = config.SWEET_SPOT_DAYS["international" if international else "domestic"]
    return 1.0 if lo <= days_until_departure <= hi else config.OFF_SWEET_SPOT_TIMING


def go_now(
    z: float | None,
    rating: Rating,
    efficiency: float,
    days_until_departure: int,
    international: bool,
) -> int:
    w = config.GO_NOW_WEIGHTS
    total = (
        w["deal"] * deal_component(z)
        + w["weather"] * config.WEATHER_SCORES[rating]
        + w["efficiency"] * efficiency_component(efficiency)
        + w["timing"] * timing_component(days_until_departure, international)
    )
    return round(100 * total)
