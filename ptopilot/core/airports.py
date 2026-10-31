"""Bundled airport catalog (OurAirports, scheduled service only) with place search."""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import yaml

from ptopilot import config

_SIZE_ORDER = {"large": 0, "medium": 1, "small": 2}
_E_ASIA = {"JP", "KR", "CN", "TW", "HK", "MO", "MN"}
_SE_ASIA = {"TH", "VN", "KH", "LA", "MY", "SG", "ID", "PH", "MM", "BN", "TL"}
_CONTINENT_ZONES = {"EU": "EUROPE", "NA": "NA", "SA": "S_AMERICA", "AF": "AFRICA", "OC": "OCEANIA"}
_EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class CatalogAirport:
    code: str
    name: str
    city: str
    country: str
    continent: str
    lat: float
    lon: float
    size: str  # "large" | "medium" | "small"


@dataclass(frozen=True)
class PlaceMatch:
    airport: CatalogAirport
    nearby: tuple[CatalogAirport, ...]
    country_name: str


def distance_km(a: CatalogAirport, b: CatalogAirport) -> float:
    """Great-circle (haversine) distance in kilometres."""
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dlam = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def zone_for(country: str, continent: str) -> str:
    """Travel-rule zone for a country; Asia splits into East and Southeast, the rest "OTHER"."""
    if continent == "AS":
        if country in _E_ASIA:
            return "E_ASIA"
        return "SE_ASIA" if country in _SE_ASIA else "OTHER"
    return _CONTINENT_ZONES.get(continent, "OTHER")


def _fold(text: str) -> str:
    """Lower-case and strip accents, so "cancun" finds "Cancún"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _read_rows(name: str) -> list[dict[str, str]]:
    text = resources.files("ptopilot.data").joinpath(name).read_text(encoding="utf-8")
    return list(csv.DictReader(text.splitlines()))


def _built_in_place_names() -> dict[str, tuple[str, ...]]:
    """geo.yaml place names by first airport, so "Azores" finds PDL and "Patagonia" finds PUQ."""
    text = resources.files("ptopilot.data").joinpath("geo.yaml").read_text(encoding="utf-8")
    names: dict[str, list[str]] = {}
    for d in yaml.safe_load(text)["destinations"].values():
        names.setdefault(d["airports"][0], []).append(_fold(re.sub(r"\s*\(.*\)", "", d["name"])))
    return {code: tuple(v) for code, v in names.items()}


class AirportCatalog:
    def __init__(
        self,
        airports: list[CatalogAirport],
        country_names: dict[str, str],
        place_names: dict[str, tuple[str, ...]] | None = None,
    ):
        self._place_names = place_names or {}  # airport code -> folded names of built-in places it opens
        self._by_code = {a.code: a for a in airports}
        self._country_names = country_names
        self._by_country: dict[str, list[CatalogAirport]] = {}
        for a in airports:
            self._by_country.setdefault(a.country, []).append(a)

    @staticmethod
    @lru_cache(maxsize=1)
    def load() -> AirportCatalog:
        airports = [
            CatalogAirport(
                code=r["code"],
                name=r["name"],
                city=r["city"],
                country=r["country"],
                continent=r["continent"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                size=r["size"],
            )
            for r in _read_rows("airports.csv")
        ]
        return AirportCatalog(
            airports, {r["code"]: r["name"] for r in _read_rows("countries.csv")}, _built_in_place_names()
        )

    def get(self, code: str) -> CatalogAirport | None:
        return self._by_code.get(code.strip().upper())

    def country_name(self, country: str) -> str:
        return self._country_names.get(country, country)

    def nearby(self, code: str, km: float = config.NEARBY_KM) -> list[CatalogAirport]:
        """Other airports in the same country within `km`, nearest first."""
        home = self.get(code)
        if home is None:
            return []
        found = [
            (d, a)
            for a in self._by_country.get(home.country, [])
            if a.code != home.code and (d := distance_km(home, a)) <= km
        ]
        return [a for _, a in sorted(found, key=lambda t: (t[0], t[1].code))]

    def within(
        self, code: str, km: float, sizes: frozenset[str] = frozenset({"large", "medium"})
    ) -> list[tuple[float, CatalogAirport]]:
        """Airports of the given sizes within `km` of `code`, in any country, nearest first."""
        home = self.get(code)
        if home is None:
            return []
        found = [
            (d, a)
            for a in self._by_code.values()
            if a.code != home.code and a.size in sizes and (d := distance_km(home, a)) <= km
        ]
        return sorted(found, key=lambda t: (t[0], t[1].code))

    def _match_kind(self, a: CatalogAirport, q: str, word: re.Pattern[str]) -> int | None:
        """0 code, 1 city, 2 country, 3 airport name; None when the airport doesn't match."""
        if a.code.lower() == q:
            return 0
        if _fold(a.city).startswith(q) or any(n.startswith(q) for n in self._place_names.get(a.code, ())):
            return 1
        if _fold(self.country_name(a.country)).startswith(q):
            return 2
        if word.search(_fold(a.name)):
            return 3
        return None

    def matches(self, query: str) -> list[tuple[int, bool, CatalogAirport]]:
        """Every airport matching `query`, best first, as (match kind, exact city or place, airport)."""
        q = _fold(query.strip())
        if not q:
            return []
        word = re.compile(r"\b" + re.escape(q) + r"\b")
        ranked = []
        for a in self._by_code.values():
            kind = self._match_kind(a, q, word)
            if kind is not None:
                # An exact code leads, then an exact city name ("Porto" before "Porto Velho"),
                # then bigger airports outrank match kind, and "International" airports lead
                # within a size. A country search ("Japan") relies on that last ordering to
                # surface HND and NRT among 28 large airports: the catalog has no traffic data.
                # Several airports in one exact city (LHR/LGW) need no tiebreak: each lists
                # the others as its nearby options.
                intl = 0 if "international" in a.name.lower() else 1
                exact = _fold(a.city) == q or q in self._place_names.get(a.code, ())
                ranked.append(((kind > 0, not exact, _SIZE_ORDER[a.size], kind, intl, a.name, a.code), a))
        ranked.sort(key=lambda t: t[0])
        return [(key[3], not key[1], a) for key, a in ranked]

    def search(self, query: str, limit: int = config.SEARCH_LIMIT) -> list[PlaceMatch]:
        return [
            PlaceMatch(a, tuple(self.nearby(a.code)), self.country_name(a.country))
            for _, _, a in self.matches(query)[:limit]
        ]
