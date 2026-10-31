"""Fixed, illustrative examples for the landing page. Never real travelers' trips."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Geo, palette
from ptopilot.photos import PlacePhoto, builtin_photos
from ptopilot.web.history import DestinationSummary, TripOption
from ptopilot.web.planner_view import _month_weeks
from ptopilot.web.viz import bar_geometry

HERO_PLACE = "PATAGONIA"  # Torres del Paine: the landing page's full-width photo
EXAMPLE_TRIP = (date(2027, 3, 5), date(2027, 3, 15))  # the dates marked free in the example calendar


def _option(
    price: int, median: float, sigma: float, depart: date, ret: date, pto: int, note: str
) -> TripOption:
    return TripOption(
        candidate_id=0, tracker_id=0, origin="JFK", dest_airport="", return_airport="",
        depart_date=depart, return_date=ret, evening_departure=False, price=Decimal(price), currency="USD",
        pto_cost=pto, days_away=(ret - depart).days + 1, season_rating="good", weather_note=note,
        carrier=None, stops=None, overnight=None, deep_link=None, deal_level="good", go_now=0, state="new",
        median=median, sigma=sigma, bar=bar_geometry(Decimal(price), median, sigma),
    )  # fmt: skip


def sample_cards(geo: Geo) -> list[DestinationSummary]:
    azores, patagonia = geo.destination("AZORES"), geo.destination("PATAGONIA")
    return [
        DestinationSummary(
            0, azores.code, azores.name, palette(azores), (7, 10),
            _option(578, 655, 45, *EXAMPLE_TRIP, 6, "Mild, ~16°C"),
            None, None,
        ),
        DestinationSummary(
            0, patagonia.code, "Patagonia", palette(patagonia), (7, 11),
            _option(1239, 1330, 90, date(2027, 3, 5), date(2027, 3, 14), 5, "Trekking season, 5–14°C"),
            None, None,
        ),
    ]  # fmt: skip


def sample_rare(geo: Geo) -> DestinationSummary:
    """A standout: a great fare that dips like it usually end within two days (what the Rare tag says)."""
    madeira = geo.destination("MADEIRA")
    trip = replace(
        _option(468, 690, 60, date(2027, 4, 9), date(2027, 4, 18), 5, "Spring, ~19°C"),
        deal_level="great", expected_days=2, standout=True,
    )  # fmt: skip
    return DestinationSummary(0, madeira.code, madeira.name, palette(madeira), (6, 9), trip, None, None)


@dataclass(frozen=True)
class Landing:
    hero: DestinationSummary  # only its palette and name are shown, under the photo
    hero_photo: PlacePhoto | None
    calendar: list  # [(month name, weeks of day cells)], as the year planner's month_tables takes
    deal: DestinationSummary
    rare: DestinationSummary
    photos: dict[str, PlacePhoto]


def landing(geo: Geo) -> Landing:
    """Everything the landing page shows. Reads geo.yaml only, never the database."""
    photos = builtin_photos()
    cards = sample_cards(geo)
    weeks = _month_weeks(2027, 3, WorkCalendar("US"), [EXAMPLE_TRIP])
    return Landing(
        hero=next(c for c in cards if c.code == HERO_PLACE),
        hero_photo=photos.get(HERO_PLACE),
        calendar=[("March 2027", weeks)],
        deal=cards[0],
        rare=sample_rare(geo),
        photos=photos,
    )
