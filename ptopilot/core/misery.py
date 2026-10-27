"""Judge an itinerary: which of its legs make a trip miserable, and whether a low price forgives them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ptopilot import config

Severity = Literal["moderate", "severe"]


@dataclass(frozen=True)
class Problem:
    kind: Literal["layover", "duration", "ground"]
    severity: Severity
    text: str


@dataclass(frozen=True)
class Assessment:
    verdict: Literal["ok", "forgiven", "ruled_out"]
    problems: tuple[Problem, ...]
    note: str | None


def format_duration(minutes: int) -> str:
    """ "9h", or "6h 30m"."""
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m}m" if m else f"{h}h"


def problems(
    *,
    longest_layover_min: int | None,
    layover_city: str | None,
    duration_min: int | None,
    fastest_min: int | None,
    ground_min: int | None,
    destination_name: str,
) -> tuple[Problem, ...]:
    """What is wrong with an itinerary; a detail that is not known never counts against it."""
    found: list[Problem] = []
    if longest_layover_min is not None and longest_layover_min > config.MISERY_LAYOVER_MODERATE_MIN:
        severe = longest_layover_min > config.MISERY_LAYOVER_SEVERE_MIN
        where = f" in {layover_city}" if layover_city else ""
        found.append(
            Problem(
                "layover",
                "severe" if severe else "moderate",
                f"{format_duration(longest_layover_min)} layover{where}",
            )
        )
    if duration_min and fastest_min:
        ratio = duration_min / fastest_min
        if ratio >= config.MISERY_DURATION_MODERATE:
            severe = ratio >= config.MISERY_DURATION_SEVERE
            found.append(
                Problem(
                    "duration",
                    "severe" if severe else "moderate",
                    f"{round(duration_min / 60)}h journey, {ratio:.1f}× the fastest",
                )
            )
    if ground_min is not None and ground_min >= config.MISERY_GROUND_MODERATE_MIN:
        severe = ground_min >= config.MISERY_GROUND_SEVERE_MIN
        found.append(
            Problem(
                "ground",
                "severe" if severe else "moderate",
                f"Lands ~{format_duration(ground_min)} from {destination_name}",
            )
        )
    return tuple(found)


def assess(
    found: tuple[Problem, ...], *, price: float, typical_median: float | None, typical_confident: bool
) -> Assessment:
    """ok with no problems; forgiven for one moderate problem at a real discount; otherwise ruled out."""
    if not found:
        return Assessment("ok", (), None)
    note = " · ".join(p.text for p in found)
    if len(found) == 1 and found[0].severity == "moderate" and typical_confident and typical_median:
        pct = round(100 * (1 - price / typical_median))
        if price <= (1 - config.MISERY_FORGIVE_PCT / 100) * typical_median:
            return Assessment("forgiven", found, f"{note} (worth it at {pct}% below typical)")
    return Assessment("ruled_out", found, note)
