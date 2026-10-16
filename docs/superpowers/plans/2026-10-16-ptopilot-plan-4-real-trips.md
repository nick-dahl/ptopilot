# ptopilot Plan 4: Your Real Trips (destinations, open-jaw, search horizon, profile loader)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the daily scan collecting price history for the author's real trips: Patagonia (W Trek), the Azores, Madeira, and the Camino Portugués (fly into Porto, home from Santiago: **open-jaw**) from JFK/EWR/PHL in March and October 2027. Also fix the trip-selection and exploration behaviour that real data exposed.

**Architecture:**
- **Open-jaw** is a destination property (`return_airports` in `geo.yaml`). It flows through the planner (arrival × return airport pairs), the sources (`ExactQuery.return_from`, `supports_open_jaw`, SerpApi multi-city) and the database (`return_airport` on route queries, observations and baselines). Every pipeline key includes it.
- **Search horizon:** the shortlist skips departures more than 300 days out.
- **Exploration:** ordered by `live_checks` (so "no flights" counts as checked), and it fills check slots that deals don't use.
- **Trip selection:** spreads across departure weeks.
- **Profiles:** a YAML loader stands in for onboarding until the web app exists.

**Tech Stack:** unchanged (Python 3.12+, SQLAlchemy/Alembic/psycopg, httpx, fast-flights, pytest).

**Spec:** [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](../specs/2026-10-16-ptopilot-design.md): §6.4 (revised diversity), §6.7 (open-jaw), §6.8 (search horizon), §6.9 (profiles), and §7 "Implementation notes (Plan 3)" (exploration, revised).

**Plan sequence change:** the digest becomes **Plan 5** and the web app **Plan 6**, so price history for real trips starts accumulating before the digest is tuned.

## Global Constraints

- No new dependencies.
- Every tunable number stays in `ptopilot/config.py`. New this plan: `TOP_SHAPES_PER_WINDOW = 8`, `MAX_SHAPES_PER_LENGTH = 3`, `MAX_SHAPES_PER_WEEK = 2`, `LIVE_HORIZON_DAYS = 300`.
- Default `pytest` never touches the network. Database tests run with `PTOPILOT_REQUIRE_DB=1`, as in every command below.
- `ruff check .` and `ruff format --check .` must pass.
- **Work directly on `main`; every task ends with a commit and a `git push`, and the *full* suite must be green after each task.** That's why the database change and the pipeline change are one task (4): the new NOT NULL columns break the pipeline until both land. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Never commit `profiles/*.yaml` other than `profiles/example.yaml`.** Profiles hold personal email addresses, and `.gitignore` enforces this from Task 5.
- Commands run from `C:\Users\nickd\dev\ptopilot` with `.venv/Scripts/python`. The local Postgres must be running (port 5433).

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **An open-jaw route when the only live source is Google** (SerpApi unconfigured or out of budget) → the route is counted as `no_open_jaw_source`, Google's circuit breaker is never tripped, and the stage doesn't fail. *Task 4: `test_open_jaw_without_a_capable_source_is_counted_not_failed`, `test_open_jaw_goes_only_to_capable_sources_without_tripping_the_breaker`.*
2. **A round trip and an open-jaw trip into the same airport on the same dates** → kept apart in route queries, prices and baselines. *Task 4: the `return_airport` unique constraint plus every key in `queries.py`, exercised by `test_open_jaw_end_to_end_produces_candidates`.*
3. **Destination codes longer than 8 characters** (`CAMINO_PORTUGUES`, `PATAGONIA`) → stored without truncation errors. *Task 4: every `test_open_jaw_*` test inserts a `CAMINO_PORTUGUES` tracker.*
4. **A window with no holidays**, where every week ties on PTO efficiency → trips spread across the window instead of bunching at its start. *Task 2: `test_select_top_spreads_across_departure_weeks`.*
5. **A profile file with several mistakes** → all of them reported at once, and nothing written. *Task 5: `test_every_problem_is_reported_at_once`, `test_missing_fields_and_typos_are_rejected`.*

## Verified before writing (2026-10-16)

- **Real API behaviour:**
  - fast-flights 3.1 multi-city raises `IndexError` inside the library, while round trips on the same dates work.
  - Google Flights returns nothing for departures in September or October 2027.
  - A SerpApi `type=3` search (JFK→OPO Mar 6, SCQ→JFK Mar 21, 2027) returned 8 open-jaw itineraries, cheapest $959 on Iberia, with no `price_insights`. That's the Task 3 fixture.
- **Migration 0004** was tested in both directions against a database holding existing round-trip rows.
- **All five tasks replayed in order** on a fresh copy of `main` (scratchpad `sim_plan4.sh`). Each task's new tests failed for the expected reasons, then passed, with the **full suite green and lint clean after every task** (231 → 235 → 240 → 248 → 253). The replayed tree matched the verified copy exactly.
- **The author's real profile** loaded into a throwaway database:
  - `expand` produced 138 route queries (69 within the horizon).
  - Departures spread from Feb 27 to Mar 19 and from Oct 1 to Oct 23.
  - `shortlist` picked 40 exploration checks.
- Verified files are in the scratchpad at `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p4`.

## File structure

```
ptopilot/
  config.py                    # + MAX_SHAPES_PER_WEEK, LIVE_HORIZON_DAYS; top-8 / 3-per-length (replace whole file)
  core/geo.py                  # Destination.return_airports, home_from, open_jaw
  core/selection.py            # select_top(max_per_week=...)
  core/planner.py              # PlannedItinerary.return_airport; arrival x return fan-out
  data/geo.yaml                # + PHL, OPO, PDL, FNC, SCQ, PUQ; PATAGONIA, AZORES, MADEIRA, CAMINO_PORTUGUES; NA/EUROPE<->S_AMERICA
  data/seasons.yaml            # + season ratings for the four new destinations
  sources/base.py              # ExactQuery.return_from + open_jaw; ExactSearchSource.supports_open_jaw
  sources/google_flights.py    # supports_open_jaw = False; refuses open-jaw queries
  sources/serpapi.py           # supports_open_jaw = True; type=3 multi_city_json
  db/models.py                 # return_airport on RouteQuery/PriceObservation/RouteBaseline; destination_code 32 chars
  db/migrations/versions/0004_open_jaw_return_airport.py   # hand-written (backfill + PK rebuild)
  pipeline/queries.py          # every key includes return_airport
  pipeline/expand.py, broad_scan.py, shortlist.py, live_verify.py, baselines.py, score.py
  profiles.py                  # parse_profile, apply_profile, CLI
profiles/example.yaml          # committed template (profiles/* otherwise git-ignored)
.gitignore, README.md
tests/core/{test_geo,test_planner,test_selection}.py
tests/sources/{test_base,test_serpapi,test_google_flights,test_real_recordings}.py
tests/sources/fixtures/real_serpapi_multicity_JFK-OPO_SCQ-JFK_2027-03.json
tests/db/{test_models,test_pipeline_tables}.py
tests/pipeline/{conftest,test_shortlist,test_score,test_open_jaw}.py
tests/test_profiles.py
```

Most tasks modify existing files. Each "Write" step gives the **complete new file**; replace the old one.

---

### Task 1: Destinations, open-jaw geography, season ratings

**Files:**
- Modify: `ptopilot/core/geo.py`, `ptopilot/data/geo.yaml`, `ptopilot/data/seasons.yaml`
- Test: `tests/core/test_geo.py`

**Interfaces:**
- Produces: `Destination.return_airports: tuple[str, ...] = ()` (new last field), `Destination.home_from -> tuple[str, ...]` (return airports, or `airports` if none), `Destination.open_jaw -> bool`; `geo.yaml` destinations `PATAGONIA [PUQ]`, `AZORES [PDL]`, `MADEIRA [FNC]`, `CAMINO_PORTUGUES [OPO] → return [SCQ]`; airports `PHL, OPO, PDL, FNC, SCQ, PUQ`; travel rules NA↔S_AMERICA and EUROPE↔S_AMERICA (3 overhead days, 9-day minimum).

The season ratings are hand-written. Patagonia uses southern-hemisphere seasons, so May–September is `avoid` (refugios closed, cold), October `shoulder`, and March `good`. Camino winters (Nov–Feb) are `avoid`. The Azores and Madeira are never cold, so their wet winters are only `shoulder`.

- [ ] **Step 1: Write the failing test file** `tests/core/test_geo.py`

```python
import pytest

from ptopilot.core.geo import Geo, TravelRule, UnknownCodeError

DATA = {
    "airports": {
        "ORD": {"country": "US", "zone": "NA"},
        "LAX": {"country": "US", "zone": "NA"},
        "BKK": {"country": "TH", "zone": "SE_ASIA"},
        "HKT": {"country": "TH", "zone": "SE_ASIA"},
    },
    "destinations": {
        "TH": {"name": "Thailand", "kind": "region", "airports": ["BKK", "HKT"]},
        "LAX": {"name": "Los Angeles", "kind": "city", "airports": ["LAX"]},
    },
    "travel": {
        "default": {"overhead_days": 1, "min_trip_days": 2},
        "pairs": [{"zones": ["NA", "SE_ASIA"], "overhead_days": 3, "min_trip_days": 9}],
    },
}
GEO = Geo.from_dict(DATA)


def test_destination_takes_country_and_zone_from_first_airport():
    th = GEO.destination("TH")
    assert th.airports == ("BKK", "HKT")
    assert (th.country, th.zone) == ("TH", "SE_ASIA")


def test_travel_rule_for_known_pair():
    assert GEO.travel_rule("ORD", GEO.destination("TH")) == TravelRule(3.0, 9)


def test_travel_rule_falls_back_to_default():
    assert GEO.travel_rule("ORD", GEO.destination("LAX")) == TravelRule(1.0, 2)


def test_is_international():
    assert GEO.is_international("ORD", GEO.destination("TH"))
    assert not GEO.is_international("ORD", GEO.destination("LAX"))


def test_unknown_codes_are_clear_errors():
    with pytest.raises(UnknownCodeError, match="ZZZ"):
        GEO.destination("ZZZ")
    with pytest.raises(UnknownCodeError, match="XXX"):
        GEO.airport("XXX")


def test_destination_with_unknown_airport_is_rejected():
    bad = {**DATA, "destinations": {"X": {"name": "X", "kind": "city", "airports": ["NOPE"]}}}
    with pytest.raises(ValueError, match="NOPE"):
        Geo.from_dict(bad)


def test_open_jaw_destination_has_separate_return_airports():
    data = {
        **DATA,
        "airports": {
            **DATA["airports"],
            "OPO": {"country": "PT", "zone": "EUROPE"},
            "SCQ": {"country": "ES", "zone": "EUROPE"},
        },
        "destinations": {
            "CAMINO": {"name": "Camino", "kind": "route", "airports": ["OPO"], "return_airports": ["SCQ"]}
        },
    }
    camino = Geo.from_dict(data).destination("CAMINO")
    assert (camino.airports, camino.home_from, camino.open_jaw) == (("OPO",), ("SCQ",), True)
    assert (camino.country, camino.zone) == ("PT", "EUROPE")


def test_ordinary_destination_flies_home_from_where_it_arrived():
    th = GEO.destination("TH")
    assert th.home_from == ("BKK", "HKT") and th.open_jaw is False


def test_unknown_return_airport_is_rejected():
    bad = {
        **DATA,
        "destinations": {
            "X": {"name": "X", "kind": "route", "airports": ["BKK"], "return_airports": ["NOPE"]}
        },
    }
    with pytest.raises(ValueError, match="NOPE"):
        Geo.from_dict(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/core/test_geo.py -q`
Expected: 3 failed, 6 passed: `test_open_jaw_destination_has_separate_return_airports` and `test_ordinary_destination_flies_home_from_where_it_arrived` with `AttributeError: 'Destination' object has no attribute 'home_from'`; `test_unknown_return_airport_is_rejected` with `DID NOT RAISE ValueError`.

- [ ] **Step 3: Write** `ptopilot/core/geo.py`

```python
"""Airports, destinations, and travel-time rules between zones."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


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

    @property
    def home_from(self) -> tuple[str, ...]:
        return self.return_airports or self.airports

    @property
    def open_jaw(self) -> bool:
        return bool(self.return_airports) and self.return_airports != self.airports


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
            first = airports[codes[0]]
            destinations[code] = Destination(
                code, d["name"], d["kind"], codes, first.country, first.zone, returns
            )
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
```

- [ ] **Step 4: Write** `ptopilot/data/geo.yaml`

```yaml
# Seed geography. Extend as friends add destinations.
# zone: coarse region used for travel-time rules; country: ISO 3166 alpha-2.
airports:
  ORD: {country: US, zone: NA}
  MDW: {country: US, zone: NA}
  JFK: {country: US, zone: NA}
  EWR: {country: US, zone: NA}
  LGA: {country: US, zone: NA}
  PHL: {country: US, zone: NA}
  SFO: {country: US, zone: NA}
  LAX: {country: US, zone: NA}
  LHR: {country: GB, zone: EUROPE}
  LGW: {country: GB, zone: EUROPE}
  LIS: {country: PT, zone: EUROPE}
  OPO: {country: PT, zone: EUROPE}
  PDL: {country: PT, zone: EUROPE}  # Ponta Delgada, Azores
  FNC: {country: PT, zone: EUROPE}  # Funchal, Madeira
  SCQ: {country: ES, zone: EUROPE}  # Santiago de Compostela
  PUQ: {country: CL, zone: S_AMERICA}  # Punta Arenas (gateway to Torres del Paine)
  BKK: {country: TH, zone: SE_ASIA}
  HKT: {country: TH, zone: SE_ASIA}
  CNX: {country: TH, zone: SE_ASIA}
  HND: {country: JP, zone: E_ASIA}
  NRT: {country: JP, zone: E_ASIA}

destinations:
  TH: {name: Thailand, kind: region, airports: [BKK, HKT, CNX]}
  LIS: {name: Lisbon, kind: city, airports: [LIS]}
  TYO: {name: Tokyo, kind: city, airports: [HND, NRT]}
  PATAGONIA: {name: "Patagonia (W Trek)", kind: region, airports: [PUQ]}
  AZORES: {name: Azores, kind: region, airports: [PDL]}
  MADEIRA: {name: Madeira, kind: region, airports: [FNC]}
  # Open-jaw: fly into the first list, home from the second.
  CAMINO_PORTUGUES: {name: "Camino Portugués (Porto → Santiago)", kind: route, airports: [OPO], return_airports: [SCQ]}

# overhead_days: round-trip travel days subtracted from time on the ground.
# min_trip_days: shortest trip worth taking between the two zones.
travel:
  default: {overhead_days: 1, min_trip_days: 2}
  pairs:
    - {zones: [NA, NA], overhead_days: 1, min_trip_days: 3}
    - {zones: [NA, EUROPE], overhead_days: 2, min_trip_days: 5}
    - {zones: [NA, SE_ASIA], overhead_days: 3, min_trip_days: 9}
    - {zones: [NA, E_ASIA], overhead_days: 2.5, min_trip_days: 7}
    - {zones: [EUROPE, EUROPE], overhead_days: 1, min_trip_days: 2}
    - {zones: [EUROPE, SE_ASIA], overhead_days: 2.5, min_trip_days: 8}
    - {zones: [EUROPE, E_ASIA], overhead_days: 2.5, min_trip_days: 7}
    - {zones: [NA, S_AMERICA], overhead_days: 3, min_trip_days: 9}
    - {zones: [EUROPE, S_AMERICA], overhead_days: 3, min_trip_days: 9}
```

- [ ] **Step 5: Write** `ptopilot/data/seasons.yaml`

```yaml
# Hand-seeded season ratings, Jan..Dec. Keys: destination code or country code.
# Plan 4 adds scripts/generate_seasons.py to draft more entries from Open-Meteo climate normals.
TH:
  months: [good, good, shoulder, shoulder, shoulder, shoulder, shoulder, shoulder, avoid, avoid, good, good]
  notes:
    1: "Cool, dry season; peak crowds"
    4: "Hottest month, often 35°C+"
    6: "Start of rainy season; short afternoon downpours"
    9: "Wettest month; flooding possible"
    10: "Heavy rain tapering late in the month"
    11: "Dry season begins"
LIS:
  months: [shoulder, shoulder, shoulder, shoulder, good, good, good, good, good, good, shoulder, shoulder]
  notes:
    1: "Mild but rainy, ~15°C"
    6: "Warm and dry, ~26°C; festival season"
    8: "Hot, ~29°C; busiest month"
TYO:
  months: [shoulder, shoulder, good, good, good, shoulder, shoulder, shoulder, shoulder, good, good, shoulder]
  notes:
    4: "Cherry blossom season; book early"
    6: "Rainy season (tsuyu)"
    8: "Hot and humid, ~31°C"
    9: "Typhoon season peaks"
    11: "Autumn leaves, clear skies"
PATAGONIA:  # Torres del Paine; southern-hemisphere seasons, refugios mostly open Oct-Apr
  months: [good, good, good, shoulder, avoid, avoid, avoid, avoid, avoid, shoulder, good, good]
  notes:
    3: "Autumn: fewer crowds, colors turning, ~5-14°C"
    10: "Early spring: windy and cold (~0-12°C), some services just reopening"
    12: "Peak summer: long days, busiest, book refugios early"
AZORES:  # mild all year; winters wet and windy rather than cold
  months: [shoulder, shoulder, shoulder, shoulder, good, good, good, good, good, good, shoulder, shoulder]
  notes:
    3: "Mild (~16°C) but rainy and changeable"
    10: "Warm sea, ~20°C, rain starting to pick up"
MADEIRA:  # 'island of eternal spring'
  months: [shoulder, shoulder, good, good, good, good, good, good, good, good, shoulder, shoulder]
  notes:
    3: "Spring flowers, ~19°C; some showers in the north"
    10: "~23°C, warm sea; levada walks in good shape"
CAMINO_PORTUGUES:  # walking Porto -> Santiago
  months: [avoid, avoid, shoulder, good, good, good, shoulder, shoulder, good, good, avoid, avoid]
  notes:
    3: "Cool (~14°C) and often rainy in Galicia; quiet albergues"
    10: "Pleasant walking (~18°C), rain more likely late in the month"
    7: "Hot inland and the busiest month"
```

