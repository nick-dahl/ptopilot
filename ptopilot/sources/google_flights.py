"""Live Google Flights prices via the unofficial `fast-flights` library. Free but fragile."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable

SEARCH_TIMEOUT_S = 60
# Errors raised while reading Google's page for one route: that route can't be parsed, Google isn't down.
ROUTE_ERRORS = (TypeError, IndexError, KeyError)


def _call_with_timeout(fn: Callable[[ExactQuery], Any], query: ExactQuery, timeout_s: float) -> Any:
    """fast-flights has no timeout of its own. Run it in a daemon thread so a stalled request can't
    hang the pipeline or block interpreter exit."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn(query)
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError(f"timed out after {timeout_s}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _dt(simple: Any) -> datetime:
    """fast-flights SimpleDatetime -> naive local datetime."""
    (y, m, d), (hh, mm) = simple.date, simple.time
    return datetime(y, m, d, hh, mm)


def _airport_code(segment: Any) -> str | None:
    """IATA code of the airport a segment lands at, or None when the library gave no usable one."""
    code = getattr(getattr(segment, "to_airport", None), "code", None)
    return code if isinstance(code, str) and len(code) == 3 else None


def parse_flights(results: Sequence[Any]) -> tuple[FlightOption, ...]:
    """Map fast-flights `Flights` objects (outbound legs of round trips) to FlightOptions."""
    options: list[FlightOption] = []
    for r in results:
        segments = list(r.flights)
        if not segments or not r.price:
            continue
        layover_min = 0
        overnight = False
        longest: tuple[int, str | None] | None = None
        for prev, nxt in zip(segments, segments[1:], strict=False):
            arrive, leave = _dt(prev.arrival), _dt(nxt.departure)
            gap = int((leave - arrive).total_seconds() // 60)
            layover_min += gap
            if longest is None or gap > longest[0]:
                longest = (gap, _airport_code(prev))
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
                longest_layover_min=longest[0] if longest else None,
                longest_layover_airport=longest[1] if longest else None,
            )
        )
    return tuple(options)


def flights_from_script(js: str) -> list[Any]:
    """Google's results script -> fast-flights results. A page with no itineraries at all (results slot
    null) is "no flights": fast-flights 3.1 crashes on it instead of returning an empty list."""
    from fast_flights.exceptions import FlightsNotFound
    from fast_flights.parser import parse_js

    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if not data.endswith("errorHasStatus: true"):
        payload = json.loads(data)
        if len(payload) <= 3 or payload[3] is None:
            return []
    try:
        return list(parse_js(js))
    except FlightsNotFound:
        return []


def _default_search(query: ExactQuery) -> tuple[Sequence[Any], str]:
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights.fetcher import fetch_flights_html
    from selectolax.lexbor import LexborHTMLParser

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
    script = LexborHTMLParser(fetch_flights_html(q)).css_first(r"script.ds\:1")
    if script is None:
        raise RuntimeError("no results script in the Google Flights page")
    return flights_from_script(script.text()), q.url()


class GoogleFlightsSource:
    name = "google_flights"
    supports_open_jaw = False  # fast-flights 3.1's multi-city parser crashes (verified 2026-10-16)

    def __init__(
        self,
        search: Callable[[ExactQuery], tuple[Sequence[Any], str]] = _default_search,
        timeout_s: float = SEARCH_TIMEOUT_S,
    ):
        self._search = search
        self._timeout_s = timeout_s

    def exact_search(self, query: ExactQuery) -> ExactResult:
        if query.open_jaw:
            raise ValueError("google_flights cannot price open-jaw trips; check supports_open_jaw first")
        try:
            results, url = _call_with_timeout(self._search, query, self._timeout_s)
            options = parse_flights(results)
        except Exception as exc:  # the library scrapes HTML; any failure means "unavailable"
            message = f"google_flights: {type(exc).__name__}: {exc}"
            raise SourceUnavailable(message, route_specific=isinstance(exc, ROUTE_ERRORS)) from exc
        return ExactResult(
            source=self.name, query=query, currency=query.currency, options=options, deep_link=url
        )
