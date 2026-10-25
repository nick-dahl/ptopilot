"""Adding and removing the places a user tracks."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot.core.airports import PlaceMatch
from ptopilot.core.climate import monthly_climate, rate_months
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Destination, DestinationSeason, Tracker, User
from ptopilot.sources.base import SourceUnavailable
from ptopilot.sources.climate import fetch_climate

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
    except (SourceUnavailable, httpx.HTTPError):
        return  # the place is still usable: it just has no seasonal filtering
    s.add(
        DestinationSeason(
            code=code, months=list(ratings), notes={str(k): v for k, v in notes.items()}, source=SEASON_SOURCE
        )
    )


def add_destination(
    s: Session,
    user: User,
    match: PlaceMatch,
    airports: list[str],
    target_days: int,
    name: str | None = None,
    climate: Callable[[float, float], dict] = fetch_climate,
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
    return tracker


def remove_destination(s: Session, user: User, tracker_id: int) -> bool:
    """Deactivate the user's tracker. History (prices, candidates, baselines) is kept."""
    tracker = s.get(Tracker, tracker_id)
    if tracker is None or tracker.user_id != user.id:
        return False
    tracker.active = False
    s.flush()
    return True