- [ ] **Step 6: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/core/test_geo.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **231 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 7: Commit and push**

```bash
git add ptopilot/core/geo.py ptopilot/data/geo.yaml ptopilot/data/seasons.yaml tests/core/test_geo.py
git commit -m "feat(core): open-jaw destinations; Patagonia, Azores, Madeira, Camino Portugues" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Planner open-jaw fan-out and week-spread trip selection

**Files:**
- Modify: `ptopilot/config.py`, `ptopilot/core/selection.py`, `ptopilot/core/planner.py`
- Test: `tests/core/test_planner.py`, `tests/core/test_selection.py`

**Interfaces:**
- Consumes: `Destination.home_from/open_jaw` (Task 1).
- Produces: `PlannedItinerary.return_airport: str` (new required last field) and `.open_jaw`; `select_top(shapes, n=6, max_per_length=2, max_per_week=None)`; planner passes `config.TOP_SHAPES_PER_WINDOW` (8), `MAX_SHAPES_PER_LENGTH` (3) and `MAX_SHAPES_PER_WEEK` (2). `config.LIVE_HORIZON_DAYS = 300` is added now and used in Task 4.

Why the weekly cap: in a window with no holidays every week has the same PTO efficiency, and ties break toward earlier dates. In the real profile, every March trip left in the first two weeks. Why 3-per-length: each destination only has about three possible trip lengths, so "2 per length" quietly capped every window at 6 trips.

- [ ] **Step 1: Write the failing test file** `tests/core/test_planner.py`

```python
from datetime import date

import pytest

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.planner import TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.core.selection import ground_days
from ptopilot.data import load_geo, load_seasons

GEO = load_geo()
SEASONS = load_seasons()
JUNE = Window(date(2027, 6, 1), date(2027, 6, 30))
SEPT = Window(date(2027, 9, 1), date(2027, 9, 30))
THAILAND = TrackerSpec("TH", min_stay_days=7, max_stay_days=12)


def profile(**overrides):
    base = {
        "home_airports": ("ORD",),
        "calendar": WorkCalendar.from_code("US"),
        "pto_available": 10,
        "min_trip_days": 3,
        "max_trip_days": 16,
        "weather_tolerance": "normal",
        "friday_evening_departure": False,
    }
    return TravelerProfile(**(base | overrides))


def test_shipped_data_files_load():
    assert GEO.destination("TH").airports == ("BKK", "HKT", "CNX")
    assert SEASONS.rating(["TH"], 9) == "avoid"


def test_thailand_in_june_but_not_rainy_september():
    its = plan_itineraries(profile(), THAILAND, [JUNE, SEPT], GEO, SEASONS)
    assert its
    assert {i.month for i in its} == {6}
    assert {i.season_rating for i in its} == {"shoulder"}


def test_relaxed_tolerance_keeps_september():
    its = plan_itineraries(profile(weather_tolerance="relaxed"), THAILAND, [JUNE, SEPT], GEO, SEASONS)
    assert {i.month for i in its} == {6, 9}


def test_every_itinerary_respects_limits():
    its = plan_itineraries(profile(), THAILAND, [JUNE], GEO, SEASONS)
    for i in its:
        s = i.shape
        assert 9 <= s.days_away <= 16  # NA -> SE_ASIA minimum is 9
        assert 7 <= ground_days(s, 3) <= 12
        assert s.pto_cost <= 10


def test_fans_out_across_destination_airports_and_caps_shapes():
    its = plan_itineraries(profile(), THAILAND, [JUNE], GEO, SEASONS)
    shapes = {i.shape for i in its}
    assert 0 < len(shapes) <= 6
    assert len(its) == len(shapes) * 3  # BKK, HKT, CNX
    assert {i.dest_airport for i in its} == {"BKK", "HKT", "CNX"}


def test_each_home_airport_gets_its_own_itineraries():
    its = plan_itineraries(profile(home_airports=("ORD", "MDW")), THAILAND, [JUNE], GEO, SEASONS)
    assert {i.origin for i in its} == {"ORD", "MDW"}


def test_overlapping_windows_do_not_duplicate_itineraries():
    early_june = Window(date(2027, 6, 1), date(2027, 6, 20))
    its = plan_itineraries(profile(), THAILAND, [JUNE, early_june], GEO, SEASONS)
    keys = [(i.origin, i.dest_airport, i.shape) for i in its]
    assert len(keys) == len(set(keys))


def test_zero_pto_left_only_allows_free_trips():
    # Company gives Tue-Wed after Memorial Day off: Sat May 29 -> Wed Jun 2 costs 0 PTO.
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 6, 1), date(2027, 6, 2)])
    lisbon = TrackerSpec("LIS", min_stay_days=1, max_stay_days=5)
    memorial = Window(date(2027, 5, 27), date(2027, 6, 6))
    its = plan_itineraries(profile(calendar=cal, pto_available=0), lisbon, [memorial], GEO, SEASONS)
    assert [(i.shape.depart_date, i.shape.return_date) for i in its] == [
        (date(2027, 5, 29), date(2027, 6, 2))
    ]
    assert its[0].shape.pto_cost == 0


def test_negative_pto_is_treated_as_zero():
    its = plan_itineraries(profile(pto_available=-3), THAILAND, [JUNE], GEO, SEASONS)
    assert its == []


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        TrackerSpec("TH", min_stay_days=10, max_stay_days=5)
    with pytest.raises(ValueError):
        Window(date(2027, 6, 30), date(2027, 6, 1))


def test_inverted_trip_length_range_is_rejected():
    with pytest.raises(ValueError, match="10"):
        profile(min_trip_days=10, max_trip_days=5)


NYC = ("JFK", "EWR", "PHL")


def test_open_jaw_route_pairs_arrival_and_return_airports():
    camino = TrackerSpec("CAMINO_PORTUGUES", min_stay_days=11, max_stay_days=14)
    march = Window(date(2027, 3, 1), date(2027, 3, 31))
    its = plan_itineraries(
        profile(home_airports=NYC, weather_tolerance="relaxed"), camino, [march], GEO, SEASONS
    )
    assert its
    assert {(i.dest_airport, i.return_airport) for i in its} == {("OPO", "SCQ")}
    assert all(i.open_jaw for i in its)
    assert {i.origin for i in its} == set(NYC)


def test_round_trips_return_from_the_arrival_airport():
    its = plan_itineraries(profile(), THAILAND, [JUNE], GEO, SEASONS)
    assert all(i.return_airport == i.dest_airport and not i.open_jaw for i in its)


def test_new_destinations_load_with_seasons():
    for code in ("PATAGONIA", "AZORES", "MADEIRA", "CAMINO_PORTUGUES"):
        dest = GEO.destination(code)
        assert SEASONS.rating([dest.code, dest.country], 3) in ("good", "shoulder", "avoid")
    assert SEASONS.rating(["PATAGONIA"], 7) == "avoid"  # southern winter
    assert GEO.travel_rule("JFK", GEO.destination("PATAGONIA")).overhead_days == 3
```

- [ ] **Step 2: Write the failing test file** `tests/core/test_selection.py`

```python
from datetime import date, timedelta

from ptopilot.core.selection import ShapeConstraints, ground_days, satisfies, select_top
from ptopilot.core.shapes import TripShape

C = ShapeConstraints(
    min_days_away=9,
    max_days_away=16,
    min_ground_days=7,
    max_ground_days=12,
    travel_overhead_days=3,
    pto_available=10,
)


def shape(days_away, pto, start=date(2027, 6, 5), evening=False):
    return TripShape(start, start + timedelta(days=days_away - 1), pto, evening)


def test_ground_days_subtracts_travel_overhead():
    assert ground_days(shape(10, 5), 3) == 7


def test_satisfies_accepts_a_trip_inside_every_limit():
    assert satisfies(shape(10, 5), C)


def test_satisfies_rejects_too_short_trip():
    assert not satisfies(shape(8, 4), C)


def test_satisfies_rejects_too_little_ground_time():
    c = ShapeConstraints(9, 16, 8, 12, 3, 10)
    assert not satisfies(shape(10, 5), c)  # 7 ground days < 8


def test_satisfies_rejects_too_much_ground_time():
    assert not satisfies(shape(16, 10), C)  # 13 ground days > 12


def test_satisfies_rejects_over_budget_pto():
    assert not satisfies(shape(15, 11), C)


def test_select_top_ranks_by_efficiency():
    a, b, c = shape(9, 5), shape(10, 4), shape(12, 8)
    assert select_top([a, b, c], n=2) == [b, a]


def test_select_top_limits_shapes_per_trip_length():
    same_length = [shape(9, 5, date(2027, 6, 5) + timedelta(days=7 * i)) for i in range(4)]
    other = shape(12, 8)
    picked = select_top(same_length + [other], n=6, max_per_length=2)
    assert len(picked) == 3
    assert picked[:2] == same_length[:2]  # earlier departures win ties
    assert picked[2] == other


def test_select_top_prefers_fewer_pto_days_on_equal_efficiency():
    a = shape(10, 5)
    b = shape(8, 4, date(2027, 7, 3))
    assert select_top([a, b], n=1) == [b]


def test_select_top_keeps_one_shape_per_date_pair():
    regular = shape(10, 6)
    evening = shape(10, 5, evening=True)
    assert select_top([regular, evening], n=6) == [evening]


def test_select_top_returns_at_most_n():
    shapes = [shape(9 + i, 5) for i in range(8)]
    assert len(select_top(shapes, n=6)) == 6


def test_select_top_spreads_across_departure_weeks():
    # Equal efficiency every week (no holidays): without a weekly cap, ties all go to the first weeks.
    weekly = [shape(9, 5, date(2027, 3, 6) + timedelta(days=7 * w)) for w in range(4)]
    weekly += [shape(10, 5, date(2027, 3, 5) + timedelta(days=7 * w)) for w in range(4)]
    picked = select_top(weekly, n=4, max_per_length=4, max_per_week=1)
    assert sorted(s.depart_date.isocalendar()[1] for s in picked) == [9, 10, 11, 12]
    assert len(select_top(weekly, n=4, max_per_length=4)) == 4  # unlimited by default
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/core -q`
Expected: 3 failed, 111 passed: `test_open_jaw_route_pairs_arrival_and_return_airports` and `test_round_trips_return_from_the_arrival_airport` with `AttributeError: 'PlannedItinerary' object has no attribute 'return_airport'`; `test_select_top_spreads_across_departure_weeks` with `TypeError: select_top() got an unexpected keyword argument 'max_per_week'`.

- [ ] **Step 4: Write** `ptopilot/config.py`

```python
"""Tunable thresholds and weights. Change behavior here, not in the logic modules."""

# Itinerary pruning
TOP_SHAPES_PER_WINDOW = 8
MAX_SHAPES_PER_LENGTH = 3
MAX_SHAPES_PER_WEEK = 2  # spread picks across the window instead of bunching at its start
WINDOW_SLACK_DAYS = 2

# Baselines
COLD_START_N = 15
MAD_TO_SIGMA = 1.4826
SIGMA_FLOOR_FRACTION = 0.03

# Deal levels (z-score thresholds, inclusive)
GOOD_DEAL_Z = -1.0
GREAT_DEAL_Z = -1.5

# Go-now score
GO_NOW_WEIGHTS = {"deal": 0.5, "weather": 0.2, "efficiency": 0.2, "timing": 0.1}
DEAL_Z_FOR_FULL_SCORE = 2.5
WEATHER_SCORES = {"good": 1.0, "shoulder": 0.6, "avoid": 0.2}
SWEET_SPOT_DAYS = {"international": (30, 120), "domestic": (21, 90)}
OFF_SWEET_SPOT_TIMING = 0.5

# Pipeline (spec §7)
DEFAULT_CURRENCY = "USD"
CACHE_LOOKBACK_DAYS = 7  # cached fares older than this are ignored
BASELINE_WINDOW_DAYS = 60
SHORTLIST_Z = -0.385  # z at the 35th percentile of a normal distribution
LIVE_CHECK_CAP = 40
EXPLORATION_QUOTA = 10  # slots reserved for routes with too little history or no cached price
PRIORITY_WEIGHTS = {1: 1.0, 2: 0.8, 3: 0.6}
MONTH_ESTIMATE_WEIGHT = 0.5  # a month's cheapest fare is a weaker signal than a fare for the exact dates
URGENCY = {"soon": 0.7, "sweet": 1.0, "far": 0.5}  # <30 days, 30-120 days, >120 days out
BREAKER_THRESHOLD = 3  # consecutive failures before a live source is skipped for the rest of the run
LIVE_DELAY_S = (3.0, 8.0)  # random pause between live checks
SOURCE_BUDGETS = {"serpapi": {"per_day": 8, "per_month": 250}}  # every attempted call counts
SHORT_HAUL_MAX_MIN = 600  # fastest option under 10 h -> short-haul stop limit applies
MAX_DURATION_RATIO = 1.5
LIVE_HORIZON_DAYS = 300  # Google Flights returns nothing ~10-11 months out; don't spend checks beyond this
```

- [ ] **Step 5: Write** `ptopilot/core/selection.py`

```python
"""Filtering trip shapes against a traveler's limits, and picking the best few."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ptopilot.core.shapes import TripShape


@dataclass(frozen=True)
class ShapeConstraints:
    min_days_away: int
    max_days_away: int
    min_ground_days: int
    max_ground_days: int
    travel_overhead_days: float
    pto_available: int


def ground_days(shape: TripShape, travel_overhead_days: float) -> float:
    """Days actually at the destination after subtracting round-trip travel time."""
    return shape.days_away - travel_overhead_days


def satisfies(shape: TripShape, c: ShapeConstraints) -> bool:
    if not c.min_days_away <= shape.days_away <= c.max_days_away:
        return False
    if not c.min_ground_days <= ground_days(shape, c.travel_overhead_days) <= c.max_ground_days:
        return False
    return shape.pto_cost <= c.pto_available


def select_top(
    shapes: Iterable[TripShape], n: int = 6, max_per_length: int = 2, max_per_week: int | None = None
) -> list[TripShape]:
    """Best n shapes by PTO efficiency, with diversity limits: at most max_per_length per trip length,
    at most max_per_week per departure week (ISO week; None = unlimited), and at most one per
    (depart, return) pair so an evening variant never duplicates its regular twin.

    Ties: fewer PTO days, then earlier departure, then the non-evening variant. Without a weekly limit,
    windows with no holidays (where every week ties) would only ever get trips from their first weeks.
    """
    ranked = sorted(
        shapes,
        key=lambda s: (-s.efficiency, s.pto_cost, s.depart_date, s.evening_departure),
    )
    picked: list[TripShape] = []
    per_length: Counter[int] = Counter()
    per_week: Counter[tuple[int, int]] = Counter()
    seen_dates: set[tuple[date, date]] = set()
    for s in ranked:
        dates = (s.depart_date, s.return_date)
        week = s.depart_date.isocalendar()[:2]
        if per_length[s.days_away] >= max_per_length or dates in seen_dates:
            continue
        if max_per_week is not None and per_week[week] >= max_per_week:
            continue
        picked.append(s)
        per_length[s.days_away] += 1
        per_week[week] += 1
        seen_dates.add(dates)
        if len(picked) == n:
            break
    return picked
```

- [ ] **Step 6: Write** `ptopilot/core/planner.py`

```python
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
    season_codes = (dest.code, dest.country)
    pto_available = max(profile.pto_available, 0)
    out: list[PlannedItinerary] = []
    seen: set[tuple[str, str, str, TripShape]] = set()
    if dest.open_jaw:
        airport_pairs = [(a, r) for a in dest.airports for r in dest.home_from]
    else:
        airport_pairs = [(a, a) for a in dest.airports]

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

            for s in select_top(
                season_of,
                n=top_n,
                max_per_length=config.MAX_SHAPES_PER_LENGTH,
                max_per_week=config.MAX_SHAPES_PER_WEEK,
            ):
                month, rating = season_of[s]
                for airport, home_from in airport_pairs:
                    key = (origin, airport, home_from, s)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(PlannedItinerary(origin, airport, dest.code, s, month, rating, home_from))
    return out
```

- [ ] **Step 7: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/core -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **235 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 8: Commit and push**

```bash
git add ptopilot/config.py ptopilot/core/selection.py ptopilot/core/planner.py tests/core/test_planner.py tests/core/test_selection.py
git commit -m "feat(core): open-jaw itineraries; spread trips across departure weeks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Open-jaw queries in the fare sources

**Files:**
- Modify: `ptopilot/sources/base.py`, `ptopilot/sources/google_flights.py`, `ptopilot/sources/serpapi.py`
- Create: `tests/sources/fixtures/real_serpapi_multicity_JFK-OPO_SCQ-JFK_2027-03.json` (real recording)
- Test: `tests/sources/test_base.py`, `test_serpapi.py`, `test_google_flights.py`, `test_real_recordings.py`

**Interfaces:**
- Produces: `ExactQuery(..., currency='USD', return_from: str | None = None)` with `.open_jaw`; protocol attribute `ExactSearchSource.supports_open_jaw: bool`; `GoogleFlightsSource.supports_open_jaw = False` (raises `ValueError` on an open-jaw query); `SerpApiSource.supports_open_jaw = True` (sends `type=3`, `multi_city_json=[{{departure_id, arrival_id, date}}, …]`).

**Fixture:** copy `real_serpapi_multicity_JFK-OPO_SCQ-JFK_2027-03.json` from `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p4\tests\sources\fixtures\`. If it's gone, re-record it, which costs 1 SerpApi search: `GET https://serpapi.com/search.json?engine=google_flights&type=3&currency=USD&hl=en&multi_city_json=[{"departure_id":"JFK","arrival_id":"OPO","date":"2027-03-06"},{"departure_id":"SCQ","arrival_id":"JFK","date":"2027-03-21"}]&api_key=…`. Save the JSON response and **check it doesn't contain the key** before committing. Update the numbers in `test_real_serpapi_multi_city_response` to match the new recording.

- [ ] **Step 1: Write the failing test file** `tests/sources/test_base.py`

```python
from datetime import date, datetime

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, snippet

QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))


def option(price):
    return FlightOption(
        price=price, carrier="TAP", stops=0, duration_min=480, outbound_departure=datetime(2027, 6, 11, 18)
    )


def test_cheapest_picks_lowest_price():
    result = ExactResult("x", QUERY, "USD", (option(700), option(612), option(650)), "https://link")
    assert result.cheapest().price == 612


def test_cheapest_of_nothing_is_none():
    assert ExactResult("x", QUERY, "USD", (), "https://link").cheapest() is None


def test_query_defaults_to_usd():
    assert QUERY.currency == "USD"


def test_snippet_flattens_and_truncates():
    assert snippet("a\n  b\tc") == "a b c"
    assert snippet("x" * 400, limit=10) == "x" * 10 + "…"


def test_open_jaw_query():
    assert QUERY.open_jaw is False
    assert ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20), return_from="LIS").open_jaw is False
    assert ExactQuery("JFK", "OPO", date(2027, 3, 6), date(2027, 3, 21), return_from="SCQ").open_jaw is True
```

- [ ] **Step 2: Write the failing test file** `tests/sources/test_serpapi.py`

```python
"""Fixture follows SerpApi's documented google_flights shape; swap for a real recording once a key exists."""

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from ptopilot.sources.base import ExactQuery, SourceUnavailable
from ptopilot.sources.serpapi import SerpApiSource, parse_google_flights

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "serpapi_ORD_LIS_2027-06-11_2027-06-20.json").read_text()
)
QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))


