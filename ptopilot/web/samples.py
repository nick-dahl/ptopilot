"""Fixed, illustrative examples for the landing page. Never real travelers' trips.

The example dates move with today, a few months ahead, so the page never shows a trip in the past."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Geo, Palette, palette
from ptopilot.photos import PlacePhoto, builtin_photos
from ptopilot.web.history import DestinationSummary, TripOption
from ptopilot.web.planner_view import _month_weeks
from ptopilot.web.viz import bar_geometry

HERO_PLACE = "PATAGONIA"  # Torres del Paine: the landing page's full-width photo
MONTHS_AHEAD = 4  # the example calendar shows the month this far from today's
CALENDAR = WorkCalendar("US")


def _month_after(day: date, months: int) -> date:
    """The first of the month `months` after `day`'s."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def example_trip(today: date, months: int = MONTHS_AHEAD) -> tuple[date, date]:
    """An 11-day Friday-to-Monday trip (two weekends) from the first Friday after the 4th of the month."""
    first = _month_after(today, months)
    depart = first + timedelta(days=4)
    depart += timedelta(days=(calendar.FRIDAY - depart.weekday()) % 7)
    return depart, depart + timedelta(days=10)


def _pto(depart: date, ret: date) -> int:
    """Weekdays away that aren't holidays: what the trip costs in PTO."""
    days = (depart + timedelta(days=n) for n in range((ret - depart).days + 1))
    return sum(1 for d in days if d.weekday() < 5 and not CALENDAR.holiday_name(d))


def _option(price: int, median: float, sigma: float, trip: tuple[date, date], note: str) -> TripOption:
    depart, ret = trip
    return TripOption(
        candidate_id=0, tracker_id=0, origin="JFK", dest_airport="", return_airport="",
        depart_date=depart, return_date=ret, evening_departure=False, price=Decimal(price), currency="USD",
        pto_cost=_pto(depart, ret), days_away=(ret - depart).days + 1, season_rating="good",
        weather_note=note,
        carrier=None, stops=None, overnight=None, deep_link=None, deal_level="good", go_now=0, state="new",
        median=median, sigma=sigma, bar=bar_geometry(Decimal(price), median, sigma),
    )  # fmt: skip


def sample_deal(geo: Geo, today: date) -> DestinationSummary:
    """A good deal on the dates the example calendar marks free."""
    azores = geo.destination("AZORES")
    trip = _option(578, 655, 45, example_trip(today), "Mild all year, 15–25°C")
    return DestinationSummary(0, azores.code, azores.name, palette(azores), (7, 10), trip, None, None)


def sample_rare(geo: Geo, today: date) -> DestinationSummary:
    """A standout: a great fare that dips like it usually end within two days (what the Rare tag says)."""
    madeira = geo.destination("MADEIRA")
    trip = replace(
        _option(468, 690, 60, example_trip(today, MONTHS_AHEAD + 1), "Mild all year, 17–25°C"),
        deal_level="great", expected_days=2, standout=True,
    )  # fmt: skip
    return DestinationSummary(0, madeira.code, madeira.name, palette(madeira), (6, 9), trip, None, None)


@dataclass(frozen=True)
class Landing:
    hero: Palette  # the colour under the hero photo, shown if the photo fails to load
    hero_photo: PlacePhoto | None
    calendar: list  # [(month name, weeks of day cells)], as the year planner's month_tables takes
    deal: DestinationSummary
    rare: DestinationSummary
    photos: dict[str, PlacePhoto]


def landing(geo: Geo, today: date) -> Landing:
    """Everything the landing page shows. Reads geo.yaml only, never the database."""
    photos = builtin_photos()
    trip = example_trip(today)
    month = trip[0]
    weeks = _month_weeks(month.year, month.month, CALENDAR, [trip])
    return Landing(
        hero=palette(geo.destination(HERO_PLACE)),
        hero_photo=photos.get(HERO_PLACE),
        calendar=[(f"{calendar.month_name[month.month]} {month.year}", weeks)],
        deal=sample_deal(geo, today),
        rare=sample_rare(geo, today),
        photos=photos,
    )
