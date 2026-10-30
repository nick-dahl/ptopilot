"""Related places a user accepted or dismissed for one of their trackers."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot.core.airports import AirportCatalog, PlaceMatch
from ptopilot.core.geo import Geo, UnknownCodeError
from ptopilot.core.related import Suggestion, load_groups, suggest
from ptopilot.data import load_geo
from ptopilot.db.models import Destination, RelatedLink, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.destinations import _generate_seasons, _needs_seasons, ensure_place, prefetch_climate
from ptopilot.sources.climate import fetch_climate

log = logging.getLogger(__name__)


def _owned_tracker(s: Session, user: User, tracker_id: int) -> Tracker:
    tracker = s.get(Tracker, tracker_id)
    if tracker is None or tracker.user_id != user.id:
        raise LookupError(f"no tracker {tracker_id}")
    return tracker


def suggestions_for(
    s: Session, user: User, tracker: Tracker, geo: Geo, catalog: AirportCatalog
) -> list[Suggestion]:
    """The tracker's suggestions, minus places the user already tracks and links they already decided."""
    try:
        dest = geo.destination(tracker.destination_code)
    except UnknownCodeError:
        return []
    exclude: set[str] = set()
    for code in s.scalars(
        select(Tracker.destination_code).where(Tracker.user_id == user.id, Tracker.active.is_(True))
    ):
        try:
            exclude.update(geo.destination(code).own_airports)
        except UnknownCodeError:
            continue
    exclude.update(s.scalars(select(RelatedLink.airport).where(RelatedLink.tracker_id == tracker.id)))
    return suggest(dest, catalog, load_groups(), exclude)


def place_for(s: Session, airport: str, catalog: AirportCatalog) -> tuple[str | None, PlaceMatch | None]:
    """(code, None) when a built-in place has this airport, else (None, a match to create the place from).
    Walking routes (open-jaw) are never the place for an airport: Porto is not the Camino."""
    for d in load_geo().destinations():
        if d.kind != "route" and not d.return_airports and airport in d.airports:
            return d.code, None
    found = catalog.get(airport)
    if found is None:
        raise ValueError(f"unknown airport {airport}")
    return None, PlaceMatch(found, (), catalog.country_name(found.country))


def accept(
    s: Session,
    user: User,
    tracker_id: int,
    airport: str,
    *,
    climate: Callable[[float, float], dict] = fetch_climate,
    catalog: AirportCatalog | None = None,
) -> RelatedLink:
    """Link a related airport to the tracker, creating its place if needed. No tracker is created for it."""
    _owned_tracker(s, user, tracker_id)
    airport = airport.strip().upper()
    code, match = place_for(s, airport, catalog or AirportCatalog.load())
    if code is None:
        code = ensure_place(s, user, match, [airport], None, climate)
    return _set_status(s, user, tracker_id, airport, code, "accepted")


def dismiss(s: Session, user: User, tracker_id: int, airport: str) -> None:
    """Never suggest this airport again for the tracker. Also removes an accepted link."""
    _owned_tracker(s, user, tracker_id)
    airport = airport.strip().upper()
    existing = s.scalars(
        select(RelatedLink).where(RelatedLink.tracker_id == tracker_id, RelatedLink.airport == airport)
    ).first()
    code = existing.place_code if existing else place_for(s, airport, AirportCatalog.load())[0] or airport
    _set_status(s, user, tracker_id, airport, code, "dismissed")


def _set_status(
    s: Session, user: User, tracker_id: int, airport: str, place_code: str, status: str
) -> RelatedLink:
    link = s.scalars(
        select(RelatedLink).where(RelatedLink.tracker_id == tracker_id, RelatedLink.airport == airport)
    ).first()
    if link is None:
        link = RelatedLink(user_id=user.id, tracker_id=tracker_id, airport=airport)
        s.add(link)
    link.place_code = place_code
    link.status = status
    s.flush()
    return link


def accepted_links(s: Session, user_id: int | None = None) -> list[RelatedLink]:
    q = select(RelatedLink).where(RelatedLink.status == "accepted").order_by(RelatedLink.id)
    if user_id is not None:
        q = q.where(RelatedLink.user_id == user_id)
    return list(s.scalars(q))


def _added_match(s: Session, place_code: str, catalog: AirportCatalog) -> tuple[PlaceMatch, list[str]] | None:
    row = s.get(Destination, place_code)
    first = catalog.get(row.airports[0]) if row and row.airports else None
    if row is None or first is None:
        return None
    return PlaceMatch(first, (), catalog.country_name(first.country)), list(row.airports)


def missing_seasons(s: Session, place_code: str, catalog: AirportCatalog) -> PlaceMatch | None:
    """The place to look up when an added place has no seasons yet; None when nothing is missing."""
    found = _added_match(s, place_code, catalog)
    return found[0] if found and _needs_seasons(s, place_code) else None


def ensure_seasons(
    s: Session, place_code: str, catalog: AirportCatalog, climate: Callable[[float, float], dict]
) -> None:
    """Retry a missing climate lookup for an added place. Pass a prefetched `climate` to keep the network call
    out of the saving transaction (see destinations.prefetch_climate)."""
    match = missing_seasons(s, place_code, catalog)
    if match is not None:
        _generate_seasons(s, place_code, match, climate)


def refresh_missing_seasons(engine, user_id: int, catalog: AirportCatalog, climate) -> None:
    """Retry the climate lookup for one of the user's accepted places that lacks seasons (one per page view,
    so a place that keeps failing can't slow every view).

    Each lookup runs in a short read-only session and is saved in a later one, so the network call
    never holds the saving transaction.
    """
    with session_scope(engine) as s:
        codes = list(dict.fromkeys(link.place_code for link in accepted_links(s, user_id)))
        todo = []
        for code in codes:
            match = missing_seasons(s, code, catalog)
            if match is not None:
                airports = list(s.get(Destination, code).airports)
                todo.append((code, prefetch_climate(s, match, airports, climate)))
                break
    if not todo:
        return
    with session_scope(engine) as s:
        for code, fetched in todo:
            ensure_seasons(s, code, catalog, fetched)
