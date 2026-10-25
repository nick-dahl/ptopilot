"""Bundled reference data (geography, seasons)."""

from pathlib import Path

from ptopilot.core.airports import AirportCatalog
from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable

DATA_DIR = Path(__file__).resolve().parent


def load_geo() -> Geo:
    return Geo.from_yaml(DATA_DIR / "geo.yaml", AirportCatalog.load())


def load_seasons() -> SeasonTable:
    return SeasonTable.from_yaml(DATA_DIR / "seasons.yaml")
