"""Season ratings from a place's daily climate record (Open-Meteo)."""

from __future__ import annotations

from dataclasses import dataclass

from ptopilot import config
from ptopilot.core.seasons import Rating


@dataclass(frozen=True)
class MonthlyClimate:
    tmax_mean: float  # mean daily high, degrees C
    wet_days: float  # days per month with precipitation >= WET_DAY_MM, averaged over the years


def monthly_climate(payload: dict) -> list[MonthlyClimate]:
    """Daily Open-Meteo record -> 12 monthly summaries (January first)."""
    daily = payload["daily"]
    temp_sum = [0.0] * 12
    temp_n = [0] * 12
    wet = [0] * 12
    years: list[set[str]] = [set() for _ in range(12)]
    for day, tmax, rain in zip(
        daily["time"], daily["temperature_2m_max"], daily["precipitation_sum"], strict=True
    ):
        m = int(day[5:7]) - 1
        years[m].add(day[:4])
        if tmax is not None:
            temp_sum[m] += tmax
            temp_n[m] += 1
        if rain is not None and rain >= config.WET_DAY_MM:
            wet[m] += 1
    return [MonthlyClimate(temp_sum[m] / temp_n[m], wet[m] / len(years[m])) for m in range(12)]


def _rate(c: MonthlyClimate) -> Rating:
    avoid, good = config.SEASON_AVOID, config.SEASON_GOOD
    if (
        c.tmax_mean < avoid["tmax_below"]
        or c.tmax_mean > avoid["tmax_above"]
        or c.wet_days >= avoid["wet_days_min"]
    ):
        return "avoid"
    if good["tmax_min"] <= c.tmax_mean <= good["tmax_max"] and c.wet_days <= good["wet_days_max"]:
        return "good"
    return "shoulder"


def rate_months(climate: list[MonthlyClimate]) -> tuple[list[Rating], dict[int, str]]:
    """Twelve ratings (January first) and a note per month (1-12), e.g. "~8°C, 6 wet days"."""
    ratings = [_rate(c) for c in climate]
    notes = {i: f"~{c.tmax_mean:.0f}°C, {c.wet_days:.0f} wet days" for i, c in enumerate(climate, start=1)}
    return ratings, notes
