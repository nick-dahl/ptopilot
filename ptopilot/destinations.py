"""Adding and removing the places a user tracks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ptopilot.core.airports import PlaceMatch
from ptopilot.core.climate import monthly_climate, rate_months
from ptopilot.core.geo import UnknownCodeError
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Destination, DestinationSeason, PlannedTrip, Tracker, User
from ptopilot.planning import plan_trip, planning_years
from ptopilot.sources.base import SourceUnavailable
from ptopilot.sources.climate import fetch_climate

log = logging.getLogger(__name__)
DEFAULT_PRIORITY = 2
SEASON_SOURCE = "open-meteo"


def destination_code(match: PlaceMatch, airports: list[str] | None = None, s: Session | None = None) -> str:
    """`HND_JP` for a new place, or the code of a built-in or added place with exactly these airports."""
    wanted = frozenset(airports or [match.airport.code])
    for d in load_geo().destinations():
        if frozenset(d.airports) == wanted and not d.return_airports:
            return d.code
    if s is not None:
        for d in s.scalars(select(Destination)):
            if frozenset(d.airports) == wanted and not d.return_airports:
                return d.code
    return f"{match.airport.code}_{match.airport.country}"


def _generate_seasons(
    s: Session, code: str, match: PlaceMatch, climate: Callable[[float, float], dict]
) -> None:
    try:
        ratings, notes = rate_months(monthly_climate(climate(match.airport.lat, match.airport.lon)))
    except Exception as exc:  # noqa: BLE001 - the place is still usable without seasonal filtering
        log.warning("climate lookup failed for %s: %s", code, type(exc).__name__)
        return
    s.add(
        DestinationSeason(
            code=code, months=list(ratings), notes={str(k): v for k, v in notes.items()}, source=SEASON_SOURCE
        )
    )


def _needs_seasons(s: Session, code: str) -> bool:
    return code not in {d.code for d in load_geo().destinations()} and (
        s.get(DestinationSeason, code) is None and code not in load_seasons().ratings
    )


def prefetch_climate(
    s: Session, match: PlaceMatch, airports: list[str], climate: Callable[[float, float], dict]
) -> Callable[[float, float], dict]:
    """Look the climate up now, so the caller can do it before opening the transaction that saves the place.

    Returns a stand-in for `climate` to hand to add_destination: it answers with what was fetched, or
    raises SourceUnavailable when nothing was needed or the lookup failed (no seasons are saved).
    """
    code = destination_code(match, airports, s)
    result: dict | None = None
    if _needs_seasons(s, code):
        try:
            result = climate(match.airport.lat, match.airport.lon)
        except Exception as exc:  # noqa: BLE001 - reported again, harmlessly, by _generate_seasons
            log.warning("climate lookup failed for %s: %s", code, type(exc).__name__)

    def fetched(lat: float, lon: float) -> dict:
        if result is None:
            raise SourceUnavailable("climate was not fetched")
        return result

    return fetched


def add_destination(
    s: Session,
    user: User,
    match: PlaceMatch,
    airports: list[str],
    target_days: int,
    name: str | None = None,
    climate: Callable[[float, float], dict] = fetch_climate,
    today: date | None = None,
) -> Tracker:
    code = destination_code(match, airports, s)
    if code not in {d.code for d in load_geo().destinations()}:
        if s.get(Destination, code) is None:
            s.add(
                Destination(
                    code=code,
                    name=name or match.airport.city,
                    kind="city",
                    airports=list(airports),
                    added_by=user.id,
                )
            )
            s.flush()
        if s.get(DestinationSeason, code) is None and code not in load_seasons().ratings:
            _generate_seasons(s, code, match, climate)
    tracker = s.scalars(
        select(Tracker).where(Tracker.user_id == user.id, Tracker.destination_code == code)
    ).first()
    if tracker is None:
        tracker = Tracker(user_id=user.id, destination_code=code, priority=DEFAULT_PRIORITY)
        s.add(tracker)
    tracker.target_days = target_days
    tracker.min_stay_days = max(target_days - 2 - 1, 1)
    tracker.max_stay_days = target_days + 2
    tracker.active = True
    s.flush()
    first_year = (today or date.today()).year
    for py in planning_years(s, user):
        if py.year >= first_year:
            plan_trip(s, user, tracker, py.year)
    return tracker


def _builtin_name(code: str) -> str:
    try:
        return load_geo().destination(code).name
    except UnknownCodeError:
        return code


def remove_destination(s: Session, user: User, tracker_id: int, *, today: date) -> bool:
    """Deactivate the user's tracker. History (prices, candidates, baselines) is kept.

    A tracker booked this year or later is refused: removing it would hide a booking that still counts.
    """
    tracker = s.get(Tracker, tracker_id)
    if tracker is None or tracker.user_id != user.id:
        return False
    if s.scalar(
        select(
            exists().where(
                PlannedTrip.tracker_id == tracker_id,
                PlannedTrip.year >= today.year,
                PlannedTrip.booked_depart.is_not(None),
            )
        )
    ):
        row = s.get(Destination, tracker.destination_code)
        name = row.name if row else _builtin_name(tracker.destination_code)
        raise ValueError(f"Cancel your {name} booking first.")
    tracker.active = False
    s.flush()
    return True
