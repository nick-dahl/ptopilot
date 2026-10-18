"""SerpApi Google Flights: quota-limited fallback that also returns Google's typical price range."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable, snippet

API_URL = "https://serpapi.com/search.json"
TIMEOUT_S = 60


def _option(item: dict) -> FlightOption | None:
    legs = item.get("flights") or []
    price = item.get("price")
    if not legs or not isinstance(price, int | float):
        return None
    airlines: list[str] = []
    for leg in legs:
        if leg.get("airline") and leg["airline"] not in airlines:
            airlines.append(leg["airline"])
    return FlightOption(
        price=float(price),
        carrier=", ".join(airlines),
        stops=len(legs) - 1,
        duration_min=int(item.get("total_duration") or sum(leg.get("duration", 0) for leg in legs)),
        outbound_departure=datetime.strptime(legs[0]["departure_airport"]["time"], "%Y-%m-%d %H:%M"),
        flight_numbers=tuple(leg["flight_number"] for leg in legs if leg.get("flight_number")),
        overnight_layover=any(lay.get("overnight") for lay in item.get("layovers") or []),
    )


NO_RESULTS_MARKER = "hasn't returned any results"


def parse_price_history(insights: object) -> tuple[tuple[date, float], ...]:
    """price_insights.price_history, [[unix_ts, price], ...] -> ((UTC day, price), ...). Skips bad points."""
    raw = insights.get("price_history") if isinstance(insights, dict) else None
    if not isinstance(raw, list):
        return ()
    points = []
    for point in raw:
        if not (isinstance(point, list) and len(point) == 2):
            continue
        ts, price = point
        if isinstance(ts, bool) or isinstance(price, bool):
            continue
        if not (isinstance(ts, int | float) and isinstance(price, int | float)):
            continue
        points.append((datetime.fromtimestamp(ts, UTC).date(), float(price)))
    return tuple(points)


def parse_google_flights(payload: dict, query: ExactQuery) -> ExactResult:
    if not isinstance(payload, dict):
        raise SourceUnavailable(f"serpapi: unexpected payload: {snippet(str(payload))}")
    if "error" in payload:
        if NO_RESULTS_MARKER in str(payload["error"]):  # a valid search with no flights, not an outage
            return ExactResult(
                source="serpapi", query=query, currency=query.currency, options=(), deep_link=""
            )
        raise SourceUnavailable(f"serpapi: {snippet(str(payload['error']))}")
    try:
        items = (payload.get("best_flights") or []) + (payload.get("other_flights") or [])
        options = tuple(o for o in (_option(i) for i in items) if o is not None)
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceUnavailable(f"serpapi: unexpected flight shape: {exc}") from exc
    insights = payload.get("price_insights") or {}
    typical = insights.get("typical_price_range")
    typical_range = (float(typical[0]), float(typical[1])) if typical and len(typical) == 2 else None
    url = (payload.get("search_metadata") or {}).get("google_flights_url", "")
    return ExactResult(
        source="serpapi",
        query=query,
        currency=query.currency,
        options=options,
        deep_link=url,
        typical_range=typical_range,
        price_history=parse_price_history(insights),
    )


class SerpApiSource:
    name = "serpapi"
    supports_open_jaw = True  # via type=3 multi-city searches

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("SerpApi key is empty; set SERPAPI_KEY")
        self._key = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def exact_search(self, query: ExactQuery) -> ExactResult:
        params: dict[str, str | int] = {
            "engine": "google_flights",
            "currency": query.currency,
            "hl": "en",
            "api_key": self._key,
        }
        if query.open_jaw:
            legs = [
                {
                    "departure_id": query.origin,
                    "arrival_id": query.dest_airport,
                    "date": query.depart_date.isoformat(),
                },
                {
                    "departure_id": query.return_from,
                    "arrival_id": query.origin,
                    "date": query.return_date.isoformat(),
                },
            ]
            params |= {"type": 3, "multi_city_json": json.dumps(legs)}
        else:
            params |= {
                "type": 1,
                "departure_id": query.origin,
                "arrival_id": query.dest_airport,
                "outbound_date": query.depart_date.isoformat(),
                "return_date": query.return_date.isoformat(),
            }
        try:
            resp = self._client.get(API_URL, params=params)
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"serpapi: {type(exc).__name__}: {exc}") from exc
        if resp.status_code != 200:
            raise SourceUnavailable(f"serpapi: HTTP {resp.status_code}: {snippet(resp.text)}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SourceUnavailable(f"serpapi: invalid JSON: {snippet(resp.text)}") from exc
        return parse_google_flights(payload, query)