def source_returning(status=200, body=None, text=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body)

    return SerpApiSource("key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_best_and_other_flights():
    result = parse_google_flights(FIXTURE, QUERY)
    assert len(result.options) == 2
    best = result.options[0]
    assert (best.price, best.carrier, best.stops, best.duration_min) == (
        905.0,
        "United, TAP Air Portugal",
        1,
        630,
    )
    assert best.flight_numbers == ("UA 1234", "TP 202")
    assert best.outbound_departure == datetime(2027, 6, 11, 18, 15)
    assert best.overnight_layover is False


def test_overnight_flag_and_cheapest():
    result = parse_google_flights(FIXTURE, QUERY)
    assert result.options[1].overnight_layover is True
    assert result.cheapest().price == 840.0


def test_typical_range_and_link():
    result = parse_google_flights(FIXTURE, QUERY)
    assert result.typical_range == (780.0, 1150.0)
    assert result.deep_link.startswith("https://www.google.com/travel/flights")
    assert result.source == "serpapi"


def test_missing_price_insights_means_no_range():
    payload = {k: v for k, v in FIXTURE.items() if k != "price_insights"}
    assert parse_google_flights(payload, QUERY).typical_range is None


def test_request_params():
    seen = []
    source_returning(body=FIXTURE, seen=seen).exact_search(QUERY)
    params = dict(seen[0].url.params)
    assert params["engine"] == "google_flights"
    assert (params["departure_id"], params["arrival_id"]) == ("ORD", "LIS")
    assert (params["outbound_date"], params["return_date"], params["type"]) == (
        "2027-06-11",
        "2027-06-20",
        "1",
    )
    assert params["api_key"] == "key"


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"status": 401, "text": "Invalid API key"}, "HTTP 401"),
        ({"status": 200, "body": {"error": "Your account has run out of searches."}}, "run out of searches"),
        ({"status": 200, "text": "not json"}, "invalid JSON"),
    ],
)
def test_failures_raise_source_unavailable(kwargs, match):
    with pytest.raises(SourceUnavailable, match=match):
        source_returning(**kwargs).exact_search(QUERY)


def test_empty_key_is_rejected():
    with pytest.raises(ValueError, match="SERPAPI_KEY"):
        SerpApiSource("")


def test_no_results_is_an_empty_result_not_an_outage():
    body = {"error": "Google Flights hasn't returned any results for this query."}
    result = source_returning(body=body).exact_search(QUERY)
    assert result.options == ()
    assert result.cheapest() is None


@pytest.mark.parametrize("body", [[1], "oops"])
def test_non_object_json_is_source_unavailable(body):
    with pytest.raises(SourceUnavailable, match="unexpected"):
        source_returning(body=body).exact_search(QUERY)


OPEN_JAW = ExactQuery("JFK", "OPO", date(2027, 3, 6), date(2027, 3, 21), return_from="SCQ")


def test_open_jaw_is_sent_as_a_multi_city_search():
    seen = []
    source_returning(body=FIXTURE, seen=seen).exact_search(OPEN_JAW)
    params = dict(seen[0].url.params)
    assert params["type"] == "3"
    assert json.loads(params["multi_city_json"]) == [
        {"departure_id": "JFK", "arrival_id": "OPO", "date": "2027-03-06"},
        {"departure_id": "SCQ", "arrival_id": "JFK", "date": "2027-03-21"},
    ]
    assert "outbound_date" not in params and "departure_id" not in params


def test_declares_open_jaw_support():
    assert SerpApiSource.supports_open_jaw is True
```

- [ ] **Step 3: Write the failing test file** `tests/sources/test_google_flights.py`

```python
"""Fixture is a real fast-flights 3.1.0 response recorded 2026-10-16 for ORD<->LIS, Jun 11-20 2027."""

import json
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ptopilot.sources.base import ExactQuery, SourceUnavailable
from ptopilot.sources.google_flights import GoogleFlightsSource, parse_flights

FIXTURE_TEXT = (
    Path(__file__).parent / "fixtures" / "google_flights_ORD_LIS_2027-06-11_2027-06-20.json"
).read_text()
QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))


def recorded():
    """Rebuild attribute-style objects like fast-flights returns."""
    return json.loads(FIXTURE_TEXT, object_hook=lambda d: SimpleNamespace(**d))


def test_parse_real_response():
    options = parse_flights(recorded())
    assert len(options) == 7
    first = options[0]
    assert first.price == 1340.0
    assert first.carrier == "SWISS"
    assert first.stops == 1
    # 530 + 175 flying, plus ZRH layover 06:10 -> 12:50 = 400
    assert first.duration_min == 1105
    assert first.outbound_departure == datetime(2027, 6, 11, 14, 20)
    assert first.overnight_layover is False
    assert first.flight_numbers == ()


def test_multi_airline_carrier_is_joined():
    third = parse_flights(recorded())[2]
    assert third.carrier == "American, British Airways"
    assert third.duration_min == 470 + 180 + 130


def test_overnight_layover_detected_when_connection_is_next_day():
    r = recorded()[0]
    r.flights[1].departure.date = [2027, 6, 13]
    assert parse_flights([r])[0].overnight_layover is True


def test_exact_search_wraps_results_and_link():
    src = GoogleFlightsSource(
        search=lambda q: (recorded(), "https://www.google.com/travel/flights/search?tfs=X")
    )
    result = src.exact_search(QUERY)
    assert result.source == "google_flights"
    assert result.cheapest().price == 1340.0
    assert result.deep_link.endswith("tfs=X")
    assert result.typical_range is None


def test_no_flights_is_an_empty_result_not_an_error():
    result = GoogleFlightsSource(search=lambda q: ([], "u")).exact_search(QUERY)
    assert result.options == ()
    assert result.cheapest() is None


def test_any_library_failure_becomes_source_unavailable():
    def blocked(q):
        raise RuntimeError("429 Too Many Requests")

    with pytest.raises(SourceUnavailable, match="429"):
        GoogleFlightsSource(search=blocked).exact_search(QUERY)


@pytest.mark.live
def test_live_google_flights_smoke():
    result = GoogleFlightsSource().exact_search(
        ExactQuery("ORD", "LIS", date(2027, 6, 11), date(2027, 6, 20))
    )
    assert result.options and result.cheapest().price > 0


def test_hung_search_times_out_as_source_unavailable():
    def hang(q):
        time.sleep(5)
        return [], "u"

    start = time.monotonic()
    with pytest.raises(SourceUnavailable, match="timed out"):
        GoogleFlightsSource(search=hang, timeout_s=0.2).exact_search(QUERY)
    assert time.monotonic() - start < 2


def test_refuses_open_jaw_queries():
    assert GoogleFlightsSource.supports_open_jaw is False
    open_jaw = ExactQuery("JFK", "OPO", date(2027, 3, 6), date(2027, 3, 21), return_from="SCQ")
    with pytest.raises(ValueError, match="open-jaw"):
        GoogleFlightsSource(search=lambda q: ([], "u")).exact_search(open_jaw)
```

- [ ] **Step 4: Write the failing test file** `tests/sources/test_real_recordings.py`

```python
"""Real API responses recorded 2026-10-16 (checked for secrets). Guards against provider format drift."""

import json
from datetime import date, datetime
from pathlib import Path

from ptopilot.sources.base import ExactQuery
from ptopilot.sources.serpapi import parse_google_flights
from ptopilot.sources.travelpayouts import parse_prices_for_dates

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_real_travelpayouts_city_pair_response():
    quotes = parse_prices_for_dates(load("real_travelpayouts_NYC_LON_2026-12.json"), "NYC", "LON")
    assert len(quotes) == 10
    first = quotes[0]
    assert (first.origin, first.dest_airport) == ("EWR", "LHR")  # city query returns real airports
    assert (first.depart_date, first.return_date) == (date(2026, 12, 1), date(2026, 12, 9))
    assert (first.price, first.currency, first.flight_number, first.stops) == (562.0, "USD", "SK 910", 1)
    assert first.deep_link.startswith("https://www.aviasales.com/search/")
    assert all(q.currency == "USD" and q.return_date for q in quotes)


def test_real_serpapi_round_trip_response():
    query = ExactQuery("ORD", "LIS", date(2027, 6, 12), date(2027, 6, 20))
    result = parse_google_flights(load("real_serpapi_ORD_LIS_2027-06-12_2027-06-20.json"), query)
    assert len(result.options) == 11
    assert result.typical_range == (1100.0, 1400.0)
    assert result.deep_link.startswith("https://www.google.com/travel/flights")
    best = result.cheapest()
    assert (best.price, best.carrier, best.stops, best.duration_min) == (1098.0, "Tap Air Portugal", 0, 490)
    assert best.flight_numbers == ("TP 244",)
    assert best.outbound_departure == datetime(2027, 6, 12, 17, 45)


def test_real_serpapi_multi_city_response():
    query = ExactQuery("JFK", "OPO", date(2027, 3, 6), date(2027, 3, 21), return_from="SCQ")
    result = parse_google_flights(load("real_serpapi_multicity_JFK-OPO_SCQ-JFK_2027-03.json"), query)
    assert len(result.options) == 8
    assert result.typical_range is None  # Google gives no price insights for multi-city
    best = result.cheapest()
    assert (best.price, best.carrier, best.stops) == (959.0, "Iberia", 1)
    assert best.flight_numbers == ("IB 212", "IB 543")
    assert best.outbound_departure == datetime(2027, 3, 6, 17, 5)
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/sources -q`
Expected: collection ERROR in `tests/sources/test_serpapi.py`: `TypeError: ExactQuery.__init__() got an unexpected keyword argument 'return_from'`.

- [ ] **Step 6: Write** `ptopilot/sources/base.py`

```python
"""Shared types for fare sources. Pipelines depend on these, never on a specific provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class SourceUnavailable(Exception):
    """A source failed (network, auth, quota, or unparseable response). Message carries a short snippet."""


@dataclass(frozen=True)
class FareQuote:
    """A cached fare from a broad month scan. Unverified."""

    source: str
    origin: str
    dest_airport: str
    depart_date: date
    return_date: date | None
    price: float
    currency: str
    airline: str | None = None
    flight_number: str | None = None
    stops: int | None = None
    return_stops: int | None = None
    duration_min: int | None = None
    deep_link: str | None = None


@dataclass(frozen=True)
class ExactQuery:
    origin: str
    dest_airport: str  # fly into
    depart_date: date
    return_date: date
    currency: str = "USD"
    return_from: str | None = None  # fly home from; None means dest_airport (a plain round trip)

    @property
    def open_jaw(self) -> bool:
        return self.return_from not in (None, self.dest_airport)


@dataclass(frozen=True)
class FlightOption:
    """One bookable round trip. Details describe the outbound leg; price is the round-trip total."""

    price: float
    carrier: str
    stops: int
    duration_min: int  # outbound, including layovers
    outbound_departure: datetime  # local time at origin
    flight_numbers: tuple[str, ...] = ()
    overnight_layover: bool = False


@dataclass(frozen=True)
class ExactResult:
    source: str
    query: ExactQuery
    currency: str
    options: tuple[FlightOption, ...]
    deep_link: str
    typical_range: tuple[float, float] | None = None  # Google's typical price range, when the source has it

    def cheapest(self) -> FlightOption | None:
        return min(self.options, key=lambda o: o.price, default=None)


class MonthScanSource(Protocol):
    name: str

    def month_scan(
        self, origin: str, dest_airport: str, month: date, market: str, currency: str
    ) -> list[FareQuote]: ...


class ExactSearchSource(Protocol):
    name: str
    supports_open_jaw: bool  # can price "into A, home from B" itineraries

    def exact_search(self, query: ExactQuery) -> ExactResult: ...


def snippet(text: str, limit: int = 300) -> str:
    """Single-line, truncated excerpt of a payload for error messages."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
