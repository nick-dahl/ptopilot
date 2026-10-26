"""Trips from different places that are all fantastic deals and fit together. Pure; no database."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ptopilot import config
from ptopilot.core.fit import BookedTrip, overlaps


@dataclass(frozen=True)
class Leg:
    tracker_id: int
    destination: str
    candidate_id: int
    depart: date
    ret: date
    pto_cost: int
    price: Decimal
    typical: Decimal
    currency: str
    confidence: str
    season_rating: str
    deep_link: str | None

    @property
    def pct_below(self) -> int:
        if self.typical <= 0:
            return 0
        return round(100 * (1 - float(self.price) / float(self.typical)))

    @property
    def savings(self) -> Decimal:
        return self.typical - self.price


def eligible(leg: Leg) -> bool:
    return (
        leg.pct_below >= config.COMBO_MIN_PCT_BELOW
        and leg.confidence == "normal"
        and leg.season_rating == "good"
    )


@dataclass(frozen=True)
class Combination:
    legs: tuple[Leg, ...]

    @property
    def pto(self) -> int:
        return sum(leg.pto_cost for leg in self.legs)

    @property
    def price(self) -> Decimal:
        return sum((leg.price for leg in self.legs), Decimal(0))

    @property
    def savings(self) -> Decimal:
        return sum((leg.savings for leg in self.legs), Decimal(0))


def _key(legs: Sequence[Leg]) -> tuple[int, Decimal, int]:
    return (-len(legs), -sum((leg.savings for leg in legs), Decimal(0)), sum(leg.pto_cost for leg in legs))


def find_combinations(
    legs: Iterable[Leg],
    booked: Sequence[BookedTrip],
    remaining: int,
    max_shown: int = config.COMBO_MAX_SHOWN,
) -> list[Combination]:
    """The best sets of fantastic trips that fit together: most legs, then most saved, then least PTO.

    One combination per set of destinations. Searches each set, biggest first, with a depth-first search
    that drops a branch once even its best possible finish cannot enter the top `max_shown`.
    """
    by_tracker: dict[int, list[Leg]] = {}
    for leg in legs:
        if eligible(leg) and not any(overlaps(leg.depart, leg.ret, b.depart, b.ret) for b in booked):
            by_tracker.setdefault(leg.tracker_id, []).append(leg)
    groups = [
        sorted(g, key=lambda leg: (-leg.pct_below, leg.price))[: config.COMBO_LEGS_PER_TRACKER]
        for _, g in sorted(by_tracker.items())
    ]
    count = len(groups)
    if count < config.COMBO_MIN_LEGS or max_shown <= 0:
        return []

    top: list[tuple[tuple, tuple[Leg, ...]]] = []  # best first, one per set of destinations

    def best_for(subset: Sequence[int], beat: tuple | None) -> tuple[Leg, ...] | None:
        """The best non-overlapping, affordable pick of one leg per destination in the subset."""
        lists = [groups[i] for i in subset]
        size = len(lists)
        tail_saved = [Decimal(0)] * (size + 1)
        tail_pto = [0] * (size + 1)
        for i in range(size - 1, -1, -1):
            tail_saved[i] = tail_saved[i + 1] + max(x.savings for x in lists[i])
            tail_pto[i] = tail_pto[i + 1] + min(x.pto_cost for x in lists[i])
        found: tuple[tuple, tuple[Leg, ...]] | None = None
        chosen: list[Leg] = []

        def visit(i: int, pto: int, saved: Decimal) -> None:
            nonlocal found
            if i == size:
                key = (-size, -saved, pto)
                if (found is None or key < found[0]) and (beat is None or key < beat):
                    found = (key, tuple(chosen))
                return
            limit = found[0] if found else beat
            if limit is not None and (-size, -(saved + tail_saved[i]), pto + tail_pto[i]) >= limit:
                return  # even the best finish from here cannot improve on what is known
            for x in sorted(lists[i], key=lambda x: -x.savings):
                if pto + x.pto_cost + tail_pto[i + 1] > remaining:
                    continue
                if any(overlaps(x.depart, x.ret, c.depart, c.ret) for c in chosen):
                    continue
                chosen.append(x)
                visit(i + 1, pto + x.pto_cost, saved + x.savings)
                chosen.pop()

        visit(0, 0, Decimal(0))
        return found[1] if found else None

    # Bigger sets first: once the top is full, smaller sets can never enter it.
    for size in range(count, config.COMBO_MIN_LEGS - 1, -1):
        if len(top) >= max_shown and size < -top[-1][0][0]:
            break
        for subset in itertools.combinations(range(count), size):
            beat = top[-1][0] if len(top) >= max_shown else None
            picked = best_for(subset, beat)
            if picked is None:
                continue
            top.append((_key(picked), picked))
            top.sort(key=lambda kv: kv[0])
            del top[max_shown:]
    return [Combination(tuple(sorted(legs, key=lambda x: x.depart))) for _, legs in top]
