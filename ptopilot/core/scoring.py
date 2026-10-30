"""The 0-100 "go now" score combining deal strength, weather, PTO efficiency, trip length, and timing."""

from __future__ import annotations

from ptopilot import config
from ptopilot.core.seasons import Rating


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def deal_component(z: float | None, capped: bool = False) -> float:
    """0-1 deal strength; thin evidence (low-confidence baseline, unverified price) caps it at half."""
    if z is None:
        return 0.0
    part = _clamp(-z / config.DEAL_Z_FOR_FULL_SCORE)
    return min(part, 0.5) if capped else part


def conservative_z(z_route: float | None, z_trip: float | None) -> float | None:
    """The less extreme of the route-month z and the exact trip's own z, whichever exist."""
    if z_route is None or z_trip is None:
        return z_route if z_trip is None else z_trip
    return max(z_route, z_trip)


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
    deal_capped: bool = False,
) -> int:
    w = config.GO_NOW_WEIGHTS
    total = (
        w["deal"] * deal_component(z, deal_capped)
        + w["weather"] * config.WEATHER_SCORES[rating]
        + w["efficiency"] * efficiency_component(efficiency)
        + w["length"] * _clamp(length_fit)
        + w["timing"] * timing_component(days_until_departure, international)
    )
    return round(100 * total)
