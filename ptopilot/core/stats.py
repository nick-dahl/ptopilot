"""Price baselines (robust median / MAD) and deal classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import Literal

from ptopilot import config

Confidence = Literal["normal", "low"]
DealLevel = Literal["none", "good", "great"]
LengthBucket = Literal["short", "week", "long"]


@dataclass(frozen=True)
class Baseline:
    median: float
    sigma: float
    n: int
    confidence: Confidence


def compute_baseline(
    prices: Sequence[float],
    google_range: tuple[float, float] | None = None,
) -> Baseline | None:
    """Typical price and spread for a route.

    With fewer than COLD_START_N prices, blends toward Google's typical range (if given)
    with weight n / COLD_START_N, and marks confidence "low". Returns None with no data at all.
    """
    n = len(prices)
    if n == 0 and google_range is None:
        return None

    if n:
        m = median(prices)
        s = config.MAD_TO_SIGMA * median(abs(p - m) for p in prices)
    else:
        m = s = 0.0

    if n < config.COLD_START_N and google_range is not None:
        low, high = google_range
        w = n / config.COLD_START_N
        m = w * m + (1 - w) * (low + high) / 2
        s = w * s + (1 - w) * (high - low) / 2

    s = max(s, config.SIGMA_FLOOR_FRACTION * m)
    confidence: Confidence = "normal" if n >= config.COLD_START_N else "low"
    return Baseline(median=m, sigma=s, n=n, confidence=confidence)


def z_score(price: float, baseline: Baseline) -> float:
    return (price - baseline.median) / baseline.sigma


def deal_level(z: float) -> DealLevel:
    if z <= config.GREAT_DEAL_Z:
        return "great"
    if z <= config.GOOD_DEAL_Z:
        return "good"
    return "none"


def length_bucket(days_away: int) -> LengthBucket:
    if days_away <= 5:
        return "short"
    if days_away <= 10:
        return "week"
    return "long"
