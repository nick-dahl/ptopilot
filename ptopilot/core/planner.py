"""Turns a traveler's profile + one bucket-list tracker into concrete itineraries to price."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ptopilot import config
from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Geo
from ptopilot.core.seasons import Rating, SeasonTable, Tolerance, is_allowed, trip_month
from ptopilot.core.selection import ShapeConstraints, satisfies, select_top
from ptopilot.core.shapes import TripShape, generate_shapes


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Window ends before it starts: {self.start} > {self.end}")


@dataclass(frozen=True)
class TravelerProfile:
    home_airports: tuple[str, ...]
    calendar: WorkCalendar
    pto_available: int
    min_trip_days: int
    max_trip_days: int
    weather_tolerance: Tolerance = "normal"
    friday_evening_departure: bool = False


@dataclass(frozen=True)
class TrackerSpec:
    destination_code: str
    min_stay_days: int
    max_stay_days: int

    def __post_init__(self) -> None:
        if not 0 < self.min_stay_days <= self.max_stay_days:
            raise ValueError(
                f"Stay range must satisfy 0 < min <= max, got {self.min_stay_days}..{self.max_stay_days}"
            )


@dataclass(frozen=True)
class PlannedItinerary:
    origin: str
    dest_airport: str
    destination_code: str
    shape: TripShape
    month: int
    season_rating: Rating


def plan_itineraries(
    profile: TravelerProfile,
    tracker: TrackerSpec,
    windows: Sequence[Window],
    geo: Geo,
    seasons: SeasonTable,
    top_n: int = config.TOP_SHAPES_PER_WINDOW,
) -> list[PlannedItinerary]:
    """For each window and home airport: generate shapes, apply limits and season filter,
    keep the top_n, then fan out across the destination's airports. Duplicates from
    overlapping windows are dropped."""
    dest = geo.destination(tracker.destination_code)
    season_codes = (dest.code, dest.country)
    pto_available = max(profile.pto_available, 0)
    out: list[PlannedItinerary] = []
    seen: set[tuple[str, str, TripShape]] = set()

    for window in windows:
        shapes = generate_shapes(
            profile.calendar,
            window.start,
            window.end,
            profile.max_trip_days,
            friday_evening=profile.friday_evening_departure,
            slack_days=config.WINDOW_SLACK_DAYS,
        )
        for origin in profile.home_airports:
            rule = geo.travel_rule(origin, dest)
            constraints = ShapeConstraints(
                min_days_away=max(profile.min_trip_days, rule.min_trip_days),
                max_days_away=profile.max_trip_days,
                min_ground_days=tracker.min_stay_days,
                max_ground_days=tracker.max_stay_days,
                travel_overhead_days=rule.overhead_days,
                pto_available=pto_available,
            )
            season_of: dict[TripShape, tuple[int, Rating]] = {}
            for s in shapes:
                if not satisfies(s, constraints):
                    continue
                month = trip_month(s.depart_date, s.return_date)
                rating = seasons.rating(season_codes, month)
                if is_allowed(rating, profile.weather_tolerance):
                    season_of[s] = (month, rating)

            for s in select_top(season_of, n=top_n, max_per_length=config.MAX_SHAPES_PER_LENGTH):
                month, rating = season_of[s]
                for airport in dest.airports:
                    key = (origin, airport, s)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(PlannedItinerary(origin, airport, dest.code, s, month, rating))
    return out
