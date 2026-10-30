"""Related places for a tracked destination: curated look-alikes, and airports right next door."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib import resources
from typing import Literal

import yaml

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.fit import BookedTrip, first_overlap
from ptopilot.core.geo import Destination
from ptopilot.core.seasons import Rating


@dataclass(frozen=True)
class RelatedGroup:
    name: str
    airports: tuple[str, ...]


@dataclass(frozen=True)
class Suggestion:
    airport: str
    kind: Literal["theme", "near"]
    label: str  # the group name, or "~N km away"
    km: float | None


@cache
def load_groups() -> tuple[RelatedGroup, ...]:
    text = resources.files("ptopilot.data").joinpath("related.yaml").read_text(encoding="utf-8")
    return tuple(RelatedGroup(g["name"], tuple(g["airports"])) for g in yaml.safe_load(text)["groups"])


def suggest(
    dest: Destination,
    catalog: AirportCatalog,
    groups: Sequence[RelatedGroup],
    exclude: Collection[str] = (),
) -> list[Suggestion]:
    """Thematic picks first (group order), then airports within RELATED_NEAR_KM by distance; capped."""
    skip = set(dest.own_airports) | set(exclude)
    out: dict[str, Suggestion] = {}
    for g in groups:
        if not set(dest.own_airports) & set(g.airports):
            continue
        for code in g.airports:
            if code not in skip and code not in out:
                out[code] = Suggestion(code, "theme", g.name, None)
    nearest: dict[str, float] = {}
    for own in dest.own_airports:
        for km, a in catalog.within(own, config.RELATED_NEAR_KM):
            if a.code not in skip:
                nearest[a.code] = min(km, nearest.get(a.code, km))
    for code, km in sorted(nearest.items(), key=lambda t: (t[1], t[0])):
        out.setdefault(code, Suggestion(code, "near", f"~{round(km)} km away", km))
    return list(out.values())[: config.RELATED_MAX_SUGGESTIONS]


def fits(
    depart: date,
    ret: date,
    *,
    ranges: Sequence[tuple[date, date]],
    pto_cost: int,
    pto_remaining: int,
    band: tuple[int, int],
    rating: Rating | None,
    booked: Sequence[BookedTrip],
) -> bool:
    """A related fare fits when the whole trip lies in an open range, its PTO is left, its days away are in
    the band, the place's season is exactly good (None: no ratings, never), and no booked trip overlaps."""
    days_away = (ret - depart).days + 1
    return (
        any(start <= depart and ret <= end for start, end in ranges)
        and pto_cost <= pto_remaining
        and band[0] <= days_away <= band[1]
        and rating == "good"
        and first_overlap(depart, ret, booked) is None
    )
