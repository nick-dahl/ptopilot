"""Travelpayouts / Aviasales Data API: free cached fares, used for the broad month scan."""

from __future__ import annotations

from datetime import date, datetime

import httpx

from ptopilot.sources.base import FareQuote, SourceUnavailable, snippet

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"
TIMEOUT_S = 20


def parse_prices_for_dates(payload: dict, origin: str, dest_airport: str) -> list[FareQuote]:
    """prices_for_dates response -> FareQuotes. Rows with a bad price or date are skipped, not fatal."""
    if not isinstance(payload, dict):
        raise SourceUnavailable(f"travelpayouts: unexpected payload: {snippet(str(payload))}")
    if not payload.get("success", False):
        raise SourceUnavailable(f"travelpayouts: success=false: {snippet(str(payload))}")
    currency = str(payload.get("currency", "")).upper()
    quotes: list[FareQuote] = []
    for row in payload.get("data") or []:
        if not isinstance(row, dict):
            continue
        price = row.get("price")
        if not isinstance(price, int | float) or price <= 0:
            continue
        try:
            depart = datetime.fromisoformat(row["departure_at"]).date()
            ret = datetime.fromisoformat(row["return_at"]).date() if row.get("return_at") else None
        except (KeyError, TypeError, ValueError):
            continue
        airline = row.get("airline") or None
        number = row.get("flight_number")
        link = row.get("link") if isinstance(row.get("link"), str) and row.get("link") else None
        quotes.append(
            FareQuote(
                source="travelpayouts",
                origin=row.get("origin_airport") or origin,
                dest_airport=row.get("destination_airport") or dest_airport,
                depart_date=depart,
                return_date=ret,
                price=float(price),
                currency=currency,
                airline=airline,
                flight_number=f"{airline} {number}" if airline and number else None,
                stops=row.get("transfers"),
                return_stops=row.get("return_transfers"),
                duration_min=row.get("duration_to"),
                deep_link=(link if link.startswith("http") else SITE + link) if link else None,
            )
        )
    return quotes


class TravelpayoutsSource:
    name = "travelpayouts"

    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise ValueError("Travelpayouts token is empty; set TRAVELPAYOUTS_TOKEN")
        self._token = token
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def month_scan(
        self, origin: str, dest_airport: str, month: date, market: str, currency: str
    ) -> list[FareQuote]:
        params = {
            "origin": origin,
            "destination": dest_airport,
            "departure_at": month.strftime("%Y-%m"),
            "one_way": "false",
            "direct": "false",
            "sorting": "price",
            "unique": "false",
            "market": market.lower(),
            "currency": currency.lower(),
            "limit": 1000,
        }
        try:
            resp = self._client.get(API_URL, params=params, headers={"X-Access-Token": self._token})
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"travelpayouts: {type(exc).__name__}: {exc}") from exc
        if resp.status_code != 200:
            raise SourceUnavailable(f"travelpayouts: HTTP {resp.status_code}: {snippet(resp.text)}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SourceUnavailable(f"travelpayouts: invalid JSON: {snippet(resp.text)}") from exc
        return parse_prices_for_dates(payload, origin, dest_airport)