```

- [ ] **Step 7: Write** `ptopilot/sources/google_flights.py`

```python
"""Live Google Flights prices via the unofficial `fast-flights` library. Free but fragile."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable

SEARCH_TIMEOUT_S = 60


def _call_with_timeout(fn: Callable[[ExactQuery], Any], query: ExactQuery, timeout_s: float) -> Any:
    """fast-flights has no timeout of its own. Run it in a daemon thread so a stalled request can't
    hang the pipeline or block interpreter exit."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn(query)
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError(f"timed out after {timeout_s}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _dt(simple: Any) -> datetime:
    """fast-flights SimpleDatetime -> naive local datetime."""
    (y, m, d), (hh, mm) = simple.date, simple.time
    return datetime(y, m, d, hh, mm)


def parse_flights(results: Sequence[Any]) -> tuple[FlightOption, ...]:
    """Map fast-flights `Flights` objects (outbound legs of round trips) to FlightOptions."""
    options: list[FlightOption] = []
    for r in results:
        segments = list(r.flights)
        if not segments or not r.price:
            continue
        layover_min = 0
        overnight = False
        for prev, nxt in zip(segments, segments[1:], strict=False):
            arrive, leave = _dt(prev.arrival), _dt(nxt.departure)
            layover_min += int((leave - arrive).total_seconds() // 60)
            overnight = overnight or leave.date() != arrive.date()
        options.append(
            FlightOption(
                price=float(r.price),
                carrier=", ".join(r.airlines),
                stops=len(segments) - 1,
                duration_min=sum(s.duration for s in segments) + layover_min,
                outbound_departure=_dt(segments[0].departure),
                flight_numbers=(),
                overnight_layover=overnight,
            )
        )
    return tuple(options)


def _default_search(query: ExactQuery) -> tuple[Sequence[Any], str]:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    from fast_flights.exceptions import FlightsNotFound

    q = create_query(
        flights=[
            FlightQuery(
                date=query.depart_date.isoformat(), from_airport=query.origin, to_airport=query.dest_airport
            ),
            FlightQuery(
                date=query.return_date.isoformat(), from_airport=query.dest_airport, to_airport=query.origin
            ),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=1),
        language="en-US",
        currency=query.currency,
    )
    try:
        return get_flights(q), q.url()
    except FlightsNotFound:
        return [], q.url()


class GoogleFlightsSource:
    name = "google_flights"
    supports_open_jaw = False  # fast-flights 3.1's multi-city parser crashes (verified 2026-10-16)

    def __init__(
        self,
        search: Callable[[ExactQuery], tuple[Sequence[Any], str]] = _default_search,
        timeout_s: float = SEARCH_TIMEOUT_S,
    ):
        self._search = search
        self._timeout_s = timeout_s

    def exact_search(self, query: ExactQuery) -> ExactResult:
        if query.open_jaw:
            raise ValueError("google_flights cannot price open-jaw trips; check supports_open_jaw first")
        try:
            results, url = _call_with_timeout(self._search, query, self._timeout_s)
            options = parse_flights(results)
        except Exception as exc:  # the library scrapes HTML; any failure means "unavailable"
            raise SourceUnavailable(f"google_flights: {type(exc).__name__}: {exc}") from exc
        return ExactResult(
            source=self.name, query=query, currency=query.currency, options=options, deep_link=url
        )
```

- [ ] **Step 8: Write** `ptopilot/sources/serpapi.py`

```python
"""SerpApi Google Flights: quota-limited fallback that also returns Google's typical price range."""

from __future__ import annotations

import json
from datetime import datetime

import httpx

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable, snippet

API_URL = "https://serpapi.com/search.json"
TIMEOUT_S = 60


def _option(item: dict) -> FlightOption | None:
    legs = item.get("flights") or []
    price = item.get("price")
    if not legs or not isinstance(price, int | float):
        return None
    airlines: list[str] = []
    for leg in legs:
        if leg.get("airline") and leg["airline"] not in airlines:
            airlines.append(leg["airline"])
    return FlightOption(
        price=float(price),
        carrier=", ".join(airlines),
        stops=len(legs) - 1,
        duration_min=int(item.get("total_duration") or sum(leg.get("duration", 0) for leg in legs)),
        outbound_departure=datetime.strptime(legs[0]["departure_airport"]["time"], "%Y-%m-%d %H:%M"),
        flight_numbers=tuple(leg["flight_number"] for leg in legs if leg.get("flight_number")),
        overnight_layover=any(lay.get("overnight") for lay in item.get("layovers") or []),
    )


NO_RESULTS_MARKER = "hasn't returned any results"


def parse_google_flights(payload: dict, query: ExactQuery) -> ExactResult:
    if not isinstance(payload, dict):
        raise SourceUnavailable(f"serpapi: unexpected payload: {snippet(str(payload))}")
    if "error" in payload:
        if NO_RESULTS_MARKER in str(payload["error"]):  # a valid search with no flights, not an outage
            return ExactResult(
                source="serpapi", query=query, currency=query.currency, options=(), deep_link=""
            )
        raise SourceUnavailable(f"serpapi: {snippet(str(payload['error']))}")
    try:
        items = (payload.get("best_flights") or []) + (payload.get("other_flights") or [])
        options = tuple(o for o in (_option(i) for i in items) if o is not None)
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceUnavailable(f"serpapi: unexpected flight shape: {exc}") from exc
    typical = (payload.get("price_insights") or {}).get("typical_price_range")
    typical_range = (float(typical[0]), float(typical[1])) if typical and len(typical) == 2 else None
    url = (payload.get("search_metadata") or {}).get("google_flights_url", "")
    return ExactResult(
        source="serpapi",
        query=query,
        currency=query.currency,
        options=options,
        deep_link=url,
        typical_range=typical_range,
    )


class SerpApiSource:
    name = "serpapi"
    supports_open_jaw = True  # via type=3 multi-city searches

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("SerpApi key is empty; set SERPAPI_KEY")
        self._key = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def exact_search(self, query: ExactQuery) -> ExactResult:
        params: dict[str, str | int] = {
            "engine": "google_flights",
            "currency": query.currency,
            "hl": "en",
            "api_key": self._key,
        }
        if query.open_jaw:
            legs = [
                {
                    "departure_id": query.origin,
                    "arrival_id": query.dest_airport,
                    "date": query.depart_date.isoformat(),
                },
                {
                    "departure_id": query.return_from,
                    "arrival_id": query.origin,
                    "date": query.return_date.isoformat(),
                },
            ]
            params |= {"type": 3, "multi_city_json": json.dumps(legs)}
        else:
            params |= {
                "type": 1,
                "departure_id": query.origin,
                "arrival_id": query.dest_airport,
                "outbound_date": query.depart_date.isoformat(),
                "return_date": query.return_date.isoformat(),
            }
        try:
            resp = self._client.get(API_URL, params=params)
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"serpapi: {type(exc).__name__}: {exc}") from exc
        if resp.status_code != 200:
            raise SourceUnavailable(f"serpapi: HTTP {resp.status_code}: {snippet(resp.text)}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SourceUnavailable(f"serpapi: invalid JSON: {snippet(resp.text)}") from exc
        return parse_google_flights(payload, query)
```

- [ ] **Step 9: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/sources -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **240 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 10: Commit and push**

```bash
git add ptopilot/sources/base.py ptopilot/sources/google_flights.py ptopilot/sources/serpapi.py tests/sources
git commit -m "feat(sources): open-jaw queries via SerpApi multi-city" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 4: Open-jaw through the database and pipeline; search horizon; exploration fixes

**Files:**
- Modify: `ptopilot/db/models.py`
- Create: `ptopilot/db/migrations/versions/0004_open_jaw_return_airport.py` (hand-written)
- Modify: `ptopilot/pipeline/queries.py`, `expand.py`, `broad_scan.py`, `shortlist.py`, `live_verify.py`, `baselines.py`, `score.py`
- Test: `tests/db/test_models.py`, `tests/db/test_pipeline_tables.py`, `tests/pipeline/conftest.py`, `tests/pipeline/test_shortlist.py`, `tests/pipeline/test_score.py`, `tests/pipeline/test_open_jaw.py` (new)

**Interfaces:**
- Consumes: `PlannedItinerary.return_airport` (Task 2); `ExactQuery.return_from`, `supports_open_jaw` (Task 3); `config.LIVE_HORIZON_DAYS` (Task 2).
- Produces: `return_airport` (NOT NULL) on `RouteQuery`, `PriceObservation` and `RouteBaseline` (part of the primary key); unique `uq_route_queries_trip`; `Tracker.destination_code` String(32); `queries.Route`, `DateKey`/`BaselineKey` with return airport, `date_key(rq_or_observation)`, `baseline_key(origin, dest, return_airport, depart, ret)`, `rq_baseline_key(rq)`; test helpers `add_observation(..., return_airport=None)`, `add_live_check(engine, depart, ret, run_date, ok=True, …)`, `FakeLiveSource(name, respond, supports_open_jaw=False)`.

Changed behaviour, beyond threading `return_airport` through every key:
- `broad_scan` skips open-jaw route queries, because the cache only has round trips.
- `live_verify` sends open-jaw queries only to `supports_open_jaw` sources. When none can take one, it counts `no_open_jaw_source`: never a breaker strike, never a stage failure.
- `shortlist` skips departures more than `LIVE_HORIZON_DAYS` out (`beyond_horizon`). It orders exploration by `live_checks` before the run date, so "no flights" results count as checked. Exploration keeps its reserved slots and also fills slots deals leave unused (cap 40).

**Migration 0004 is hand-written.** Autogenerate can't backfill a new NOT NULL column on tables with rows, and it doesn't detect primary-key changes. The file below adds each `return_airport` as nullable, backfills it from `dest_airport`, sets NOT NULL, swaps the route-query unique constraint, rebuilds `pk_route_baselines`, and widens `trackers.destination_code`. Its downgrade deletes open-jaw rows first.

- [ ] **Step 1: Write the failing test file** `tests/db/test_models.py`

```python
from datetime import date, time
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ptopilot.db.models import (
    DigestSend,
    PriceObservation,
    RouteQuery,
    Tracker,
    TravelWindow,
    User,
)


def make_user(session, **overrides):
    fields = {
        "email": "nick@example.com",
        "home_airport": "ORD",
        "country": "US",
        "holiday_calendar": "US",
        "pto_days_total": 20,
        "max_trip_days": 16,
    } | overrides
    user = User(**fields)
    session.add(user)
    session.flush()
    return user


def test_user_defaults_and_arrays_round_trip(session):
    user = make_user(session, nearby_airports=["MDW"], extra_days_off=[date(2027, 11, 26)])
    session.expire_all()
    loaded = session.get(User, user.id)
    assert loaded.nearby_airports == ["MDW"]
    assert loaded.extra_days_off == [date(2027, 11, 26)]
    assert loaded.ignored_holidays == []
    assert (loaded.currency, loaded.weather_tolerance, loaded.min_trip_days) == ("USD", "normal", 3)
    assert loaded.friday_evening_min_time == time(17, 0)
    assert loaded.created_at is not None


def test_user_email_is_unique(session):
    make_user(session)
    with pytest.raises(IntegrityError):
        make_user(session)


@pytest.mark.parametrize(
    "overrides",
    [
        {"weather_tolerance": "sunny"},
        {"min_trip_days": 10, "max_trip_days": 5},
        {"pto_days_total": -1},
    ],
)
def test_user_checks_reject_bad_values(session, overrides):
    with pytest.raises(IntegrityError):
        make_user(session, **overrides)


def test_deleting_user_cascades_to_trackers_and_windows(session):
    user = make_user(session)
    session.add_all(
        [
            Tracker(user_id=user.id, destination_code="TH", min_stay_days=7, max_stay_days=12),
            TravelWindow(user_id=user.id, start_date=date(2027, 6, 1), end_date=date(2027, 6, 30)),
        ]
    )
    session.flush()
    session.delete(user)
    session.flush()
    assert session.scalar(select(func.count()).select_from(Tracker)) == 0
    assert session.scalar(select(func.count()).select_from(TravelWindow)) == 0


@pytest.mark.parametrize(
    "row",
    [
        lambda uid: Tracker(user_id=uid, destination_code="TH", min_stay_days=12, max_stay_days=7),
        lambda uid: Tracker(
            user_id=uid, destination_code="TH", min_stay_days=7, max_stay_days=12, priority=4
        ),
        lambda uid: TravelWindow(user_id=uid, start_date=date(2027, 6, 30), end_date=date(2027, 6, 1)),
    ],
)
def test_tracker_and_window_checks(session, row):
    user = make_user(session)
    session.add(row(user.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_route_queries_are_unique(session):
    def rq():
        return RouteQuery(
            origin="ORD",
            dest_airport="LIS",
            return_airport="LIS",
            depart_date=date(2027, 6, 11),
            return_date=date(2027, 6, 20),
        )

    session.add(rq())
    session.flush()
    session.add(rq())
    with pytest.raises(IntegrityError):
        session.flush()


def test_price_observation_round_trip(session):
    obs = PriceObservation(
        origin="ORD",
        dest_airport="LIS",
        return_airport="LIS",
        depart_date=date(2027, 6, 11),
        return_date=date(2027, 6, 20),
        month=date(2027, 6, 1),
        source="serpapi",
        price=Decimal("905.00"),
        currency="USD",
        flight_numbers=["UA 1234", "TP 202"],
        verified=True,
    )
    session.add(obs)
    session.flush()
    session.expire_all()
    loaded = session.get(PriceObservation, obs.id)
    assert loaded.price == Decimal("905.00")
    assert loaded.flight_numbers == ["UA 1234", "TP 202"]
    assert loaded.observed_at is not None


def test_digest_items_json_round_trip(session):
    user = make_user(session)
    send = DigestSend(user_id=user.id, items=[{"candidate_id": 1, "price": 612.0}])
    session.add(send)
    session.flush()
    session.expire_all()
    assert session.get(DigestSend, send.id).items == [{"candidate_id": 1, "price": 612.0}]
```

- [ ] **Step 2: Write the failing test file** `tests/db/test_pipeline_tables.py`

```python
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from ptopilot.db.models import PriceObservation, RouteQuery, ShortlistEntry


def route(session):
    rq = RouteQuery(
        origin="ORD",
        dest_airport="LIS",
        return_airport="LIS",
        depart_date=date(2027, 6, 12),
        return_date=date(2027, 6, 20),
    )
    session.add(rq)
    session.flush()
    return rq


def test_shortlist_entry_round_trip_and_uniqueness(session):
    rq = route(session)
    session.add(
        ShortlistEntry(run_date=date(2027, 3, 1), route_query_id=rq.id, rank=1, reason="deal", est_price=800)
    )
    session.flush()
    session.add(ShortlistEntry(run_date=date(2027, 3, 1), route_query_id=rq.id, rank=2, reason="explore"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_shortlist_reason_is_checked(session):
    rq = route(session)
    session.add(ShortlistEntry(run_date=date(2027, 3, 1), route_query_id=rq.id, rank=1, reason="hunch"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_observation_stores_google_typical_range(session):
    obs = PriceObservation(
        origin="ORD",
        dest_airport="LIS",
        return_airport="LIS",
        month=date(2027, 6, 1),
        source="serpapi",
        price=Decimal("905.00"),
        currency="USD",
        typical_low=Decimal("780.00"),
        typical_high=Decimal("1150.00"),
    )
    session.add(obs)
    session.flush()
    session.expire_all()
    loaded = session.get(PriceObservation, obs.id)
    assert (loaded.typical_low, loaded.typical_high) == (Decimal("780.00"), Decimal("1150.00"))
```

- [ ] **Step 3: Write the failing test file** `tests/pipeline/conftest.py`

```python
"""Fakes and seed data for pipeline tests. Run date is 2027-03-01; the seeded user travels in June 2027."""

import random
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import select

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import LiveCheck, PriceObservation, RouteQuery, Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.sources.base import ExactQuery, ExactResult, FareQuote, FlightOption, SourceUnavailable

RUN = date(2027, 3, 1)
GEO = load_geo()
SEASONS = load_seasons()


class FakeMonthSource:
    name = "fake_month"

    def __init__(self, quotes: dict | None = None):
        self.quotes = quotes or {}  # (origin, dest, month) -> list[FareQuote] | Exception
        self.calls: list[tuple] = []

    def month_scan(self, origin, dest_airport, month, market, currency):
        self.calls.append((origin, dest_airport, month, market, currency))
        found = self.quotes.get((origin, dest_airport, month), [])
        if isinstance(found, Exception):
            raise found
        return found


class FakeLiveSource:
    def __init__(
        self, name: str, respond: Callable[[ExactQuery], ExactResult], supports_open_jaw: bool = False
    ):
        self.name = name
        self.respond = respond
        self.supports_open_jaw = supports_open_jaw
        self.calls: list[ExactQuery] = []

    def exact_search(self, query):
        self.calls.append(query)
        return self.respond(query)


def option(price, stops=1, duration=780, dep=time(18, 0), overnight=False, day=None) -> FlightOption:
    return FlightOption(
        price=float(price),
        carrier="TAP",
        stops=stops,
        duration_min=duration,
        outbound_departure=datetime.combine(day or date(2027, 6, 5), dep),
        flight_numbers=("TP 246",),
        overnight_layover=overnight,
    )


def answering(*options: FlightOption, typical=None, source="google_flights"):
    def respond(q: ExactQuery) -> ExactResult:
        return ExactResult(source, q, "USD", tuple(options), "https://flights.example/x", typical)

    return respond


def failing(message="blocked"):
    def respond(q):
        raise SourceUnavailable(message)

    return respond


def quote(origin, dest, depart, ret, price) -> FareQuote:
    return FareQuote(
        "travelpayouts", origin, dest, depart, ret, float(price), "USD", "TP", "TP 246", 1, 1, 760
    )


def add_user(
    engine, email="nick@example.com", windows=((date(2027, 6, 1), date(2027, 6, 30)),), **fields
) -> int:
    values = {
        "email": email,
        "home_airport": "ORD",
        "country": "US",
        "holiday_calendar": "US",
        "pto_days_total": 15,
        "max_trip_days": 16,
    } | fields
    with session_scope(engine) as s:
        user = User(**values)
        s.add(user)
        s.flush()
        for start, end in windows:
            s.add(TravelWindow(user_id=user.id, start_date=start, end_date=end))
        return user.id


def add_tracker(engine, user_id, code="LIS", min_stay=5, max_stay=9, **fields) -> int:
    with session_scope(engine) as s:
        t = Tracker(
            user_id=user_id, destination_code=code, min_stay_days=min_stay, max_stay_days=max_stay, **fields
        )
        s.add(t)
        s.flush()
        return t.id


def add_observation(
    engine,
    depart,
    ret,
    price,
    observed: date,
    verified=False,
    origin="ORD",
    dest="LIS",
    return_airport=None,
    **fields,
):
    with session_scope(engine) as s:
        s.add(
            PriceObservation(
                origin=origin,
                dest_airport=dest,
                return_airport=return_airport or dest,
                depart_date=depart,
                return_date=ret,
                month=depart.replace(day=1),
                source="google_flights" if verified else "travelpayouts",
                price=Decimal(str(price)),
                currency="USD",
                verified=verified,
                observed_at=datetime.combine(observed, time(12), UTC),
                **fields,
            )
        )


def add_live_check(
    engine, depart, ret, run_date: date, ok=True, origin="ORD", dest="LIS", source="google_flights"
):
    """Record that a route was live-checked on run_date (the route query must already exist)."""
    with session_scope(engine) as s:
        rq_id = s.scalar(
            select(RouteQuery.id).filter_by(
                origin=origin, dest_airport=dest, depart_date=depart, return_date=ret
            )
        )
        s.add(LiveCheck(run_date=run_date, route_query_id=rq_id, source=source, ok=ok))


@pytest.fixture
def make_ctx(clean_engine):
    def make(**overrides) -> RunContext:
        fields = {
            "run_date": RUN,
            "engine": clean_engine,
            "geo": GEO,
            "seasons": SEASONS,
            "sleep": lambda seconds: None,
            "rng": random.Random(0),
        } | overrides
        return RunContext(**fields)

    return make
```

- [ ] **Step 4: Write the failing test file** `tests/pipeline/test_shortlist.py`

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import RouteBaseline, RouteQuery, ShortlistEntry
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, shortlist
from tests.pipeline.conftest import RUN, add_live_check, add_observation, add_tracker, add_user

JUNE = date(2027, 6, 1)
DEAL = (date(2027, 6, 12), date(2027, 6, 20))  # 9 days away -> "week" bucket
PRICEY = (date(2027, 6, 11), date(2027, 6, 20))  # 10 days away -> "week" bucket
LATE = (date(2027, 6, 17), date(2027, 6, 27))  # 11 days away -> "long"; created after the others


def entries(engine):
    with session_scope(engine) as s:
        rows = s.execute(
            select(ShortlistEntry, RouteQuery).join(RouteQuery).order_by(ShortlistEntry.rank)
        ).all()
        return [(e.rank, e.reason, (rq.depart_date, rq.return_date), e.est_price) for e, rq in rows]


def confident_baseline(engine, bucket="week", median=1000, sigma=100):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                month=JUNE,
                length_bucket=bucket,
                median=Decimal(median),
                sigma=Decimal(sigma),
                n=20,
                confidence="normal",
            )
        )


def setup(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    return ctx


def test_without_history_everything_is_exploration(make_ctx):
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)
    assert counts["explore"] == 6 and counts["deal"] == 0
    assert all(reason == "explore" for _, reason, _, _ in entries(ctx.engine))


def test_cheap_cached_price_against_confident_baseline_is_a_deal(make_ctx):
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)
    confident_baseline(ctx.engine, bucket="long")
    add_observation(ctx.engine, *DEAL, 800, observed=RUN)  # z = -2
    add_observation(ctx.engine, *PRICEY, 990, observed=RUN)  # z = -0.1
    counts = shortlist.run(ctx)
    # DEAL's own fare, plus 4 routes with no exact fare estimated from June's cheapest ($800)
    assert (counts["deal"], counts["not_cheap"]) == (5, 1)
    assert entries(ctx.engine)[0][:2] == (1, "deal")


def test_exact_date_fare_outranks_month_level_estimates(make_ctx):
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)
    confident_baseline(ctx.engine, bucket="long")
    add_observation(ctx.engine, *LATE, 800, observed=RUN)  # exact fare; also June's cheapest
    shortlist.run(ctx)
    first = entries(ctx.engine)[0]
    assert first[:3] == (1, "deal", LATE)
    assert first[3] == 800


