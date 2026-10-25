"""Bundled reference data (geography, seasons), plus the places users added in the database."""

from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ptopilot.core.airports import AirportCatalog, zone_for
from ptopilot.core.geo import Destination as GeoDestination
from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.db.models import Destination, DestinationSeason

DATA_DIR = Path(__file__).resolve().parent


def _geo_destination(row: Destination, catalog: AirportCatalog) -> GeoDestination | None:
    first = catalog.get(row.airports[0]) if row.airports else None
    if first is None:
        return None  # an airport no longer in the catalog: skip the place rather than fail every load
    return GeoDestination(
        row.code,
        row.name,
        row.kind,
        tuple(row.airports),
        first.country,
        zone_for(first.country, first.continent),
        tuple(row.return_airports or ()),
        row.color,
    )


def load_geo(engine: Engine | None = None) -> Geo:
    catalog = AirportCatalog.load()
    geo = Geo.from_yaml(DATA_DIR / "geo.yaml", catalog)
    if engine is None:
        return geo
    with Session(engine) as s:
        rows = s.scalars(select(Destination)).all()
    found = (_geo_destination(r, catalog) for r in rows)
    return geo.with_destinations({d.code: d for d in found if d is not None})


def load_seasons(engine: Engine | None = None) -> SeasonTable:
    table = SeasonTable.from_yaml(DATA_DIR / "seasons.yaml")
    if engine is None:
        return table
    with Session(engine) as s:
        rows = s.scalars(select(DestinationSeason)).all()
    extra = SeasonTable.from_dict(
        {r.code: {"months": r.months, "notes": r.notes} for r in rows},
    )
    return table.merged_with(extra)
