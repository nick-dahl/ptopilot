"""Shared types for fare sources. Pipelines depend on these, never on a specific provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class SourceUnavailable(Exception):
    """A source failed (network, auth, quota, or unparseable response). Message carries a short snippet."""


@dataclass(frozen=True)
class FareQuote:
    """A cached fare from a broad month scan. Unverified."""

    source: str
    origin: str
    dest_airport: str
    depart_date: date
    return_date: date | None
    price: float
    currency: str
    airline: str | None = None
    flight_number: str | None = None
    stops: int | None = None
    return_stops: int | None = None
    duration_min: int | None = None
    deep_link: str | None = None


@dataclass(frozen=True)
class ExactQuery:
    origin: str
    dest_airport: str  # fly into
    depart_date: date
    return_date: date
    currency: str = "USD"
    return_from: str | None = None  # fly home from; None means dest_airport (a plain round trip)

    @property
    def open_jaw(self) -> bool:
        return self.return_from not in (None, self.dest_airport)


@dataclass(frozen=True)
class FlightOption:
    """One bookable round trip. Details describe the outbound leg; price is the round-trip total."""

    price: float
    carrier: str
    stops: int
    duration_min: int  # outbound, including layovers
    outbound_departure: datetime  # local time at origin
    flight_numbers: tuple[str, ...] = ()
    overnight_layover: bool = False


@dataclass(frozen=True)
class ExactResult:
    source: str
    query: ExactQuery
    currency: str
    options: tuple[FlightOption, ...]
    deep_link: str
    typical_range: tuple[float, float] | None = None  # Google's typical price range, when the source has it
    # Google's daily price history for these exact dates, (day, price), when the source has it (SerpApi)
    price_history: tuple[tuple[date, float], ...] = ()

    def cheapest(self) -> FlightOption | None:
        return min(self.options, key=lambda o: o.price, default=None)


class MonthScanSource(Protocol):
    name: str

    def month_scan(
        self, origin: str, dest_airport: str, month: date, market: str, currency: str
    ) -> list[FareQuote]: ...


class ExactSearchSource(Protocol):
    name: str
    supports_open_jaw: bool  # can price "into A, home from B" itineraries

    def exact_search(self, query: ExactQuery) -> ExactResult: ...


def snippet(text: str, limit: int = 300) -> str:
    """Single-line, truncated excerpt of a payload for error messages."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