def test_stale_cached_prices_are_ignored(make_ctx):
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)
    add_observation(ctx.engine, *DEAL, 800, observed=date(2027, 2, 20))  # older than CACHE_LOOKBACK_DAYS
    shortlist.run(ctx)
    assert "deal" not in {reason for _, reason, _, _ in entries(ctx.engine)}


def test_exploration_prefers_routes_never_checked_live(make_ctx):
    ctx = setup(make_ctx)
    add_live_check(ctx.engine, *DEAL, run_date=date(2027, 2, 1), ok=True)
    shortlist.run(ctx)
    assert entries(ctx.engine)[-1][2] == DEAL


def test_a_no_flights_check_still_counts_as_checked(make_ctx):
    ctx = setup(make_ctx)
    add_live_check(ctx.engine, *DEAL, run_date=date(2027, 2, 1), ok=True)  # stored no price rows
    shortlist.run(ctx)
    assert entries(ctx.engine)[-1][2] == DEAL


def test_departures_beyond_the_search_horizon_are_skipped(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_HORIZON_DAYS", 100)  # run 2027-03-01 -> June trips are ~100+ days out
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)
    assert counts["beyond_horizon"] >= 1
    assert all((dep - RUN).days <= 100 for _, _, (dep, _), _ in entries(ctx.engine))


def test_exploration_fills_check_slots_that_deals_leave_unused(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_CHECK_CAP", 3)
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 2)
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)  # no history: 6 exploration candidates, no deals
    assert (counts["explore"], counts["explore_overflow"]) == (3, 3)
    assert len(entries(ctx.engine)) == 3


def test_exploration_keeps_its_reserved_slots_when_deals_overflow(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_CHECK_CAP", 3)
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 1)
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)  # "week" trips only; the two 11-day trips stay exploration
    add_observation(ctx.engine, *DEAL, 800, observed=RUN)  # June's cheapest: makes week trips look like deals
    counts = shortlist.run(ctx)
    assert (counts["deal"], counts["explore"]) == (2, 1)
    assert [reason for _, reason, _, _ in entries(ctx.engine)] == ["deal", "deal", "explore"]


def test_rerun_replaces_the_days_shortlist(make_ctx):
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    shortlist.run(ctx)
    assert [rank for rank, *_ in entries(ctx.engine)] == [1, 2, 3, 4, 5, 6]


def test_same_day_rerun_keeps_the_same_exploration_picks(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 2)
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    first = [dates for _, _, dates, _ in entries(ctx.engine)]
    for dep, ret in first:  # live_verify checked them earlier today
        add_live_check(ctx.engine, dep, ret, run_date=RUN)
    shortlist.run(ctx)
    assert [dates for _, _, dates, _ in entries(ctx.engine)] == first
```

- [ ] **Step 5: Write the failing test file** `tests/pipeline/test_score.py`

```python
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from ptopilot.db.models import Candidate, PriceObservation, RouteBaseline, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, score
from ptopilot.pipeline.score import pick_option
from tests.pipeline.conftest import RUN, add_observation, add_tracker, add_user

JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 12), date(2027, 6, 20))
USER = SimpleNamespace(
    max_stops_short=1, max_stops_long=2, allow_overnight_layover=False, friday_evening_min_time=time(17, 0)
)


def obs(id, price, stops=1, duration=780, dep=time(18, 0), overnight=False):
    return PriceObservation(
        id=id,
        price=Decimal(price),
        stops=stops,
        duration_min=duration,
        outbound_departure=datetime.combine(date(2027, 6, 12), dep),
        overnight_layover=overnight,
    )


def test_pick_option_applies_every_filter():
    options = [
        obs(1, 500, stops=3),  # too many stops for long haul (fastest 780 min >= 600)
        obs(2, 520, overnight=True),  # overnight layover not allowed
        obs(3, 540, duration=1200),  # > 1.5x fastest (780)
        obs(4, 600),
        obs(5, 650, stops=0),
    ]
    assert pick_option(options, USER, evening_departure=False).id == 4


def test_pick_option_short_haul_uses_short_stop_limit():
    options = [obs(1, 200, stops=2, duration=300), obs(2, 250, stops=1, duration=320)]
    assert pick_option(options, USER, evening_departure=False).id == 2


def test_pick_option_evening_variant_needs_late_departure():
    options = [obs(1, 500, dep=time(9, 0)), obs(2, 600, dep=time(19, 30))]
    assert pick_option(options, USER, evening_departure=True).id == 2
    assert pick_option(options, USER, evening_departure=False).id == 1


def test_pick_option_none_when_nothing_passes():
    assert pick_option([obs(1, 500, stops=4)], USER, evening_departure=False) is None
    assert pick_option([], USER, evening_departure=False) is None


def candidates(engine):
    with session_scope(engine) as s:
        rows = s.execute(select(Candidate, RouteQuery).join(RouteQuery)).all()
        return {(rq.depart_date, rq.return_date): c for c, rq in rows}


def baseline(engine, median=1000, sigma=100):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                month=JUNE,
                length_bucket="week",
                median=Decimal(median),
                sigma=Decimal(sigma),
                n=20,
                confidence="normal",
            )
        )


def setup(make_ctx, **tracker_fields):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine), **tracker_fields)
    expand.run(ctx)
    return ctx


def test_verified_price_scored_against_baseline(make_ctx):
    ctx = setup(make_ctx)
    baseline(ctx.engine)
    add_observation(ctx.engine, *TRIP, 820, observed=RUN, verified=True, stops=1, duration_min=780)
    add_observation(ctx.engine, *TRIP, 790, observed=RUN, verified=True, stops=3, duration_min=780)
    counts = score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.price, c.verified, c.confidence) == (820, True, "normal")
    assert c.z == -1.8 and c.deal_level == "great"
    assert 0 < c.go_now <= 100
    assert counts["deal_great"] == 1


def test_cached_exact_fare_is_an_unverified_fallback(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, *TRIP, 900, observed=RUN)
    score.run(ctx)
    c = candidates(ctx.engine)[TRIP]
    assert (c.price, c.verified, c.z, c.deal_level, c.confidence) == (900, False, None, "none", "low")


def test_month_level_fares_never_become_a_candidate_price(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, date(2027, 6, 2), date(2027, 6, 9), 300, observed=RUN)
    counts = score.run(ctx)
    assert counts == {"no_price": 6}


def test_max_price_drops_expensive_trips(make_ctx):
    ctx = setup(make_ctx, max_price=Decimal(800))
    add_observation(ctx.engine, *TRIP, 900, observed=RUN, verified=True, stops=1, duration_min=780)
    assert score.run(ctx)["over_max_price"] == 1
    assert candidates(ctx.engine) == {}


def test_rerun_replaces_the_days_candidates(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, *TRIP, 900, observed=RUN)
    score.run(ctx)
    score.run(ctx)
    with session_scope(ctx.engine) as s:
        assert len(list(s.scalars(select(Candidate)))) == 1


def test_no_cached_fallback_when_live_options_were_all_rejected(make_ctx):
    ctx = setup(make_ctx)
    add_observation(ctx.engine, *TRIP, 650, observed=RUN, verified=True, stops=3, duration_min=780)
    add_observation(ctx.engine, *TRIP, 600, observed=RUN)  # cached fare, probably the same 3-stop flight
    counts = score.run(ctx)
    assert counts["rejected_by_filters"] == 1
    assert TRIP not in candidates(ctx.engine)
```

- [ ] **Step 6: Write the failing test file** `tests/pipeline/test_open_jaw.py`

```python
"""Open-jaw routes (fly into Porto, home from Santiago) through the pipeline."""

from datetime import date

from sqlalchemy import select

from ptopilot.db.models import Candidate, PriceObservation, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import broad_scan, expand, live_verify, runner, shortlist
from tests.pipeline.conftest import FakeLiveSource, FakeMonthSource, add_tracker, add_user, answering, option

MARCH = ((date(2027, 3, 1), date(2027, 3, 31)),)


def camino(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    uid = add_user(ctx.engine, home_airport="JFK", windows=MARCH, weather_tolerance="relaxed")
    add_tracker(ctx.engine, uid, code="CAMINO_PORTUGUES", min_stay=11, max_stay=14)
    return ctx


def route_queries(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(RouteQuery)))


def test_expand_creates_open_jaw_route_queries(make_ctx):
    ctx = camino(make_ctx)
    expand.run(ctx)
    rqs = route_queries(ctx.engine)
    assert rqs
    assert {(rq.origin, rq.dest_airport, rq.return_airport) for rq in rqs} == {("JFK", "OPO", "SCQ")}


def test_broad_scan_skips_open_jaw_routes(make_ctx):
    source = FakeMonthSource()
    ctx = camino(make_ctx, month_source=source)
    expand.run(ctx)
    assert broad_scan.run(ctx) == {}
    assert source.calls == []


def test_open_jaw_goes_only_to_capable_sources_without_tripping_the_breaker(make_ctx):
    google = FakeLiveSource("google_flights", answering(option(800)))
    serp = FakeLiveSource("serpapi", answering(option(959), source="serpapi"), supports_open_jaw=True)
    ctx = camino(make_ctx, live_sources=[google, serp])
    expand.run(ctx)
    shortlist.run(ctx)
    counts = live_verify.run(ctx)
    assert google.calls == []
    assert "google_flights_breaker_tripped" not in counts
    assert counts["serpapi_ok"] >= 1
    assert all(q.return_from == "SCQ" and q.open_jaw for q in serp.calls)
    with session_scope(ctx.engine) as s:
        assert {o.return_airport for o in s.scalars(select(PriceObservation))} == {"SCQ"}


def test_open_jaw_without_a_capable_source_is_counted_not_failed(make_ctx):
    google = FakeLiveSource("google_flights", answering(option(800)))
    ctx = camino(make_ctx, live_sources=[google])
    expand.run(ctx)
    shortlist.run(ctx)
    counts = live_verify.run(ctx)
    assert google.calls == []
    assert counts["no_open_jaw_source"] >= 1


