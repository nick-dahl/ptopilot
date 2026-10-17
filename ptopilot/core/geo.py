"""Airports, destinations, and travel-time rules between zones."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# Destination colors for the web app and digest: a destination's own `color`, else its zone's default.
ZONE_COLORS = {
    "EUROPE": "#0e7490",
    "S_AMERICA": "#7c2d12",
    "SE_ASIA": "#047857",
    "E_ASIA": "#be123c",
    "NA": "#1d4ed8",
}
NEUTRAL_COLOR = "#374151"
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


class UnknownCodeError(KeyError):
    pass


@dataclass(frozen=True)
class Airport:
    code: str
    country: str
    zone: str


@dataclass(frozen=True)
class Destination:
    code: str
    name: str
    kind: str  # "city", "region", or "route"
    airports: tuple[str, ...]  # where you fly in
    country: str
    zone: str
    return_airports: tuple[str, ...] = ()  # where you fly home from; empty means the same as `airports`
    color: str | None = None  # "#rrggbb"; None means the zone default

    @property
    def home_from(self) -> tuple[str, ...]:
        return self.return_airports or self.airports

    @property
    def open_jaw(self) -> bool:
        return bool(self.return_airports) and self.return_airports != self.airports


@dataclass(frozen=True)
class Palette:
    color: str  # headers, dots, accents
    tint: str  # the light "typical price" band


def tint(color: str, amount: float = 0.25) -> str:
    """`amount` of the color mixed into white."""
    rgb = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(255 - (255 - c) * amount):02x}" for c in rgb)


NEUTRAL_PALETTE = Palette(NEUTRAL_COLOR, tint(NEUTRAL_COLOR))


def palette(dest: Destination) -> Palette:
    color = dest.color or ZONE_COLORS.get(dest.zone, NEUTRAL_COLOR)
    return Palette(color, tint(color))


@dataclass(frozen=True)
class TravelRule:
    overhead_days: float  # round-trip travel days subtracted from time on the ground
    min_trip_days: int  # shortest trip worth taking between these zones


class Geo:
    def __init__(
        self,
        airports: dict[str, Airport],
        destinations: dict[str, Destination],
        rules: dict[frozenset[str], TravelRule],
        default_rule: TravelRule,
    ):
        self._airports = airports
        self._destinations = destinations
        self._rules = rules
        self._default_rule = default_rule

    @classmethod
    def from_dict(cls, data: dict) -> Geo:
        airports = {code: Airport(code, a["country"], a["zone"]) for code, a in data["airports"].items()}
        destinations: dict[str, Destination] = {}
        for code, d in data["destinations"].items():
            codes = tuple(d["airports"])
            returns = tuple(d.get("return_airports") or ())
            missing = [c for c in codes + returns if c not in airports]
            if missing:
                raise ValueError(f"Destination {code!r} uses unknown airports {missing}")
            color = d.get("color")
            if color is not None and not (isinstance(color, str) and _HEX.fullmatch(color)):
                raise ValueError(f"Destination {code!r} has an invalid color {color!r} (expected #rrggbb)")
            first = airports[codes[0]]
            destinations[code] = Destination(
                code, d["name"], d["kind"], codes, first.country, first.zone, returns,
                color.lower() if color else None,
            )  # fmt: skip
        travel = data["travel"]
        rules = {
            frozenset(p["zones"]): TravelRule(float(p["overhead_days"]), int(p["min_trip_days"]))
            for p in travel["pairs"]
        }
        default = TravelRule(
            float(travel["default"]["overhead_days"]), int(travel["default"]["min_trip_days"])
        )
        return cls(airports, destinations, rules, default)

    @classmethod
    def from_yaml(cls, path: Path) -> Geo:
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def airport(self, code: str) -> Airport:
        try:
            return self._airports[code]
        except KeyError:
            raise UnknownCodeError(f"Unknown airport: {code!r}") from None

    def destinations(self) -> list[Destination]:
        """Every known destination, sorted by name."""
        return sorted(self._destinations.values(), key=lambda d: d.name)

    def destination(self, code: str) -> Destination:
        try:
            return self._destinations[code]
        except KeyError:
            raise UnknownCodeError(f"Unknown destination: {code!r}") from None

    def travel_rule(self, origin: str, dest: Destination) -> TravelRule:
        key = frozenset({self.airport(origin).zone, dest.zone})
        return self._rules.get(key, self._default_rule)

    def is_international(self, origin: str, dest: Destination) -> bool:
        return self.airport(origin).country != dest.country
