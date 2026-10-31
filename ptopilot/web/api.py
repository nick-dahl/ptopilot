"""JSON for the type-ahead inputs (static/chips.js): airports, places and a calendar's holiday names.

Signed-in only, like every in-place endpoint: a signed-out request gets 401 (JSON) or a redirect home.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ptopilot.core.airports import AirportCatalog, distance_km
from ptopilot.core.calendar import upcoming_holiday_names

MAX_ROWS = 6
MIN_QUERY = 2  # one letter matches half the catalog
SIZES = ("large", "medium")


def airport_rows(catalog: AirportCatalog, q: str, near: str = "") -> list[dict]:
    """Large and medium airports matching `q`: in the destination search's match order (code, exact
    city, city, country, name), and nearest to `near` within one kind of match."""
    if len(q.strip()) < MIN_QUERY:
        return []
    home = catalog.get(near) if near.strip() else None
    found = []
    for i, (kind, exact, a) in enumerate(catalog.matches(q)):
        if a.size in SIZES:
            km = round(distance_km(home, a)) if home else None
            found.append(((kind > 0, not exact, kind, km or 0, i), a, km))
    found.sort(key=lambda t: t[0])
    return [
        {"code": a.code, "name": a.name, "city": a.city, "country": a.country, "km": km}
        for _, a, km in found[:MAX_ROWS]
    ]


def place_rows(catalog: AirportCatalog, q: str) -> list[dict]:
    """The /destinations search: a place, its country, and the airports that serve it."""
    if len(q.strip()) < MIN_QUERY:
        return []
    return [
        {
            "code": m.airport.code,
            "name": m.airport.city,
            "country": m.country_name,
            "airports": [{"code": a.code, "name": a.name} for a in (m.airport, *m.nearby)],
            # the airports the add card starts with: the place's own city, as the plain search checks them
            "default": [a.code for a in (m.airport, *m.nearby) if a.city == m.airport.city],
        }
        for m in catalog.search(q, limit=MAX_ROWS)
    ]


def router(
    catalog: AirportCatalog,
    today: Callable[[], date],
    signed_in: Callable[[Request], bool],
    signed_out: Callable[[Request], Response],
) -> APIRouter:
    api = APIRouter(prefix="/api")

    @api.get("/airports")
    def airports(request: Request, q: str = "", near: str = ""):
        return airport_rows(catalog, q, near) if signed_in(request) else signed_out(request)

    @api.get("/places")
    def places(request: Request, q: str = ""):
        return place_rows(catalog, q) if signed_in(request) else signed_out(request)

    @api.get("/holidays")
    def holidays(request: Request, calendar: str = ""):
        if not signed_in(request):
            return signed_out(request)
        return upcoming_holiday_names(calendar, today()) if calendar.strip() else []

    return api
