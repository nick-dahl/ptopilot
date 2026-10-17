"""Fixed, illustrative deal cards for the landing page. Never real travelers' trips."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ptopilot.core.geo import Geo, palette
from ptopilot.web.history import DestinationSummary, TripOption
from ptopilot.web.viz import bar_geometry


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
            _option(578, 655, 45, date(2027, 3, 5), date(2027, 3, 15), 6, "Mild, ~16°C"),
            None, None,
        ),
        DestinationSummary(
            0, patagonia.code, "Patagonia", palette(patagonia), (7, 11),
            _option(1239, 1330, 90, date(2027, 3, 5), date(2027, 3, 14), 5, "Trekking season, 5–14°C"),
            None, None,
        ),
    ]  # fmt: skip
