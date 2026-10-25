"""Bundled reference data (geography, seasons), plus the places users added in the database."""

from functools import cache
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ptopilot.core.airports import AirportCatalog, zone_for
from ptopilot.core.geo import Destination as GeoDestination
from ptopilot.core.geo import Geo
from ptopilot.core.seasons import RATINGS, SeasonTable
from ptopilot.db.models import Destination, DestinationSeason

DATA_DIR = Path(__file__).resolve().parent


def _geo_destination(row: Destination, catalog: AirportCatalog) -> GeoDestination:
    """Build a place from the airports the catalog still knows; never drop one, trackers reference it."""
    known = [a for code in row.airports if (a := catalog.get(code)) is not None]
    if known:
        country, zone = known[0].country, zone_for(known[0].country, known[0].continent)
    else:  # none left: the country is in the code (HND_JP), and the default travel rule applies
        country, zone = row.code.rsplit("_", 1)[-1], "OTHER"
    return GeoDestination(
        row.code,
        row.name,
        row.kind,
        tuple(row.airports),
        country,
        zone,
        tuple(row.return_airports or ()),
        row.color,
    )


@cache
def _yaml_geo() -> Geo:
    return Geo.from_yaml(DATA_DIR / "geo.yaml", AirportCatalog.load())


@cache
def _yaml_seasons() -> SeasonTable:
    return SeasonTable.from_yaml(DATA_DIR / "seasons.yaml")


def load_geo(engine: Engine | None = None) -> Geo:
    catalog = AirportCatalog.load()
    geo = _yaml_geo()  # parsed once; Geo and SeasonTable are never mutated, only copied
    if engine is None:
        return geo
    with Session(engine) as s:
        rows = s.scalars(select(Destination)).all()
    return geo.with_destinations({r.code: _geo_destination(r, catalog) for r in rows})


def load_seasons(engine: Engine | None = None) -> SeasonTable:
    table = _yaml_seasons()
    if engine is None:
        return table
    with Session(engine) as s:
        rows = s.scalars(select(DestinationSeason)).all()
    valid = {}
    for r in rows:
        if len(r.months) == 12 and all(m in RATINGS for m in r.months):
            valid[r.code] = {"months": r.months, "notes": r.notes}
    return table.merged_with(SeasonTable.from_dict(valid))
