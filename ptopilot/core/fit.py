"""Does a trip fit around the trips already booked and the PTO that is left? Pure; no database."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class BookedTrip:
    tracker_id: int
    destination: str
    year: int
    depart: date
    ret: date
    pto_cost: int
    price: Decimal | None
    currency: str | None


def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Whether two date ranges share a day; both ends count."""
    return a_start <= b_end and b_start <= a_end


def first_overlap(
    depart: date, ret: date, booked: Sequence[BookedTrip], ignore_tracker: int | None = None
) -> BookedTrip | None:
    for trip in booked:
        if trip.tracker_id == ignore_tracker:
            continue
        if overlaps(depart, ret, trip.depart, trip.ret):
            return trip
    return None


def fit_notes(
    depart: date,
    ret: date,
    pto_cost: int,
    booked: Sequence[BookedTrip],
    remaining: int | None,
    own_tracker_id: int | None = None,
) -> tuple[str, ...]:
    notes: list[str] = []
    clash = first_overlap(depart, ret, booked, own_tracker_id)
    if clash is not None:
        notes.append(f"Overlaps your booked {clash.destination} trip.")
    if remaining is not None and pto_cost > remaining:
        notes.append(f"Doesn't fit your remaining PTO ({max(remaining, 0)} left).")
    return tuple(notes)
