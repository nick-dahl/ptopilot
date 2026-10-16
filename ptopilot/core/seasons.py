"""Seasonal suitability per destination and month."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import yaml

from ptopilot.core.calendar import ONE_DAY

Rating = Literal["good", "shoulder", "avoid"]
Tolerance = Literal["strict", "normal", "relaxed"]

RATINGS: tuple[Rating, ...] = ("good", "shoulder", "avoid")
ALLOWED: dict[Tolerance, frozenset[Rating]] = {
    "strict": frozenset({"good"}),
    "normal": frozenset({"good", "shoulder"}),
    "relaxed": frozenset({"good", "shoulder", "avoid"}),
}


def is_allowed(rating: Rating, tolerance: Tolerance) -> bool:
    return rating in ALLOWED[tolerance]


def trip_month(depart: date, return_: date) -> int:
    """Calendar month holding most of the trip's days; ties go to the earlier month."""
    counts: Counter[tuple[int, int]] = Counter()
    for i in range((return_ - depart).days + 1):
        d = depart + i * ONE_DAY
        counts[(d.year, d.month)] += 1
    best = max(counts.values())
    return min(ym for ym, n in counts.items() if n == best)[1]


@dataclass
class SeasonTable:
    """ratings[code] is a 12-item list (Jan..Dec); notes[code] maps month -> short note."""

    ratings: dict[str, list[Rating]]
    notes: dict[str, dict[int, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> SeasonTable:
        ratings: dict[str, list[Rating]] = {}
        notes: dict[str, dict[int, str]] = {}
        for code, entry in data.items():
            months = list(entry["months"])
            if len(months) != 12 or any(m not in RATINGS for m in months):
                raise ValueError(f"Season entry {code!r} needs 12 ratings from {RATINGS}")
            ratings[code] = months
            notes[code] = {int(k): str(v) for k, v in (entry.get("notes") or {}).items()}
        return cls(ratings, notes)

    @classmethod
    def from_yaml(cls, path: Path) -> SeasonTable:
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def rating(self, codes: Sequence[str], month: int) -> Rating:
        """Rating from the first code that has an entry (e.g. city, then country). Unknown -> "good"."""
        for code in codes:
            if code in self.ratings:
                return self.ratings[code][month - 1]
        return "good"

    def note(self, codes: Sequence[str], month: int) -> str | None:
        for code in codes:
            if code in self.ratings:
                return self.notes.get(code, {}).get(month)
        return None
