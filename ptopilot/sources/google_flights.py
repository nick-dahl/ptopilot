"""Live Google Flights prices via the unofficial `fast-flights` library. Free but fragile."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable


def _dt(simple: Any) -> datetime:
    """fast-flights SimpleDatetime -> naive local datetime."""
    (y, m, d), (hh, mm) = simple.date, simple.time
    return datetime(y, m, d, hh, mm)


def parse_flights(results: Sequence[Any]) -> tuple[FlightOption, ...]:
    """Map fast-flights `Flights` objects (outbound legs of round trips) to FlightOptions."""
    options: list[FlightOption] = []
    for r in results:
        segments = list(r.flights)
        if not segments or not r.price:
            continue
        layover_min = 0
        overnight = False
        for prev, nxt in zip(segments, segments[1:], strict=False):
            arrive, leave = _dt(prev.arrival), _dt(nxt.departure)
            layover_min += int((leave - arrive).total_seconds() // 60)
            overnight = overnight or leave.date() != arrive.date()
        options.append(
            FlightOption(
                price=float(r.price),
                carrier=", ".join(r.airlines),
                stops=len(segments) - 1,
                duration_min=sum(s.duration for s in segments) + layover_min,
                outbound_departure=_dt(segments[0].departure),
                flight_numbers=(),
                overnight_layover=overnight,
            )
        )
    return tuple(options)


def _default_search(query: ExactQuery) -> tuple[Sequence[Any], str]:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    from fast_flights.exceptions import FlightsNotFound

    q = create_query(
        flights=[
            FlightQuery(
                date=query.depart_date.isoformat(), from_airport=query.origin, to_airport=query.dest_airport
            ),
            FlightQuery(
                date=query.return_date.isoformat(), from_airport=query.dest_airport, to_airport=query.origin
            ),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=1),
        language="en-US",
        currency=query.currency,
    )
    try:
        return get_flights(q), q.url()
    except FlightsNotFound:
        return [], q.url()


class GoogleFlightsSource:
    name = "google_flights"

    def __init__(self, search: Callable[[ExactQuery], tuple[Sequence[Any], str]] = _default_search):
        self._search = search

    def exact_search(self, query: ExactQuery) -> ExactResult:
        try:
            results, url = self._search(query)
            options = parse_flights(results)
        except Exception as exc:  # the library scrapes HTML; any failure means "unavailable"
            raise SourceUnavailable(f"google_flights: {type(exc).__name__}: {exc}") from exc
        return ExactResult(
            source=self.name, query=query, currency=query.currency, options=options, deep_link=url
        )