def test_open_jaw_end_to_end_produces_candidates(make_ctx):
    serp = FakeLiveSource("serpapi", answering(option(959), source="serpapi"), supports_open_jaw=True)
    ctx = camino(make_ctx, live_sources=[serp])
    statuses = {r.stage: r.status for r in runner.run_pipeline(ctx)}
    assert statuses["score"] == "ok"
    with session_scope(ctx.engine) as s:
        rows = s.execute(select(Candidate, RouteQuery).join(RouteQuery)).all()
    assert rows
    assert all(rq.return_airport == "SCQ" and c.verified and c.price == 959 for c, rq in rows)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/db tests/pipeline -q`
Expected: 28 failed, 55 passed. Typical errors: `TypeError: 'return_airport' is an invalid keyword argument for RouteQuery` (or `PriceObservation`, `RouteBaseline`), `StringDataRightTruncation: value too long for type character varying(8)` (`CAMINO_PORTUGUES`), `KeyError: 'beyond_horizon'`.

- [ ] **Step 8: Write** `ptopilot/db/models.py`

```python
"""SQLAlchemy models for every table in spec §5."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Numeric(10, 2)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("weather_tolerance IN ('strict', 'normal', 'relaxed')", name="weather_tolerance"),
        CheckConstraint("0 < min_trip_days AND min_trip_days <= max_trip_days", name="trip_days"),
        CheckConstraint("pto_days_total >= 0 AND pto_committed >= 0", name="pto_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    home_airport: Mapped[str] = mapped_column(String(3))
    nearby_airports: Mapped[list[str]] = mapped_column(ARRAY(String(3)), server_default="{}")
    country: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    holiday_calendar: Mapped[str] = mapped_column(String(16))
    extra_days_off: Mapped[list[date]] = mapped_column(ARRAY(Date), server_default="{}")
    ignored_holidays: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    pto_days_total: Mapped[int] = mapped_column(SmallInteger)
    pto_committed: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    min_trip_days: Mapped[int] = mapped_column(SmallInteger, server_default="3")
    max_trip_days: Mapped[int] = mapped_column(SmallInteger)
    weather_tolerance: Mapped[str] = mapped_column(String(8), server_default="normal")
    max_stops_short: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    max_stops_long: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    allow_overnight_layover: Mapped[bool] = mapped_column(server_default="false")
    friday_evening_departure: Mapped[bool] = mapped_column(server_default="false")
    friday_evening_min_time: Mapped[time] = mapped_column(Time, server_default="17:00")
    created_at: Mapped[datetime] = created_at()


class Invite(Base):
    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    invited_at: Mapped[datetime] = created_at()


class TravelWindow(Base):
    __tablename__ = "travel_windows"
    __table_args__ = (CheckConstraint("start_date <= end_date", name="ordered"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date]
    end_date: Mapped[date]


class Tracker(Base):
    __tablename__ = "trackers"
    __table_args__ = (
        CheckConstraint("0 < min_stay_days AND min_stay_days <= max_stay_days", name="stay_days"),
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    destination_code: Mapped[str] = mapped_column(String(32))
    min_stay_days: Mapped[int] = mapped_column(SmallInteger)
    max_stay_days: Mapped[int] = mapped_column(SmallInteger)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    max_price: Mapped[Decimal | None] = mapped_column(Money)
    snoozed_until: Mapped[date | None]
    active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = created_at()


class TrackerExclusion(Base):
    __tablename__ = "tracker_exclusions"
    __table_args__ = (UniqueConstraint("tracker_id", "depart_date", "return_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    depart_date: Mapped[date]
    return_date: Mapped[date]


class RouteQuery(Base):
    """A shared, de-duplicated search unit (origin, airport, dates) used by any number of trackers."""

    __tablename__ = "route_queries"
    __table_args__ = (
        UniqueConstraint(
            "origin",
            "dest_airport",
            "return_airport",
            "depart_date",
            "return_date",
            name="uq_route_queries_trip",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    dest_airport: Mapped[str] = mapped_column(String(3))  # fly into
    return_airport: Mapped[str] = mapped_column(String(3))  # fly home from (differs only for open-jaw)
    depart_date: Mapped[date]
    return_date: Mapped[date]


class TrackerRouteLink(Base):
    """Why a tracker wants a route_query on a given run: the trip shape's PTO facts and season."""

    __tablename__ = "tracker_route_links"
    __table_args__ = (UniqueConstraint("tracker_id", "route_query_id", "run_date", "evening_departure"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    route_query_id: Mapped[int] = mapped_column(
        ForeignKey("route_queries.id", ondelete="CASCADE"), index=True
    )
    run_date: Mapped[date] = mapped_column(index=True)
    evening_departure: Mapped[bool] = mapped_column(server_default="false")
    pto_cost: Mapped[int] = mapped_column(SmallInteger)
    days_away: Mapped[int] = mapped_column(SmallInteger)
    efficiency: Mapped[float]
    month: Mapped[int] = mapped_column(SmallInteger)
    season_rating: Mapped[str] = mapped_column(String(8))
    days_off: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")


class PriceObservation(Base):
    """Every price ever seen. Append-only: never update or delete rows."""

    __tablename__ = "price_observations"
    __table_args__ = (
        Index("ix_price_observations_route_month", "origin", "dest_airport", "month"),
        Index("ix_price_observations_route_dates", "origin", "dest_airport", "depart_date", "return_date"),
        Index("ix_price_observations_verified_observed_at", "verified", "observed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    dest_airport: Mapped[str] = mapped_column(String(3))
    return_airport: Mapped[str] = mapped_column(String(3))
    depart_date: Mapped[date | None]
    return_date: Mapped[date | None]
    month: Mapped[date]  # first day of the departure month
    source: Mapped[str] = mapped_column(String(32))
    price: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    carrier: Mapped[str | None] = mapped_column(String(120))
    stops: Mapped[int | None] = mapped_column(SmallInteger)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    outbound_departure: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    flight_numbers: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default="{}")
    overnight_layover: Mapped[bool | None]
    deep_link: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(server_default="false")
    typical_low: Mapped[Decimal | None] = mapped_column(
        Money
    )  # Google's typical range, when the source has it
    typical_high: Mapped[Decimal | None] = mapped_column(Money)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShortlistEntry(Base):
    """Route queries picked for a live check on a run, in check order."""

    __tablename__ = "shortlist_entries"
    __table_args__ = (
        UniqueConstraint("run_date", "route_query_id"),
        CheckConstraint("reason IN ('deal', 'explore')", name="reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    route_query_id: Mapped[int] = mapped_column(ForeignKey("route_queries.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(SmallInteger)
    reason: Mapped[str] = mapped_column(String(8))
    est_price: Mapped[Decimal | None] = mapped_column(Money)


class LiveCheck(Base):
    """One attempted live check, whatever the outcome. Drives same-day re-run skips and daily budgets."""

    __tablename__ = "live_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    route_query_id: Mapped[int] = mapped_column(ForeignKey("route_queries.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    ok: Mapped[bool]
    options: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = created_at()


class RouteBaseline(Base):
    __tablename__ = "route_baselines"
    __table_args__ = (CheckConstraint("length_bucket IN ('short', 'week', 'long')", name="length_bucket"),)

    origin: Mapped[str] = mapped_column(String(3), primary_key=True)
    dest_airport: Mapped[str] = mapped_column(String(3), primary_key=True)
    return_airport: Mapped[str] = mapped_column(String(3), primary_key=True)
    month: Mapped[date] = mapped_column(primary_key=True)
    length_bucket: Mapped[str] = mapped_column(String(5), primary_key=True)
    median: Mapped[Decimal] = mapped_column(Money)
    sigma: Mapped[Decimal] = mapped_column(Money)
    n: Mapped[int]
    confidence: Mapped[str] = mapped_column(String(6))
    google_typical_low: Mapped[Decimal | None] = mapped_column(Money)
    google_typical_high: Mapped[Decimal | None] = mapped_column(Money)
    computed_at: Mapped[datetime] = created_at()


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("tracker_id", "route_query_id", "run_date", "evening_departure"),
        CheckConstraint("deal_level IN ('none', 'good', 'great')", name="deal_level"),
        CheckConstraint("state IN ('new', 'sent', 'snoozed', 'excluded')", name="state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    route_query_id: Mapped[int] = mapped_column(ForeignKey("route_queries.id", ondelete="CASCADE"))
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id", ondelete="SET NULL")
    )
    run_date: Mapped[date] = mapped_column(index=True)
    evening_departure: Mapped[bool] = mapped_column(server_default="false")
    price: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    z: Mapped[float | None]
    deal_level: Mapped[str] = mapped_column(String(5))
    go_now: Mapped[int] = mapped_column(SmallInteger)
    confidence: Mapped[str] = mapped_column(String(6))
    verified: Mapped[bool]
    state: Mapped[str] = mapped_column(String(8), server_default="new")


class DigestSend(Base):
    __tablename__ = "digest_sends"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sent_at: Mapped[datetime] = created_at()
    items: Mapped[list[dict]] = mapped_column(JSONB, server_default="[]")  # [{"candidate_id", "price"}]


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    stage: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    counts: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)


class SourceBudget(Base):
    __tablename__ = "source_budget"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    period: Mapped[date] = mapped_column(primary_key=True)  # first day of the month
    calls_used: Mapped[int] = mapped_column(server_default="0")
```

- [ ] **Step 9: Write** `ptopilot/db/migrations/versions/0004_open_jaw_return_airport.py`

```python
"""open-jaw return airport

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16

Adds `return_airport` (fly home from) to route_queries, price_observations and route_baselines, and widens
trackers.destination_code from 8 to 32 characters (e.g. CAMINO_PORTUGUES).
Existing rows are all round trips, so they are backfilled with their dest_airport before the column
becomes NOT NULL. Alembic doesn't detect primary-key changes, so route_baselines' key is rebuilt by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("route_queries", "price_observations", "route_baselines")


def upgrade() -> None:
    op.alter_column("trackers", "destination_code", type_=sa.String(length=32), existing_nullable=False)
    for table in TABLES:
        op.add_column(table, sa.Column("return_airport", sa.String(length=3), nullable=True))
        op.execute(f"UPDATE {table} SET return_airport = dest_airport")
        op.alter_column(table, "return_airport", nullable=False)

    op.drop_constraint("uq_route_queries_origin", "route_queries", type_="unique")
    op.create_unique_constraint(
        "uq_route_queries_trip",
        "route_queries",
        ["origin", "dest_airport", "return_airport", "depart_date", "return_date"],
    )

    op.drop_constraint("pk_route_baselines", "route_baselines", type_="primary")
    op.create_primary_key(
        "pk_route_baselines",
        "route_baselines",
        ["origin", "dest_airport", "return_airport", "month", "length_bucket"],
    )


def downgrade() -> None:
    # Open-jaw rows can't be represented without return_airport; drop them first.
    op.execute("DELETE FROM route_queries WHERE return_airport <> dest_airport")
    op.execute("DELETE FROM price_observations WHERE return_airport <> dest_airport")
    op.execute("DELETE FROM route_baselines WHERE return_airport <> dest_airport")

    op.drop_constraint("pk_route_baselines", "route_baselines", type_="primary")
    op.create_primary_key(
        "pk_route_baselines", "route_baselines", ["origin", "dest_airport", "month", "length_bucket"]
    )
    op.drop_constraint("uq_route_queries_trip", "route_queries", type_="unique")
    op.create_unique_constraint(
        "uq_route_queries_origin", "route_queries", ["origin", "dest_airport", "depart_date", "return_date"]
    )
    for table in TABLES:
        op.drop_column(table, "return_airport")
    op.alter_column("trackers", "destination_code", type_=sa.String(length=8), existing_nullable=False)
```

- [ ] **Step 10: Write** `ptopilot/pipeline/queries.py`

```python
"""Queries shared by several stages.

A route is (origin, fly-into airport, fly-home-from airport); the last two differ only for open-jaw
trips. Every key below includes all three, so a round trip to Porto and an open-jaw into Porto
never share prices or baselines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.stats import Baseline, length_bucket
from ptopilot.db.models import PriceObservation, RouteBaseline, RouteQuery, TrackerRouteLink

Route = tuple[str, str, str]  # origin, dest_airport, return_airport
DateKey = tuple[str, str, str, date, date]  # route + depart, return
BaselineKey = tuple[str, str, str, date, str]  # route + month, length_bucket


def month_of(d: date) -> date:
    return d.replace(day=1)


def start_of(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def date_key(rq: RouteQuery | PriceObservation) -> DateKey:
    return (rq.origin, rq.dest_airport, rq.return_airport, rq.depart_date, rq.return_date)


def baseline_key(origin: str, dest: str, return_airport: str, depart: date, ret: date) -> BaselineKey:
    return (origin, dest, return_airport, month_of(depart), length_bucket((ret - depart).days + 1))


def rq_baseline_key(rq: RouteQuery) -> BaselineKey:
    return baseline_key(rq.origin, rq.dest_airport, rq.return_airport, rq.depart_date, rq.return_date)


def todays_route_queries(s: Session, run_date: date) -> list[RouteQuery]:
    """Route queries any tracker wants on this run."""
    linked = select(TrackerRouteLink.route_query_id).where(TrackerRouteLink.run_date == run_date)
    return list(s.scalars(select(RouteQuery).where(RouteQuery.id.in_(linked)).order_by(RouteQuery.id)))


@dataclass(frozen=True)
class CachedPrice:
    observation_id: int
    price: Decimal


def cached_prices(
    s: Session, rqs: list[RouteQuery], run_date: date
) -> tuple[dict[DateKey, CachedPrice], dict[tuple[str, str, str, date], CachedPrice]]:
    """Cheapest recent unverified fare per exact date pair, and per (route, month)."""
    since = start_of(run_date - timedelta(days=config.CACHE_LOOKBACK_DAYS))
    routes: set[Route] = {(rq.origin, rq.dest_airport, rq.return_airport) for rq in rqs}
    exact: dict[DateKey, CachedPrice] = {}
    monthly: dict[tuple[str, str, str, date], CachedPrice] = {}
    if not routes:
        return exact, monthly
    rows = s.scalars(
        select(PriceObservation).where(
            PriceObservation.verified.is_(False),
            PriceObservation.observed_at >= since,
            PriceObservation.observed_at < start_of(run_date + timedelta(days=1)),
        )
    )
    for o in rows:
        route = (o.origin, o.dest_airport, o.return_airport)
        if route not in routes:
            continue
        cp = CachedPrice(o.id, o.price)
        mkey = (*route, o.month)
        if mkey not in monthly or cp.price < monthly[mkey].price:
            monthly[mkey] = cp
        if o.depart_date and o.return_date:
            dkey = date_key(o)
            if dkey not in exact or cp.price < exact[dkey].price:
                exact[dkey] = cp
    return exact, monthly


def estimate(rq: RouteQuery, exact: dict, monthly: dict) -> CachedPrice | None:
    return exact.get(date_key(rq)) or monthly.get(
        (rq.origin, rq.dest_airport, rq.return_airport, month_of(rq.depart_date))
    )


def load_baselines(s: Session) -> dict[BaselineKey, Baseline]:
    return {
        (b.origin, b.dest_airport, b.return_airport, b.month, b.length_bucket): Baseline(
            float(b.median), float(b.sigma), b.n, b.confidence
        )
        for b in s.scalars(select(RouteBaseline))
    }
```

- [ ] **Step 11: Write** `ptopilot/pipeline/expand.py`

```python
"""Stage `expand`: turn every active tracker into today's route queries (spec §7).

The season filter (spec's separate `season_filter` stage) happens inside core.planner, before
top-N pruning, so it is not a stage of its own.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import UnknownCodeError
from ptopilot.core.planner import PlannedItinerary, TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.db.models import RouteQuery, Tracker, TrackerExclusion, TrackerRouteLink, TravelWindow, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext

log = logging.getLogger(__name__)


def profile_for(user: User) -> TravelerProfile:
    return TravelerProfile(
        home_airports=(user.home_airport, *user.nearby_airports),
        calendar=WorkCalendar.from_code(user.holiday_calendar, user.extra_days_off, user.ignored_holidays),
        pto_available=user.pto_days_total - user.pto_committed,
        min_trip_days=user.min_trip_days,
        max_trip_days=user.max_trip_days,
        weather_tolerance=user.weather_tolerance,  # type: ignore[arg-type]
        friday_evening_departure=user.friday_evening_departure,
    )


def _route_query_id(s: Session, it: PlannedItinerary, cache: dict) -> int:
    key = (it.origin, it.dest_airport, it.return_airport, it.shape.depart_date, it.shape.return_date)
    if key not in cache:
        names = ("origin", "dest_airport", "return_airport", "depart_date", "return_date")
        values = dict(zip(names, key, strict=True))
        s.execute(insert(RouteQuery).values(**values).on_conflict_do_nothing())
        cache[key] = s.scalar(select(RouteQuery.id).filter_by(**values))
    return cache[key]


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    tomorrow = ctx.run_date + timedelta(days=1)
    with session_scope(ctx.engine) as s:
        s.execute(delete(TrackerRouteLink).where(TrackerRouteLink.run_date == ctx.run_date))
        rows = s.execute(
            select(Tracker, User)
            .join(User, Tracker.user_id == User.id)
            .where(
                Tracker.active.is_(True),
                or_(Tracker.snoozed_until.is_(None), Tracker.snoozed_until < ctx.run_date),
            )
            .order_by(Tracker.id)
        ).all()
        windows: defaultdict[int, list[Window]] = defaultdict(list)
        for w in s.scalars(select(TravelWindow).where(TravelWindow.end_date >= tomorrow)):
            windows[w.user_id].append(Window(max(w.start_date, tomorrow), w.end_date))
        excluded = {(e.tracker_id, e.depart_date, e.return_date) for e in s.scalars(select(TrackerExclusion))}

        cache: dict = {}
        for tracker, user in rows:
            counts["trackers"] += 1
            if not windows[user.id]:
                counts["trackers_without_windows"] += 1
                continue
            try:
                spec = TrackerSpec(tracker.destination_code, tracker.min_stay_days, tracker.max_stay_days)
                itineraries = plan_itineraries(
                    profile_for(user), spec, windows[user.id], ctx.geo, ctx.seasons
                )
            except (UnknownCodeError, ValueError) as exc:
                counts["tracker_errors"] += 1
                log.warning("tracker %s skipped: %s", tracker.id, exc)
                continue
            for it in itineraries:
                shape = it.shape
                if shape.depart_date < tomorrow:
                    continue
                if (tracker.id, shape.depart_date, shape.return_date) in excluded:
                    counts["excluded"] += 1
                    continue
                s.add(
                    TrackerRouteLink(
                        tracker_id=tracker.id,
                        route_query_id=_route_query_id(s, it, cache),
                        run_date=ctx.run_date,
                        evening_departure=shape.evening_departure,
                        pto_cost=shape.pto_cost,
                        days_away=shape.days_away,
                        efficiency=shape.efficiency,
                        month=it.month,
                        season_rating=it.season_rating,
                        days_off=list(shape.days_off),
                    )
                )
                counts["links"] += 1
        counts["route_queries"] = len(cache)
    return dict(counts)
```

- [ ] **Step 12: Write** `ptopilot/pipeline/broad_scan.py`

```python
"""Stage `broad_scan`: one cached month scan per (origin, airport, month) needed today (spec §7).

Only two kinds of quote are stored, to keep the append-only table small (Neon's free tier is 0.5 GB):
the cheapest quote for each date pair some tracker wants today, and the month's single cheapest quote
(which `shortlist` uses as the month-level estimate). Route-months already scanned today are skipped.
Open-jaw routes are skipped entirely: the cache only holds plain round trips.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import date_key, month_of, start_of, todays_route_queries
from ptopilot.sources.base import FareQuote, SourceUnavailable

log = logging.getLogger(__name__)


def _keep(quotes: list[FareQuote], tracked: set) -> list[FareQuote]:
    round_trips = [q for q in quotes if q.return_date is not None]
    best: dict[tuple, FareQuote] = {}
    for q in round_trips:
        key = (q.origin, q.dest_airport, q.dest_airport, q.depart_date, q.return_date)
        if key in tracked and (key not in best or q.price < best[key].price):
            best[key] = q
    cheapest = min(round_trips, key=lambda q: q.price, default=None)
    kept = list(best.values())
    if cheapest is not None and cheapest not in kept:
        kept.append(cheapest)
    return kept


def _observation(ctx: RunContext, q: FareQuote) -> PriceObservation:
    return PriceObservation(
        origin=q.origin,
        dest_airport=q.dest_airport,
        return_airport=q.dest_airport,
        depart_date=q.depart_date,
        return_date=q.return_date,
        month=month_of(q.depart_date),
        source=q.source,
        price=Decimal(str(q.price)),
        currency=q.currency or config.DEFAULT_CURRENCY,
        carrier=q.airline,
        stops=q.stops,
        duration_min=q.duration_min,
        flight_numbers=[q.flight_number] if q.flight_number else [],
        deep_link=q.deep_link,
        verified=False,
        observed_at=ctx.stamp(),
    )


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.month_source is None:
        raise StageSkipped("no month-scan source configured (set TRAVELPAYOUTS_TOKEN)")
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        rqs = [rq for rq in todays_route_queries(s, ctx.run_date) if rq.return_airport == rq.dest_airport]
        tracked = {date_key(rq) for rq in rqs}
        keys = sorted({(rq.origin, rq.dest_airport, month_of(rq.depart_date)) for rq in rqs})
        scanned_today = set(
            s.execute(
                select(PriceObservation.origin, PriceObservation.dest_airport, PriceObservation.month).where(
                    PriceObservation.verified.is_(False),
                    PriceObservation.observed_at >= start_of(ctx.run_date),
                    PriceObservation.observed_at < start_of(ctx.run_date + timedelta(days=1)),
                )
            ).all()
        )
    last_error = ""
    for origin, dest, month in keys:
        if (origin, dest, month) in scanned_today:
            counts["already_scanned"] += 1
            continue
        try:
            quotes = ctx.month_source.month_scan(
                origin, dest, month, market=ctx.geo.airport(origin).country, currency=config.DEFAULT_CURRENCY
            )
        except SourceUnavailable as exc:
            counts["scans_failed"] += 1
            last_error = str(exc)
            log.warning("month scan %s-%s %s failed: %s", origin, dest, month, exc)
            continue
        counts["scans_ok"] += 1
        kept = _keep(quotes, tracked)
        with session_scope(ctx.engine) as s:
            s.add_all(_observation(ctx, q) for q in kept)
        counts["quotes"] += len(kept)
    if keys and not counts["scans_ok"] and not counts["already_scanned"]:
        raise StageFailed(f"all {len(keys)} month scans failed; last error: {last_error}")
    return dict(counts)
```

- [ ] **Step 13: Write** `ptopilot/pipeline/shortlist.py`

```python
"""Stage `shortlist`: choose which route queries get a live check today (spec §7).

Two kinds of entry, deals first in check order:
- deal: the cached price is at or below ~p35 of a confident baseline, ranked by
  deal strength × urgency × tracker priority.
- explore: routes with too little history (n < COLD_START_N) or no cached price at all, least
  recently live-checked first (any outcome, from `live_checks`, so "no flights" counts as checked).
  EXPLORATION_QUOTA slots are reserved for these so history keeps building even on days full of deals,
  and exploration also takes any of the LIVE_CHECK_CAP slots that deals leave unused.

Departures more than LIVE_HORIZON_DAYS out are left alone: Google can't price them yet.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from ptopilot import config
from ptopilot.core.stats import z_score
from ptopilot.db.models import LiveCheck, ShortlistEntry, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    cached_prices,
    date_key,
    estimate,
    load_baselines,
    rq_baseline_key,
    todays_route_queries,
)

NEVER = datetime.min


def urgency(days_until: int) -> float:
    if days_until < 30:
        return config.URGENCY["soon"]
    if days_until <= 120:
        return config.URGENCY["sweet"]
    return config.URGENCY["far"]


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        s.execute(delete(ShortlistEntry).where(ShortlistEntry.run_date == ctx.run_date))
        rqs = todays_route_queries(s, ctx.run_date)
        exact, monthly = cached_prices(s, rqs, ctx.run_date)
        baselines = load_baselines(s)
        best_priority = dict(
            s.execute(
                select(TrackerRouteLink.route_query_id, func.min(Tracker.priority))
                .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
                .where(TrackerRouteLink.run_date == ctx.run_date)
                .group_by(TrackerRouteLink.route_query_id)
            ).all()
        )
        # Only checks from before today: a same-day re-run must pick the same routes again.
        last_checked = {
            rq_id: when.replace(tzinfo=None)
            for rq_id, when in s.execute(
                select(LiveCheck.route_query_id, func.max(LiveCheck.checked_at))
                .where(LiveCheck.run_date < ctx.run_date)
                .group_by(LiveCheck.route_query_id)
            ).all()
        }

        deals: list[tuple[float, int, Decimal]] = []
        explore: list[tuple[datetime, date, int, Decimal | None]] = []
        for rq in rqs:
            if (rq.depart_date - ctx.run_date).days > config.LIVE_HORIZON_DAYS:
                counts["beyond_horizon"] += 1
                continue
            est = estimate(rq, exact, monthly)
            b = baselines.get(rq_baseline_key(rq))
            if est is None or b is None or b.n < config.COLD_START_N:
                seen = last_checked.get(rq.id, NEVER)
                explore.append((seen, rq.depart_date, rq.id, est.price if est else None))
                continue
            z = z_score(float(est.price), b)
            if z > config.SHORTLIST_Z:
                counts["not_cheap"] += 1
                continue
            weight = config.PRIORITY_WEIGHTS.get(best_priority.get(rq.id, 2), 0.8)
            if date_key(rq) not in exact:
                weight *= config.MONTH_ESTIMATE_WEIGHT
            score = -z * urgency((rq.depart_date - ctx.run_date).days) * weight
            deals.append((score, rq.id, est.price))

        explore.sort()
        deals.sort(key=lambda d: (-d[0], d[1]))
        reserved = min(config.EXPLORATION_QUOTA, len(explore))
        picked_deals = deals[: config.LIVE_CHECK_CAP - reserved]
        picked_explore = explore[: config.LIVE_CHECK_CAP - len(picked_deals)]  # reserved + unused deal slots

        rank = 0
        for _, rq_id, price in picked_deals:
            rank += 1
            s.add(
                ShortlistEntry(
                    run_date=ctx.run_date, route_query_id=rq_id, rank=rank, reason="deal", est_price=price
                )
            )
        for _, _, rq_id, price in picked_explore:
            rank += 1
            s.add(
                ShortlistEntry(
                    run_date=ctx.run_date, route_query_id=rq_id, rank=rank, reason="explore", est_price=price
                )
            )
        counts.update(
            {
                "candidates": len(rqs),
                "deal": len(picked_deals),
                "explore": len(picked_explore),
                "deal_overflow": len(deals) - len(picked_deals),
                "explore_overflow": len(explore) - len(picked_explore),
            }
        )
    return dict(counts)
```

- [ ] **Step 14: Write** `ptopilot/pipeline/live_verify.py`

```python
"""Stage `live_verify`: live exact-date checks for the shortlist, with circuit breaker and budgets (§7).

Sources are tried in order (Google Flights first, SerpApi as fallback). A source that fails
BREAKER_THRESHOLD times in a row is skipped for the rest of the run. Every attempt is recorded in
`live_checks`, which lets a same-day re-run skip routes already checked (even ones with no flights) and
caps budgeted sources (SerpApi) per day; the monthly cap lives in `source_budget`.
Open-jaw queries go only to sources with `supports_open_jaw` (SerpApi); skipping a source that can't
price them never counts toward its circuit breaker.
Every option a source returns is stored as a verified observation; per-user filtering happens in `score`.
"""

from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.db.models import LiveCheck, PriceObservation, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import month_of
from ptopilot.sources.base import ExactQuery, ExactResult, ExactSearchSource, SourceUnavailable

log = logging.getLogger(__name__)


class Budget:
    """Per-day caps (counted from live_checks, so they survive re-runs) and per-month caps (source_budget)."""

    def __init__(self, ctx: RunContext):
        self._ctx = ctx
        self._period = month_of(ctx.run_date)

    def allows(self, source: str) -> bool:
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return True
        if self.used_today(source) >= caps["per_day"]:
            return False
        return self.used_this_month(source) < caps["per_month"]

    def used_today(self, source: str) -> int:
        with session_scope(self._ctx.engine) as s:
            return s.scalar(
                select(func.count()).where(
                    LiveCheck.source == source, LiveCheck.run_date == self._ctx.run_date
                )
            )

    def used_this_month(self, source: str) -> int:
        with session_scope(self._ctx.engine) as s:
            return (
                s.scalar(select(SourceBudget.calls_used).filter_by(source=source, period=self._period)) or 0
            )

    def charge(self, source: str) -> None:
        if source not in config.SOURCE_BUDGETS:
            return
        stmt = insert(SourceBudget).values(source=source, period=self._period, calls_used=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SourceBudget.source, SourceBudget.period],
            set_={"calls_used": SourceBudget.calls_used + 1},
        )
        with session_scope(self._ctx.engine) as s:
            s.execute(stmt)


def _store(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    low, high = result.typical_range or (None, None)
    with session_scope(ctx.engine) as s:
        for o in result.options:
            s.add(
                PriceObservation(
                    origin=rq.origin,
                    dest_airport=rq.dest_airport,
                    return_airport=rq.return_airport,
                    depart_date=rq.depart_date,
                    return_date=rq.return_date,
                    month=month_of(rq.depart_date),
                    source=result.source,
                    price=Decimal(str(o.price)),
                    currency=result.currency,
                    carrier=o.carrier,
                    stops=o.stops,
                    duration_min=o.duration_min,
                    outbound_departure=o.outbound_departure,
                    flight_numbers=list(o.flight_numbers),
                    overnight_layover=o.overnight_layover,
                    deep_link=result.deep_link,
                    verified=True,
                    observed_at=ctx.stamp(),
                    typical_low=None if low is None else Decimal(str(low)),
                    typical_high=None if high is None else Decimal(str(high)),
                )
            )
    return len(result.options)


def _record(
    ctx: RunContext, rq: RouteQuery, source: str, ok: bool, options: int = 0, error: str | None = None
):
    with session_scope(ctx.engine) as s:
        s.add(
            LiveCheck(
                run_date=ctx.run_date,
                route_query_id=rq.id,
                source=source,
                ok=ok,
                options=options,
                error=error,
                checked_at=ctx.stamp(),
            )
        )


def run(ctx: RunContext) -> dict[str, int]:
    if not ctx.live_sources:
        raise StageSkipped("no live sources configured")
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        entries = (
            s.execute(
                select(RouteQuery)
                .join(ShortlistEntry, ShortlistEntry.route_query_id == RouteQuery.id)
                .where(ShortlistEntry.run_date == ctx.run_date)
                .order_by(ShortlistEntry.rank)
            )
            .scalars()
            .all()
        )
        # A re-run of the same day skips routes already checked successfully for this run date.
        checked = set(
            s.scalars(
                select(LiveCheck.route_query_id).where(
                    LiveCheck.run_date == ctx.run_date, LiveCheck.ok.is_(True)
                )
            )
        )

    budget = Budget(ctx)
    consecutive_failures: Counter[str] = Counter()
    disabled: set[str] = set()
    for i, rq in enumerate(entries):
        if rq.id in checked:
            counts["already_checked"] += 1
            continue
        usable: list[ExactSearchSource] = [src for src in ctx.live_sources if src.name not in disabled]
        if not usable:
            counts["unchecked"] += len(entries) - i
            break
        query = ExactQuery(
            rq.origin,
            rq.dest_airport,
            rq.depart_date,
            rq.return_date,
            config.DEFAULT_CURRENCY,
            return_from=rq.return_airport,
        )
        capable = [src for src in usable if src.supports_open_jaw or not query.open_jaw]
        if not capable:  # e.g. open-jaw with SerpApi unconfigured or out of budget for today
            counts["no_open_jaw_source"] += 1
            continue
        for src in capable:
            if not budget.allows(src.name):
                disabled.add(src.name)
                counts[f"{src.name}_budget_exhausted"] += 1
                continue
            budget.charge(src.name)
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
                _record(ctx, rq, src.name, ok=False, error=str(exc))
                counts[f"{src.name}_failed"] += 1
                consecutive_failures[src.name] += 1
                log.warning("%s failed for %s: %s", src.name, query, exc)
                if consecutive_failures[src.name] >= config.BREAKER_THRESHOLD:
                    disabled.add(src.name)
                    counts[f"{src.name}_breaker_tripped"] += 1
                continue
            consecutive_failures[src.name] = 0
            counts[f"{src.name}_ok"] += 1
            counts["options_stored"] += _store(ctx, rq, result)
            _record(ctx, rq, src.name, ok=True, options=len(result.options))
            if not result.options:
                counts["no_flights"] += 1
            break
        else:
            counts["all_sources_failed"] += 1
        if i < len(entries) - 1:
            ctx.sleep(ctx.rng.uniform(*config.LIVE_DELAY_S))

    successes = sum(v for k, v in counts.items() if k.endswith("_ok"))
    # Routes no configured source can price (open-jaw without SerpApi) were never attempted: not a failure.
    pending = len(entries) - counts["already_checked"] - counts["no_open_jaw_source"]
    if pending and not successes:
        raise StageFailed(f"no live check succeeded for {pending} shortlisted routes: {dict(counts)}")
    return dict(counts)
```

- [ ] **Step 15: Write** `ptopilot/pipeline/baselines.py`

```python
"""Stage `baselines`: typical price and spread per (origin, airport, month, trip-length bucket) (spec §7).

Uses the trailing BASELINE_WINDOW_DAYS of observations, cached and verified alike, keeping only the
cheapest price per exact date pair per day so heavily-checked routes don't dominate. The latest
Google typical range for the key (from SerpApi) seeds cold-start baselines.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.core.stats import compute_baseline
from ptopilot.db.models import PriceObservation, RouteBaseline
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    BaselineKey,
    baseline_key,
    rq_baseline_key,
    start_of,
    todays_route_queries,
)


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    since = start_of(ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS))
    until = start_of(ctx.run_date + timedelta(days=1))
    with session_scope(ctx.engine) as s:
        rqs = todays_route_queries(s, ctx.run_date)
        wanted = {rq_baseline_key(rq) for rq in rqs}
        routes = {k[:3] for k in wanted}
        daily_min: dict[tuple, Decimal] = {}
        google: dict[BaselineKey, tuple[object, Decimal, Decimal]] = {}
        rows = s.scalars(
            select(PriceObservation).where(
                PriceObservation.observed_at >= since,
                PriceObservation.observed_at < until,
                PriceObservation.depart_date.is_not(None),
                PriceObservation.return_date.is_not(None),
            )
        )
        for o in rows:
            if (o.origin, o.dest_airport, o.return_airport) not in routes:
                continue
            key = baseline_key(o.origin, o.dest_airport, o.return_airport, o.depart_date, o.return_date)
            if key not in wanted:
                continue
            day_key = (key, o.depart_date, o.return_date, o.observed_at.date())
            if day_key not in daily_min or o.price < daily_min[day_key]:
                daily_min[day_key] = o.price
            if o.typical_low is not None and o.typical_high is not None:
                if key not in google or o.observed_at > google[key][0]:
                    google[key] = (o.observed_at, o.typical_low, o.typical_high)

        prices: defaultdict[BaselineKey, list[float]] = defaultdict(list)
        for (key, *_), price in daily_min.items():
            prices[key].append(float(price))

        for key in sorted(wanted):
            g = google.get(key)
            b = compute_baseline(prices[key], (float(g[1]), float(g[2])) if g else None)
            if b is None:
                counts["no_data"] += 1
                continue
            values = {
                "median": Decimal(str(round(b.median, 2))),
                "sigma": Decimal(str(round(b.sigma, 2))),
                "n": b.n,
                "confidence": b.confidence,
                "google_typical_low": g[1] if g else None,
                "google_typical_high": g[2] if g else None,
                "computed_at": ctx.stamp(),
            }
            origin, dest, return_airport, month, bucket = key
            stmt = insert(RouteBaseline).values(
                origin=origin,
                dest_airport=dest,
                return_airport=return_airport,
                month=month,
                length_bucket=bucket,
                **values,
            )
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["origin", "dest_airport", "return_airport", "month", "length_bucket"],
                    set_=values,
                )
            )
            counts[f"confidence_{b.confidence}"] += 1
    return dict(counts)
```

- [ ] **Step 16: Write** `ptopilot/pipeline/score.py`

```python
"""Stage `score`: one candidate per tracker link with a price, judged against its baseline (spec §7).

Price choice per link: the cheapest of today's verified options that pass the user's filters
(stops, duration, overnight layovers, Friday-evening departure time); otherwise a cached fare for the
exact same dates. Month-level minimums only steer the shortlist; they never become a candidate's price.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import delete, select

from ptopilot import config
from ptopilot.core.scoring import go_now
from ptopilot.core.stats import deal_level, z_score
from ptopilot.db.models import Candidate, PriceObservation, RouteQuery, Tracker, TrackerRouteLink, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    DateKey,
    cached_prices,
    date_key,
    load_baselines,
    rq_baseline_key,
    start_of,
    todays_route_queries,
)


def pick_option(
    options: list[PriceObservation], user: User, evening_departure: bool
) -> PriceObservation | None:
    """Cheapest verified option that passes this user's filters."""
    if not options:
        return None
    durations = [o.duration_min for o in options if o.duration_min]
    fastest = min(durations) if durations else None
    long_haul = fastest is not None and fastest >= config.SHORT_HAUL_MAX_MIN
    max_stops = user.max_stops_long if long_haul else user.max_stops_short
    ok = []
    for o in options:
        if o.stops is not None and o.stops > max_stops:
            continue
        if fastest and o.duration_min and o.duration_min > config.MAX_DURATION_RATIO * fastest:
            continue
        if o.overnight_layover and not user.allow_overnight_layover:
            continue
        if evening_departure and (
            o.outbound_departure is None or o.outbound_departure.time() < user.friday_evening_min_time
        ):
            continue
        ok.append(o)
    return min(ok, key=lambda o: (o.price, o.id), default=None)


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        s.execute(delete(Candidate).where(Candidate.run_date == ctx.run_date))
        rqs = todays_route_queries(s, ctx.run_date)
        exact, _ = cached_prices(s, rqs, ctx.run_date)
        baselines = load_baselines(s)
        wanted = {date_key(rq) for rq in rqs}
        verified: defaultdict[DateKey, list[PriceObservation]] = defaultdict(list)
        for o in s.scalars(
            select(PriceObservation).where(
                PriceObservation.verified.is_(True),
                PriceObservation.observed_at >= start_of(ctx.run_date),
                PriceObservation.observed_at < start_of(ctx.run_date + timedelta(days=1)),
            )
        ):
            key = date_key(o)
            if key in wanted:
                verified[key].append(o)

        rows = s.execute(
            select(TrackerRouteLink, RouteQuery, Tracker, User)
            .join(RouteQuery, RouteQuery.id == TrackerRouteLink.route_query_id)
            .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
            .join(User, User.id == Tracker.user_id)
            .where(TrackerRouteLink.run_date == ctx.run_date)
            .order_by(TrackerRouteLink.id)
        ).all()
        for link, rq, tracker, user in rows:
            live_options = verified[date_key(rq)]
            chosen = pick_option(live_options, user, link.evening_departure)
            if chosen is None and live_options:
                # Live prices exist but none fit this user; the cached fare is likely one of the same flights.
                counts["rejected_by_filters"] += 1
                continue
            if chosen is not None:
                price, obs_id, is_verified, currency = chosen.price, chosen.id, True, chosen.currency
            elif (est := exact.get(date_key(rq))) is not None:  # exact dates only, never a month minimum
                price, obs_id, is_verified, currency = (
                    est.price,
                    est.observation_id,
                    False,
                    config.DEFAULT_CURRENCY,
                )
            else:
                counts["no_price"] += 1
                continue
            if tracker.max_price is not None and price > tracker.max_price:
                counts["over_max_price"] += 1
                continue
            b = baselines.get(rq_baseline_key(rq))
            z = z_score(float(price), b) if b else None
            dest = ctx.geo.destination(tracker.destination_code)
            s.add(
                Candidate(
                    user_id=user.id,
                    tracker_id=tracker.id,
                    route_query_id=rq.id,
                    price_observation_id=obs_id,
                    run_date=ctx.run_date,
                    evening_departure=link.evening_departure,
                    price=price,
                    currency=currency,
                    z=z,
                    deal_level=deal_level(z) if z is not None else "none",
                    go_now=go_now(
                        z,
                        link.season_rating,  # type: ignore[arg-type]
                        link.efficiency,
                        (rq.depart_date - ctx.run_date).days,
                        ctx.geo.is_international(rq.origin, dest),
                    ),
                    confidence=b.confidence if b else "low",
                    verified=is_verified,
                )
            )
            counts["candidates"] += 1
            counts["verified" if is_verified else "unverified"] += 1
            if z is not None:
                counts[f"deal_{deal_level(z)}"] += 1
    return dict(counts)
```

- [ ] **Step 17: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/db tests/pipeline -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **248 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 18: Apply the migration to the dev database**

Run: `.venv/Scripts/python -m alembic upgrade head`
Expected: `Running upgrade 0003 -> 0004, open-jaw return airport`.

- [ ] **Step 19: Commit and push**

```bash
git add ptopilot/db ptopilot/pipeline tests/db tests/pipeline
git commit -m "feat: open-jaw through db and pipeline; search horizon; exploration by live checks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 5: Traveler profile loader

**Files:**
- Create: `ptopilot/profiles.py`, `profiles/example.yaml`
- Modify: `.gitignore` (+ `profiles/*`, `!profiles/example.yaml`), `README.md` (+ Traveler profiles)
- Test: `tests/test_profiles.py`

**Interfaces:**
- Produces: `parse_profile(data: dict, geo: Geo) -> Profile` (raises `ValueError` listing every problem); `apply_profile(session, profile) -> dict` (summary: `user` created/updated, `windows`, `trackers_added/updated/deactivated`; the caller commits); CLI `python -m ptopilot.profiles load PATH [--dry-run]` (exit 2 on an invalid profile).

- [ ] **Step 1: Write** `profiles/example.yaml`

```yaml
# Traveler profile for `python -m ptopilot.profiles load <file>`.
# Copy to profiles/<you>.yaml (git-ignored: it holds your email) and edit.
email: you@example.com
home_airport: JFK
nearby_airports: [EWR, PHL]      # LGA omitted: almost no long-haul international flights
country: US
holiday_calendar: US             # e.g. US, GB-ENG, GB-SCT
ignored_holidays: [Columbus Day, Veterans Day]   # federal holidays your office works
extra_days_off: []               # company days off, YYYY-MM-DD
pto_days_total: 22
pto_committed: 7                 # already spoken for
min_trip_days: 7                 # days away from home
max_trip_days: 16                # two work weeks plus the weekends either side
weather_tolerance: normal        # strict | normal | relaxed ("normal" skips months rated avoid)
max_stops_short: 3
max_stops_long: 3
allow_overnight_layover: true
friday_evening_departure: true   # leave after work on the last workday
friday_evening_min_time: "17:00"
windows:
  - {start: 2027-03-01, end: 2027-03-31}
  - {start: 2027-10-01, end: 2027-10-31}
trackers:                        # min_stay/max_stay: days on the ground, after travel days
  - {destination: PATAGONIA, min_stay: 7, max_stay: 11}         # W Trek (~5 days) + Puerto Natales
  - {destination: AZORES, min_stay: 7, max_stay: 10}
  - {destination: MADEIRA, min_stay: 6, max_stay: 9}
  - {destination: CAMINO_PORTUGUES, min_stay: 11, max_stay: 14}  # walk Porto -> Santiago (open-jaw)
```

- [ ] **Step 2: Write** `.gitignore`

```
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
.ruff_cache/
.env
*.local.*
.pgdata/
.env.*
!.env.example
.neon
node_modules/
profiles/*
!profiles/example.yaml
```

- [ ] **Step 3: Write the failing test file** `tests/test_profiles.py`

```python
from datetime import date, time
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from ptopilot.data import load_geo
from ptopilot.db.models import Invite, Tracker, TravelWindow, User
from ptopilot.profiles import apply_profile, parse_profile

GEO = load_geo()
EXAMPLE = yaml.safe_load((Path(__file__).resolve().parents[1] / "profiles" / "example.yaml").read_text())
EMAIL = "you@example.com"


def mine(model):
    """Rows belonging to the example profile's user (other tests may have committed their own users)."""
    owner = select(User.id).where(User.email == EMAIL).scalar_subquery()
    return select(model).where(model.user_id == owner)


def test_example_profile_is_valid():
    p = parse_profile(EXAMPLE, GEO)
    assert p.email == "you@example.com"
    assert p.user["pto_days_total"] - p.user["pto_committed"] == 15
    assert p.windows == [(date(2027, 3, 1), date(2027, 3, 31)), (date(2027, 10, 1), date(2027, 10, 31))]
    assert [t.destination for t in p.trackers] == ["PATAGONIA", "AZORES", "MADEIRA", "CAMINO_PORTUGUES"]
    assert p.friday_evening_min_time == time(17, 0)


def test_every_problem_is_reported_at_once():
    bad = {
        **EXAMPLE,
        "home_airport": "XXX",
        "ignored_holidays": ["Columbo Day"],
        "windows": [{"start": "2027-03-31", "end": "2027-03-01"}],
        "trackers": [
            {"destination": "ATLANTIS", "min_stay": 5, "max_stay": 9},
            {"destination": "AZORES", "min_stay": 9, "max_stay": 5},
        ],
    }
    with pytest.raises(ValueError) as exc:
        parse_profile(bad, GEO)
    message = str(exc.value)
    for fragment in ("XXX", "Columbo Day", "ends 2027-03-01 before", "ATLANTIS", "AZORES"):
        assert fragment in message


def test_missing_fields_and_typos_are_rejected():
    with pytest.raises(ValueError, match="email") as exc:
        parse_profile({"home_airprot": "JFK"}, GEO)
    assert "home_airprot" in str(exc.value)


def test_apply_creates_then_updates_idempotently(session):
    profile = parse_profile(EXAMPLE, GEO)
    assert apply_profile(session, profile) == {
        "user": "created",
        "windows": 2,
        "trackers_added": 4,
        "trackers_updated": 0,
        "trackers_deactivated": 0,
    }
    first_ids = {t.destination_code: t.id for t in session.scalars(mine(Tracker))}
    assert apply_profile(session, profile)["user"] == "updated"
    assert {t.destination_code: t.id for t in session.scalars(mine(Tracker))} == first_ids  # history kept
    assert session.scalar(select(User.ignored_holidays).where(User.email == EMAIL)) == [
        "Columbus Day",
        "Veterans Day",
    ]
    assert len(list(session.scalars(mine(TravelWindow)))) == 2
    assert session.scalar(select(Invite.email).where(Invite.email == EMAIL)) == EMAIL


def test_trackers_removed_from_the_file_are_deactivated_not_deleted(session):
    apply_profile(session, parse_profile(EXAMPLE, GEO))
    fewer = {**EXAMPLE, "trackers": EXAMPLE["trackers"][:2]}
    summary = apply_profile(session, parse_profile(fewer, GEO))
    assert summary["trackers_deactivated"] == 2
    active = {t.destination_code: t.active for t in session.scalars(mine(Tracker))}
    assert active == {"PATAGONIA": True, "AZORES": True, "MADEIRA": False, "CAMINO_PORTUGUES": False}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/test_profiles.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.profiles'`.

- [ ] **Step 5: Write** `ptopilot/profiles.py`

```python
"""Load a traveler profile (user, travel windows, trackers) from YAML into the database.

    python -m ptopilot.profiles load profiles/me.yaml [--dry-run]

A stopgap until the web app's onboarding (Plan 6) exists. Loading is idempotent and keyed on email:
the user is created or updated, travel windows are replaced, trackers are matched by destination
code (updated in place, so their history and snoozes survive), and trackers missing from the file are
deactivated rather than deleted. The email is also added to `invites`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Geo, UnknownCodeError
from ptopilot.data import load_geo
from ptopilot.db.models import Invite, Tracker, TravelWindow, User
from ptopilot.db.session import make_engine
from ptopilot.settings import Settings

USER_FIELDS = {
    "home_airport": str,
    "country": str,
    "currency": str,
    "holiday_calendar": str,
    "pto_days_total": int,
    "pto_committed": int,
    "min_trip_days": int,
    "max_trip_days": int,
    "weather_tolerance": str,
    "max_stops_short": int,
    "max_stops_long": int,
    "allow_overnight_layover": bool,
    "friday_evening_departure": bool,
}
REQUIRED = ("email", "home_airport", "country", "holiday_calendar", "pto_days_total", "max_trip_days")


@dataclass
class TrackerSpecRow:
    destination: str
    min_stay: int
    max_stay: int
    priority: int = 2
    max_price: Decimal | None = None


@dataclass
class Profile:
    email: str
    user: dict
    nearby_airports: list[str] = field(default_factory=list)
    extra_days_off: list[date] = field(default_factory=list)
    ignored_holidays: list[str] = field(default_factory=list)
    friday_evening_min_time: time | None = None
    windows: list[tuple[date, date]] = field(default_factory=list)
    trackers: list[TrackerSpecRow] = field(default_factory=list)


def _as_date(value, where: str, problems: list[str]) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        problems.append(f"{where}: {value!r} is not a YYYY-MM-DD date")
        return None


def parse_profile(data: dict, geo: Geo) -> Profile:
    """Validate a profile mapping. Raises ValueError listing every problem found."""
    problems: list[str] = []
    data = data or {}
    for key in REQUIRED:
        if data.get(key) in (None, ""):
            problems.append(f"missing required field {key!r}")
    unknown = set(data) - set(USER_FIELDS) - {
        "email", "nearby_airports", "extra_days_off", "ignored_holidays",
        "friday_evening_min_time", "windows", "trackers",
    }  # fmt: skip
    if unknown:
        problems.append(f"unknown field(s) {sorted(unknown)}")

    user = {k: data[k] for k in USER_FIELDS if k in data}
    for key, kind in USER_FIELDS.items():
        if key in user and not isinstance(user[key], kind):
            problems.append(f"{key}: expected {kind.__name__}, got {user[key]!r}")

    for code in [data.get("home_airport"), *(data.get("nearby_airports") or [])]:
        if code:
            try:
                geo.airport(code)
            except UnknownCodeError:
                problems.append(f"unknown airport {code!r} (add it to ptopilot/data/geo.yaml)")

    extra = [_as_date(d, "extra_days_off", problems) for d in data.get("extra_days_off") or []]
    ignored = list(data.get("ignored_holidays") or [])
    if data.get("holiday_calendar"):
        try:
            WorkCalendar.from_code(data["holiday_calendar"], [d for d in extra if d], ignored)
        except ValueError as exc:
            problems.append(str(exc))

    min_time = None
    if data.get("friday_evening_min_time") is not None:
        try:
            min_time = time.fromisoformat(str(data["friday_evening_min_time"]))
        except ValueError:
            problems.append(f"friday_evening_min_time: {data['friday_evening_min_time']!r} is not HH:MM")

    windows = []
    for i, w in enumerate(data.get("windows") or []):
        start = _as_date((w or {}).get("start"), f"windows[{i}].start", problems)
        end = _as_date((w or {}).get("end"), f"windows[{i}].end", problems)
        if start and end:
            if end < start:
                problems.append(f"windows[{i}]: ends {end} before it starts {start}")
            windows.append((start, end))
    if not windows:
        problems.append("at least one travel window is required")

    trackers = []
    seen = set()
    for i, t in enumerate(data.get("trackers") or []):
        t = t or {}
        code = t.get("destination")
        try:
            geo.destination(code)
        except UnknownCodeError:
            problems.append(f"trackers[{i}]: unknown destination {code!r} (add it to ptopilot/data/geo.yaml)")
            continue
        if code in seen:
            problems.append(f"trackers[{i}]: destination {code!r} listed twice")
        seen.add(code)
        lo, hi, prio = t.get("min_stay"), t.get("max_stay"), t.get("priority", 2)
        if not (isinstance(lo, int) and isinstance(hi, int) and 0 < lo <= hi):
            problems.append(f"trackers[{i}] ({code}): need 0 < min_stay <= max_stay, got {lo}..{hi}")
            continue
        if prio not in (1, 2, 3):
            problems.append(f"trackers[{i}] ({code}): priority must be 1, 2 or 3")
        price = t.get("max_price")
        trackers.append(
            TrackerSpecRow(code, lo, hi, prio, Decimal(str(price)) if price is not None else None)
        )
    if not trackers and not any("trackers[" in p for p in problems):
        problems.append("at least one tracker is required")

    if problems:
        raise ValueError("invalid profile:\n  - " + "\n  - ".join(problems))
    return Profile(
        email=str(data["email"]).strip().lower(),
        user=user,
        nearby_airports=list(data.get("nearby_airports") or []),
        extra_days_off=[d for d in extra if d],
        ignored_holidays=ignored,
        friday_evening_min_time=min_time,
        windows=windows,
        trackers=trackers,
    )


def apply_profile(s: Session, p: Profile) -> dict[str, int | str]:
    """Upsert the profile in the given session (caller commits or rolls back). Returns a change summary."""
    summary: dict[str, int | str] = {}
    user = s.scalar(select(User).where(User.email == p.email))
    summary["user"] = "updated" if user else "created"
    if user is None:
        user = User(email=p.email)
        s.add(user)
    for key, value in p.user.items():
        setattr(user, key, value)
    user.nearby_airports = p.nearby_airports
    user.extra_days_off = p.extra_days_off
    user.ignored_holidays = p.ignored_holidays
    if p.friday_evening_min_time is not None:
        user.friday_evening_min_time = p.friday_evening_min_time
    s.flush()

    s.execute(delete(TravelWindow).where(TravelWindow.user_id == user.id))
    s.add_all(TravelWindow(user_id=user.id, start_date=a, end_date=b) for a, b in p.windows)
    summary["windows"] = len(p.windows)

    existing = {t.destination_code: t for t in s.scalars(select(Tracker).where(Tracker.user_id == user.id))}
    added = updated = 0
    for row in p.trackers:
        t = existing.pop(row.destination, None)
        if t is None:
            t = Tracker(user_id=user.id, destination_code=row.destination)
            s.add(t)
            added += 1
        else:
            updated += 1
        t.min_stay_days, t.max_stay_days = row.min_stay, row.max_stay
        t.priority, t.max_price, t.active = row.priority, row.max_price, True
    deactivated = 0
    for t in existing.values():
        if t.active:
            t.active = False
            deactivated += 1
    summary |= {"trackers_added": added, "trackers_updated": updated, "trackers_deactivated": deactivated}

    s.execute(insert(Invite).values(email=p.email).on_conflict_do_nothing())
    s.flush()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.profiles")
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="create or update a traveler from a YAML profile")
    load.add_argument("path", type=Path)
    load.add_argument("--dry-run", action="store_true", help="validate and show changes without saving")
    args = parser.parse_args(argv)

    try:
        profile = parse_profile(yaml.safe_load(args.path.read_text(encoding="utf-8")), load_geo())
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    engine = make_engine(Settings.from_env().database_url)
    with Session(engine) as s:
        summary = apply_profile(s, profile)
        if args.dry_run:
            s.rollback()
        else:
            s.commit()
    verb = "would apply" if args.dry_run else "applied"
    print(f"{verb} profile for {profile.email}: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Write** `README.md`

````markdown
# ptopilot

PTO-aware flight deal tracker. Tell it your PTO budget, office holiday calendar, rough travel windows, and bucket-list destinations; it builds realistic trips, tracks their prices daily, and emails a twice-weekly digest of the ones priced well below normal.

- Design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md)
- Roadmap: [`ROADMAP.md`](ROADMAP.md)

## Development (Windows)

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

### Local database

A private Postgres 17 server lives in `.pgdata/` (git-ignored) on port 5433 with no password, using the binaries from a standard PostgreSQL install. One-time setup:

```powershell
$pg = "C:\Program Files\PostgreSQL\17\bin"
& "$pg\initdb.exe" -D .pgdata -U ptopilot --auth=trust -E UTF8 --locale=C
& "$pg\pg_ctl.exe" -D .pgdata -o "-p 5433" -l .pgdata/server.log start
& "$pg\psql.exe" -h localhost -p 5433 -U ptopilot -d postgres -c "CREATE DATABASE ptopilot" -c "CREATE DATABASE ptopilot_test"
```

After a reboot, start it again with the `pg_ctl ... start` line. Apply migrations to the dev database with `.venv/Scripts/python -m alembic upgrade head`.

### Tests

```powershell
.venv/Scripts/python -m pytest          # database tests skip if the server is down
.venv/Scripts/python -m pytest -m live  # hits real flight sources; run by hand
```

## Traveler profiles

Until the web app's onboarding exists, travelers are loaded from YAML:

```powershell
copy profiles\example.yaml profiles\me.yaml                       # profiles/* is git-ignored (holds your email)
.venv/Scripts/python -m ptopilot.profiles load profiles/me.yaml --dry-run   # validate and preview
.venv/Scripts/python -m ptopilot.profiles load profiles/me.yaml             # save (re-run any time to update)
```

Destinations must exist in `ptopilot/data/geo.yaml` (with season ratings in `seasons.yaml`). A destination with `return_airports` is an **open-jaw** route (fly into one airport, home from another); only SerpApi can price those. Live checks skip departures more than ~300 days out (Google Flights doesn't search that far yet).

## Daily scan

```powershell
.venv/Scripts/python -m ptopilot.pipeline run --dry-run            # whole pipeline, no health email
.venv/Scripts/python -m ptopilot.pipeline run --stage expand       # one stage (repeatable)
.venv/Scripts/python -m ptopilot.pipeline run --date 2026-10-20    # re-run a past day
```

Stages: `expand → broad_scan → shortlist → live_verify → baselines → score`. Each run is recorded in `pipeline_runs`. A failed `expand` or `broad_scan` stops the rest; a failed `live_verify` does not. In production, `.github/workflows/scan.yml` runs it daily at 06:00 UTC (and on demand from the Actions tab, with optional date/stage inputs); `keepalive.yml` stops GitHub from disabling the schedule.

## Neon (production database)

The repo is linked to Neon project `green-feather-91450838`, branch `production` (`.neon`, git-ignored; `neon.ts` declares the services: Postgres only). After `neon login`, `neon env pull` writes `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct) to `.env.local` (git-ignored). Use the direct URL for migrations. The `DATABASE_URL` GitHub secret holds the direct URL, because the scan job runs migrations before the pipeline.

## Configuration

Environment variables (never committed; GitHub Actions secrets in production):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (Neon in production); defaults to the local dev database |
| `TRAVELPAYOUTS_TOKEN` | Cached fares for the broad scan; without it `broad_scan` is skipped |
| `SERPAPI_KEY` | Live-check fallback (~8 searches/run, 250/month) |
| `RESEND_API_KEY`, `ADMIN_EMAIL` | Health email after each scan |
| `EMAIL_FROM` | Sender; defaults to Resend's shared `onboarding@resend.dev`, which only delivers to your own Resend account address |
````

- [ ] **Step 7: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/test_profiles.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **253 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 8: Commit and push**

```bash
git add ptopilot/profiles.py profiles/example.yaml .gitignore README.md tests/test_profiles.py
git commit -m "feat: load traveler profiles from YAML" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Check `git status` shows no `profiles/` file other than `example.yaml` before pushing.

---

### Task 6: Load the author's profile into Neon and start collecting

No code. This connects the production database to the real trips.

- [ ] **Step 1: Create the personal profile.** Copy `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p4\profiles\nick.yaml` to `profiles/nick.yaml`. It's `example.yaml` with the real email. Confirm `git status` doesn't list it.
- [ ] **Step 2: Migrate Neon to 0004 over the direct connection.** Run with `DATABASE_URL` set from `.env.local`'s `DATABASE_URL_UNPOOLED`, without printing it: `.venv/Scripts/python -m alembic upgrade head`. Expected: `Running upgrade 0003 -> 0004`, then `alembic current` → `0004 (head)`. (The scheduled scan would also do this, but the profile load needs the new schema first.)
- [ ] **Step 3: Dry run, then load,** with the same environment: `.venv/Scripts/python -m ptopilot.profiles load profiles/nick.yaml --dry-run`, then without `--dry-run`. Expected: `user=created, windows=2, trackers_added=4, trackers_updated=0, trackers_deactivated=0`.
- [ ] **Step 4: Trigger the scan:** `& "C:\Program Files\GitHub CLI\gh.exe" workflow run scan.yml`, then watch it. Expected: green. In the log, `expand` should show `trackers=4` and about `route_queries=138`, `shortlist` about `beyond_horizon=69, explore=40`, and `live_verify` `google_flights_ok` plus up to 8 `serpapi_ok` (the Camino). The health email arrives at `ADMIN_EMAIL`.
- [ ] **Step 5:** Record the run's headline counts in the ledger. They're the first real data point for Plan 5's digest tuning.

### Final check

- [ ] `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q` → **253 passed, 1 deselected**. `git status` clean. Nothing unpushed. Latest `ci` and `scan` runs green.
