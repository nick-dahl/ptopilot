"""Turns a traveler's profile + one bucket-list tracker into concrete itineraries to price."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date

from ptopilot import config
from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Destination, Geo
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
    ideal_trip_days: int | None = None  # preferred days away; trips near it are priced first

    def __post_init__(self) -> None:
        if not 0 < self.min_trip_days <= self.max_trip_days:
            raise ValueError(
                f"Trip length must satisfy 0 < min <= max, got {self.min_trip_days}..{self.max_trip_days}"
            )


@dataclass(frozen=True)
class TrackerSpec:
    destination_code: str
    min_stay_days: int
    max_stay_days: int
    target_days: int | None = None  # days away; with it, trips of target +/- tolerance qualify

    def __post_init__(self) -> None:
        if not 0 < self.min_stay_days <= self.max_stay_days:
            raise ValueError(
                f"Stay range must satisfy 0 < min <= max, got {self.min_stay_days}..{self.max_stay_days}"
            )


@dataclass(frozen=True)
class PlannedItinerary:
    origin: str
    dest_airport: str  # fly into
    destination_code: str
    shape: TripShape
    month: int
    season_rating: Rating
    return_airport: str  # fly home from; equals dest_airport except on open-jaw routes

    @property
    def open_jaw(self) -> bool:
        return self.return_airport != self.dest_airport


def target_band(target: int, tol: int, min_trip_days: int) -> tuple[int, int]:
    """Days away to search for a target: target +/- tol, but never below the place's minimum.

    A target shorter than the minimum searches from the minimum, a full band wide.
    """
    low = max(min_trip_days, target - tol)
    return low, max(target + tol, low + 2 * tol)


def _qualifying_shapes(
    profile: TravelerProfile,
    tracker: TrackerSpec,
    dest: Destination,
    windows: Sequence[Window],
    geo: Geo,
    seasons: SeasonTable,
    pto_available: int,
) -> Iterator[tuple[str, dict[TripShape, tuple[int, Rating]]]]:
    """For each window and home airport: the shapes that meet the days-away band, ground-day rule,
    PTO limit and season filter, as {shape: (month, rating)}."""
    season_codes = (dest.code, dest.country)
    target = tracker.target_days
    tol = config.TARGET_TOLERANCE_DAYS
    rules = {origin: geo.travel_rule(origin, dest) for origin in profile.home_airports}
    longest = profile.max_trip_days
    if target is not None:
        longest = max(longest, *(target_band(target, tol, r.min_trip_days)[1] for r in rules.values()))

    for window in windows:
        shapes = generate_shapes(
            profile.calendar,
            window.start,
            window.end,
            longest,
            friday_evening=profile.friday_evening_departure,
            slack_days=config.WINDOW_SLACK_DAYS,
        )
        for origin in profile.home_airports:
            rule = rules[origin]
            if target is None:
                days_away = (max(profile.min_trip_days, rule.min_trip_days), profile.max_trip_days)
                ground = (tracker.min_stay_days, tracker.max_stay_days)
            else:
                days_away = target_band(target, tol, rule.min_trip_days)
                ground = (0, days_away[1])
            constraints = ShapeConstraints(
                min_days_away=days_away[0],
                max_days_away=days_away[1],
                min_ground_days=ground[0],
                max_ground_days=ground[1],
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
            yield origin, season_of


def estimate_pto(
    profile: TravelerProfile,
    tracker: TrackerSpec,
    windows: Sequence[Window],
    geo: Geo,
    seasons: SeasonTable,
) -> int | None:
    """The fewest PTO days of any trip `plan_itineraries` would accept in these windows, ignoring the
    PTO limit; None when no trip qualifies."""
    dest = geo.destination(tracker.destination_code)
    costs = [
        s.pto_cost
        for _, season_of in _qualifying_shapes(
            profile, tracker, dest, windows, geo, seasons, config.MAX_PTO_DAYS
        )
        for s in season_of
    ]
    return min(costs, default=None)


def plan_itineraries(
    profile: TravelerProfile,
    tracker: TrackerSpec,
    windows: Sequence[Window],
    geo: Geo,
    seasons: SeasonTable,
    top_n: int = config.TOP_SHAPES_PER_WINDOW,
) -> list[PlannedItinerary]:
    """For each window and home airport: generate shapes, apply limits and season filter,
    keep the top_n, then fan out across the destination's (arrival, return) airport pairs:
    the same airport both ways for ordinary trips, every arrival x return pair for open-jaw
    routes. Duplicates from overlapping windows are dropped."""
    dest = geo.destination(tracker.destination_code)
    pto_available = max(profile.pto_available, 0)
    out: list[PlannedItinerary] = []
    seen: set[tuple[str, str, str, TripShape]] = set()
    if dest.open_jaw:
        airport_pairs = [(a, r) for a in dest.airports for r in dest.home_from]
    else:
        airport_pairs = [(a, a) for a in dest.airports]
    target = tracker.target_days

    for origin, season_of in _qualifying_shapes(profile, tracker, dest, windows, geo, seasons, pto_available):
        for s in select_top(
            season_of,
            n=top_n,
            max_per_length=config.MAX_SHAPES_PER_LENGTH,
            max_per_week=config.MAX_SHAPES_PER_WEEK,
            ideal_days=target if target is not None else profile.ideal_trip_days,
        ):
            month, rating = season_of[s]
            for airport, home_from in airport_pairs:
                key = (origin, airport, home_from, s)
                if key in seen:
                    continue
                seen.add(key)
                out.append(PlannedItinerary(origin, airport, dest.code, s, month, rating, home_from))
    return out
