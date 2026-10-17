# ptopilot Plan 7: V2 Look and Feel (design system, landing, dashboard, destination pages, digest, preferred trip length)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the working-but-bare V1 web app and digest into a consistent, professional "travel editorial" product, and let travelers set a preferred trip length that steers both which trips get priced and how they score.

**Architecture:**
- **Design system:** one stylesheet of CSS tokens (`ptopilot/web/static/app.css`), Fraunces + Inter from Google Fonts, and Jinja macros (`templates/_components.html`) that every page composes.
- **Destination colors:** each destination's color comes from `geo.yaml` or its zone (`core.geo.palette`).
- **Pages:** the landing page, dashboard grid and destination page read from a new read-only module (`web/history.py`) over the existing `candidates` table. Charts are server-drawn SVG (`web/viz.py`); there is no JavaScript.
- **Digest:** the email reuses the same palette and bar geometry, built from table cells instead of SVG.
- **Preferred trip length:** a nullable `users.ideal_trip_days` (migration 0005) feeds `select_top` (ranking by efficiency × (1 + 0.25 × fit)) and a new 10% go-now weight.

**Tech Stack:** No new dependencies. FastAPI `StaticFiles` serves the stylesheet; fonts load from Google Fonts.

**Spec:** [`docs/superpowers/specs/2026-10-17-ptopilot-v2-look-and-feel-design.md`](../specs/2026-10-17-ptopilot-v2-look-and-feel-design.md)

## Global Constraints

- **No new runtime dependencies.** No JavaScript on any page. External assets: Google Fonts only (Fraunces opsz 400/600, Inter 400/600/700, `display=swap`).
- **Colors and spacing come from the tokens in `app.css`:** `--bg #fbf7f0`, `--surface #ffffff`, `--ink #1f2937`, `--muted #6b7280`, `--line #f3f4f6`, `--track #e5e7eb`, `--btn #111827`, `--danger #b91c1c`, radius 12px for cards and 8px for controls. Destination colors come only from `core.geo.palette`.
- **Email:** table layout and inline styles only. No SVG, no web fonts (Georgia plus the system sans), a 600px container with an Outlook `<!--[if mso]>` wrapper.
- **Pages:** no horizontal scroll at 375px, 16px side gutter (24px from 768px).
- **No preference means no change:** with `ideal_trip_days` unset, `select_top` ranks exactly as V1 did. The go-now score adds a constant 10 points (length fit 1.0) for every such trip, so the ranking between them is unchanged.
- **Ownership:** a tracker that belongs to another user, or doesn't exist, is a 404 on every page. Malformed requests get the styled 400 page, never JSON.
- **Example cards on the landing page are fixed illustrative data**, never another user's trips.
- **Migration 0005 goes to Neon before the Task 2 push** (Render auto-deploys `main`). Never print, commit or log secrets: `.env.local`, `.env.keys` and `profiles/nick.yaml` stay git-ignored and unread on screen.
- `ruff check .` and `ruff format --check .` must pass. Default `pytest` never touches the network; run database tests with `PTOPILOT_REQUIRE_DB=1`.
- **Work directly on `main`; every task ends with a commit and a `git push`, with the full suite green.** Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Commands run from `C:\Users\nickd\dev\ptopilot` with `.venv/Scripts/python`. The local Postgres must be running on port 5433 (`"C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D .pgdata -o "-p 5433" -l .pgdata/server.log start`).

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **A route with no baseline yet** (a new destination, or one too new to have history) → no price bar, "typical price still being learned", and no crash in the page or the email. *Task 6: `test_trip_options_carry_bar_geometry_when_a_baseline_exists` (FNC has none); Task 12: deals without a bar render through `bars.get`; Task 5: `test_no_baseline_means_no_bar`.*
2. **A thin or ragged price history** (one or two scan days, missed days, a flat price) → an empty-state sentence instead of a chart, broken line segments at gaps, and no division by zero. *Task 5: `test_fewer_than_three_points_has_no_chart`, `test_missing_days_break_the_line_into_segments`, `test_flat_prices_still_draw`, `test_zero_sigma_uses_the_floor_instead_of_dividing_by_zero`.*
3. **A guessed or malformed URL** (another user's tracker id, a deleted one, `/trackers/abc`) → 404 or a styled 400, revealing nothing. *Task 10: `test_someone_elses_or_a_missing_tracker_is_not_found`; Task 7: `test_malformed_path_gets_a_page_not_json`.*
4. **A traveler who never sets an ideal length, or clears it** → V1 behavior: identical trip selection, and the stored value removed. *Task 4: `test_no_preference_plans_exactly_as_before`; Task 2: `test_loading_a_profile_without_an_ideal_clears_a_stored_one`; Task 11: `test_clearing_the_ideal_length_removes_the_preference`.*
5. **A Monday when every deal was already emailed** → the quiet digest says nothing new arrived since the last digest, instead of claiming nothing is below typical. *Task 12: `test_quiet_digest_wording_depends_on_whether_deals_went_out_before`, `test_selection_counts_deals_held_back_as_already_sent`.*

## Verified before writing (2026-10-17)

- **Built test-first in a scratch worktree** (branch `v2-scratch`, never pushed), one commit per task.
- **Replayed on a fresh copy of `main`** by `sim_plan7.py`: for each task, the test files were written first and the named tests watched fail, then the remaining files were written and the full suite and ruff run. The "Verified tail" lines below come from that replay, and the final tree matched the verified branch byte for byte (53 files).
- **Test database hazard found in the replay:** a test database already migrated past `main`'s head makes every database test error at setup (the fixture can't downgrade an unknown revision). The local `ptopilot_test` was reset to 0004 after the scratch runs; if Task 1's suite shows ~137 setup errors, that is the cause.
- **Visual QA with a real server** (uvicorn, a seeded local `ptopilot_preview` database, the example profile with 20 days of Azores history): landing page, dashboard, destination page and profile screenshotted in Chromium at 1280px and 375px, plus the rendered digest at 700px. Task 13 holds the fixes this found. No page scrolls horizontally at 375px.
- Verified files: `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\wt`.

## File structure

```
ptopilot/config.py                          # length fit, selection bonus, go-now weights, MIN_TREND_POINTS
ptopilot/core/geo.py                        # Palette, tint, palette(), ZONE_COLORS, NEUTRAL_PALETTE, Destination.color
ptopilot/core/scoring.py                    # length_fit; go_now(length_fit=)
ptopilot/core/selection.py                  # select_top(ideal_days=)
ptopilot/core/planner.py                    # TravelerProfile.ideal_trip_days
ptopilot/data/geo.yaml                      # per-destination colors
ptopilot/db/models.py                       # User.ideal_trip_days + check constraint
ptopilot/db/migrations/versions/0005_ideal_trip_days.py
ptopilot/profiles.py                        # ideal_trip_days validation
ptopilot/pipeline/expand.py, score.py       # pass the preference through
ptopilot/digest/select.py                   # DealCard.palette/sigma, TrackerRow.palette, Digest.held_back
ptopilot/digest/render.py                   # date_range, bar_cells, render(base_url=)
ptopilot/digest/send.py, __main__.py        # base_url plumbing
ptopilot/digest/templates/digest.{html,txt}.j2
ptopilot/web/viz.py                         # bar_geometry, trend_chart (pure)
ptopilot/web/history.py                     # trip_options, trend, typical_band, destination_summaries
ptopilot/web/samples.py                     # landing page example cards
ptopilot/web/app.py                         # static files, 400 handler, landing, dashboard, /trackers/{id}
ptopilot/web/forms.py                       # ideal_trip_days field
ptopilot/web/static/app.css                 # the design system
ptopilot/web/templates/{base,_components,landing,dashboard,destination,profile,message,login_sent,action_confirm}.html
profiles/example.yaml, pyproject.toml       # ideal_trip_days example; static files packaged
```

## Pre-flight: shared interfaces

| Producer → consumer | Interface | Checked |
|---|---|---|
| 1 → 6, 8, 12 | `palette(dest) -> Palette(color, tint)` | Same names in all four tasks |
| 2 → 4, 11 | `User.ideal_trip_days`; form key `ideal_trip_days` | Same |
| 3 → 4 | `length_fit`, `select_top(ideal_days=)`, `go_now(length_fit=)` | Same keyword names |
| 5 → 6, 10, 12 | `bar_geometry(price, median, sigma)`, `TrendPoint`, `trend_chart(points, band, palette)` | Same |
| 6 → 8, 9, 10 | `DestinationSummary`, `TripOption`, `destination_summaries`, `trip_options`, `trend`, `typical_band` | Same |
| 7 → 8–11 | macros in `_components.html`; filters `dates`, `money`, `day` (+ `stops` from Task 10) | Same |
| 10 → 12 | `/trackers/{id}` URL used by digest rows | Same path |

### Task 1: Destination colors

Every page and the email color a destination the same way. `geo.yaml` gains an optional `color`; anything without one falls back to its zone's color.

**Files:**
- Modify: `ptopilot/core/geo.py`
- Modify: `ptopilot/data/geo.yaml`
- Create: `tests/core/test_palette.py`

**Interfaces:**
- Consumes: `Geo.from_dict`, `Destination` (existing).
- Produces: `ptopilot.core.geo`: `Palette(color: str, tint: str)`, `tint(color: str, amount=0.25) -> str`, `palette(dest: Destination) -> Palette`, `ZONE_COLORS`, `NEUTRAL_COLOR`, and `Destination.color: str | None`.

- [ ] **Step 1: Write the failing test file `tests/core/test_palette.py`**

```python
import pytest

from ptopilot.core.geo import Geo, Palette, palette, tint
from ptopilot.data import load_geo

DATA = {
    "airports": {
        "PDL": {"country": "PT", "zone": "EUROPE"},
        "PUQ": {"country": "CL", "zone": "S_AMERICA"},
        "XXX": {"country": "AQ", "zone": "ANTARCTICA"},
    },
    "destinations": {
        "AZORES": {"name": "Azores", "kind": "region", "airports": ["PDL"], "color": "#0E7490"},
        "PATAGONIA": {"name": "Patagonia", "kind": "region", "airports": ["PUQ"]},
        "POLE": {"name": "South Pole", "kind": "region", "airports": ["XXX"]},
    },
    "travel": {"default": {"overhead_days": 1, "min_trip_days": 2}, "pairs": []},
}
GEO = Geo.from_dict(DATA)


def test_explicit_color_is_used_and_normalized_to_lowercase():
    assert palette(GEO.destination("AZORES")).color == "#0e7490"


def test_missing_color_falls_back_to_the_zone_default():
    assert palette(GEO.destination("PATAGONIA")).color == "#7c2d12"


def test_unknown_zone_falls_back_to_neutral():
    assert palette(GEO.destination("POLE")).color == "#374151"


def test_tint_mixes_a_quarter_of_the_color_into_white():
    assert tint("#000000") == "#bfbfbf"
    assert tint("#ffffff") == "#ffffff"
    assert palette(GEO.destination("AZORES")) == Palette("#0e7490", tint("#0e7490"))


@pytest.mark.parametrize("bad", ["teal", "#0e749", "#0e7490ff", "0e7490", 123])
def test_invalid_color_is_rejected(bad):
    data = {**DATA, "destinations": {"A": {"name": "A", "kind": "city", "airports": ["PDL"], "color": bad}}}
    with pytest.raises(ValueError, match="color"):
        Geo.from_dict(data)


def test_every_seeded_destination_has_its_own_color():
    geo = load_geo()
    colors = [palette(d).color for d in geo.destinations()]
    assert len(colors) == len(set(colors))
    assert palette(geo.destination("MADEIRA")).color == "#15803d"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/core/test_palette.py`

Expected: FAIL. Verified tail: `1 error in 0.49s`

- [ ] **Step 3: Write `ptopilot/core/geo.py` (full new contents)**

```python
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
```

- [ ] **Step 4: Write `ptopilot/data/geo.yaml` (full new contents)**

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

# color: header and accent color in the web app and digest (#rrggbb); optional, defaults by zone.
destinations:
  TH: {name: Thailand, kind: region, airports: [BKK, HKT, CNX], color: "#047857"}
  LIS: {name: Lisbon, kind: city, airports: [LIS], color: "#1d4ed8"}
  TYO: {name: Tokyo, kind: city, airports: [HND, NRT], color: "#be123c"}
  PATAGONIA: {name: "Patagonia (W Trek)", kind: region, airports: [PUQ], color: "#7c2d12"}
  AZORES: {name: Azores, kind: region, airports: [PDL], color: "#0e7490"}
  MADEIRA: {name: Madeira, kind: region, airports: [FNC], color: "#15803d"}
  # Open-jaw: fly into the first list, home from the second.
  CAMINO_PORTUGUES: {name: "Camino Portugués (Porto → Santiago)", kind: route, airports: [OPO], return_airports: [SCQ], color: "#a16207"}

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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/core/test_palette.py`

Expected: PASS. Verified tail: `10 passed in 0.39s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `345 passed, 1 deselected, 1 warning in 39.71s`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(geo): destination colors and palettes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 2: Ideal trip length: storage, profile file and form

`users.ideal_trip_days` (nullable) with a check constraint, loaded from the profile YAML and the profile form. A profile without it clears any stored value.

**Files:**
- Modify: `profiles/example.yaml`
- Create: `ptopilot/db/migrations/versions/0005_ideal_trip_days.py`
- Modify: `ptopilot/db/models.py`
- Modify: `ptopilot/profiles.py`
- Modify: `ptopilot/web/forms.py`
- Create: `tests/test_ideal_trip_days.py`

**Interfaces:**
- Consumes: `profiles.parse_profile`/`apply_profile`, `web.forms` (existing).
- Produces: `User.ideal_trip_days: int | None`; `parse_profile(...).user["ideal_trip_days"]` is always present (None when unset); `web.forms.OPTIONAL_INT_FIELDS`; form key `ideal_trip_days` ("" when unset); migration `0005`.

- [ ] **Step 1: Write the failing test file `tests/test_ideal_trip_days.py`**

```python
"""The optional preferred trip length: profile YAML, database column, and the profile form."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ptopilot.data import load_geo
from ptopilot.db.models import User
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.web.forms import form_to_profile, profile_to_form
from tests.web.conftest import PROFILE_FORM

GEO = load_geo()
EXAMPLE = yaml.safe_load((Path(__file__).resolve().parents[1] / "profiles" / "example.yaml").read_text())


def test_ideal_trip_days_is_optional_and_defaults_to_none():
    data = {k: v for k, v in EXAMPLE.items() if k != "ideal_trip_days"}
    assert parse_profile(data, GEO).user["ideal_trip_days"] is None


def test_example_profile_sets_an_ideal_length():
    assert parse_profile(EXAMPLE, GEO).user["ideal_trip_days"] == 10


@pytest.mark.parametrize("bad", [6, 17, "ten", True])
def test_ideal_trip_days_must_be_a_whole_number_between_min_and_max(bad):
    data = {**EXAMPLE, "min_trip_days": 7, "max_trip_days": 16, "ideal_trip_days": bad}
    with pytest.raises(ValueError, match="ideal_trip_days: "):
        parse_profile(data, GEO)


def test_loading_a_profile_without_an_ideal_clears_a_stored_one(session):
    apply_profile(session, parse_profile(EXAMPLE, GEO))
    data = {k: v for k, v in EXAMPLE.items() if k != "ideal_trip_days"}
    apply_profile(session, parse_profile(data, GEO))
    assert session.scalar(select(User.ideal_trip_days).where(User.email == EXAMPLE["email"])) is None


def test_database_rejects_an_ideal_outside_the_trip_range(session):
    session.add(
        User(
            email="x@example.com",
            home_airport="JFK",
            country="US",
            holiday_calendar="US",
            pto_days_total=10,
            min_trip_days=7,
            max_trip_days=16,
            ideal_trip_days=20,
        )
    )
    with pytest.raises(IntegrityError, match="ideal_trip_days"):
        session.flush()


def test_form_blank_means_no_preference_and_a_number_is_kept():
    blank = form_to_profile({**PROFILE_FORM, "ideal_trip_days": ""}, "a@example.com")
    assert blank.get("ideal_trip_days") is None
    ten = form_to_profile({**PROFILE_FORM, "ideal_trip_days": "10"}, "a@example.com")
    assert ten["ideal_trip_days"] == 10


def test_form_shows_the_stored_ideal_or_blank(session):
    apply_profile(session, parse_profile(EXAMPLE, GEO))
    user = session.scalar(select(User).where(User.email == EXAMPLE["email"]))
    assert profile_to_form(session, user)["ideal_trip_days"] == "10"
    user.ideal_trip_days = None
    assert profile_to_form(session, user)["ideal_trip_days"] == ""
    assert profile_to_form(session, None)["ideal_trip_days"] == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_ideal_trip_days.py`

Expected: FAIL. Verified tail: `7 failed, 1 warning, 3 errors in 3.46s`

- [ ] **Step 3: Write `profiles/example.yaml` (full new contents)**

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
ideal_trip_days: 10              # optional: trips near this length are priced first and score higher
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

- [ ] **Step 4: Write `ptopilot/db/migrations/versions/0005_ideal_trip_days.py`**

```python
"""preferred trip length

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17

Adds the optional users.ideal_trip_days (days away from home). NULL means no preference. When set, it must
lie within the user's min..max trip length.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ideal_trip_days", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ideal_trip_days",
        "users",
        "ideal_trip_days IS NULL OR (min_trip_days <= ideal_trip_days AND ideal_trip_days <= max_trip_days)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_ideal_trip_days"), "users", type_="check")
    op.drop_column("users", "ideal_trip_days")
```

- [ ] **Step 5: Write `ptopilot/db/models.py` (full new contents)**

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
        CheckConstraint(
            "ideal_trip_days IS NULL"
            " OR (min_trip_days <= ideal_trip_days AND ideal_trip_days <= max_trip_days)",
            name="ideal_trip_days",
        ),
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
    ideal_trip_days: Mapped[int | None] = mapped_column(SmallInteger)  # None: no preferred length
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

- [ ] **Step 6: Write `ptopilot/profiles.py` (full new contents)**

```python
"""Load a traveler profile (user, travel windows, trackers) from YAML into the database.

    python -m ptopilot.profiles load profiles/me.yaml [--dry-run]
    python -m ptopilot.profiles invite friend@example.com

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
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
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
    "ideal_trip_days": int,
    "weather_tolerance": str,
    "max_stops_short": int,
    "max_stops_long": int,
    "allow_overnight_layover": bool,
    "friday_evening_departure": bool,
}
REQUIRED = ("email", "home_airport", "country", "holiday_calendar", "pto_days_total", "max_trip_days")
TOLERANCES = ("strict", "normal", "relaxed")
DEFAULT_MIN_TRIP_DAYS = 3  # matches the users.min_trip_days server default


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
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("invalid profile:\n  - the file must be a mapping of field: value pairs")
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
        if key not in user:
            continue
        value = user[key]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            problems.append(f"{key}: expected {kind.__name__}, got {value!r}")
            user.pop(key)

    def ok_int(key):
        return isinstance(user.get(key), int)

    email = str(data.get("email") or "")
    if email and not ("@" in email and "." in email.rsplit("@", 1)[-1]):
        problems.append(f"email: {email!r} is not an email address")
    if "country" in user and not (len(user["country"]) == 2 and user["country"].isalpha()):
        problems.append(f"country: expected a 2-letter code like US, got {user['country']!r}")
    if "currency" in user and not (len(user["currency"]) == 3 and user["currency"].isalpha()):
        problems.append(f"currency: expected a 3-letter code like USD, got {user['currency']!r}")
    if "weather_tolerance" in user and user["weather_tolerance"] not in TOLERANCES:
        problems.append(
            f"weather_tolerance: must be one of {list(TOLERANCES)}, got {user['weather_tolerance']!r}"
        )
    if ok_int("max_trip_days"):
        lo = user.get("min_trip_days", DEFAULT_MIN_TRIP_DAYS)
        if isinstance(lo, int) and not 0 < lo <= user["max_trip_days"]:
            problems.append(
                f"min_trip_days/max_trip_days: need 0 < min <= max, got {lo}..{user['max_trip_days']}"
            )
    if ok_int("ideal_trip_days"):
        lo, hi = user.get("min_trip_days", DEFAULT_MIN_TRIP_DAYS), user.get("max_trip_days")
        if isinstance(lo, int) and isinstance(hi, int) and not lo <= user["ideal_trip_days"] <= hi:
            problems.append(
                f"ideal_trip_days: {user['ideal_trip_days']} is outside your trip length {lo}..{hi}"
            )
    user.setdefault("ideal_trip_days", None)  # absent means no preference, and clears a stored one
    if ok_int("pto_days_total") and user["pto_days_total"] < 0:
        problems.append("pto_days_total: must be 0 or more")
    if ok_int("pto_committed"):
        if user["pto_committed"] < 0:
            problems.append("pto_committed: must be 0 or more")
        elif ok_int("pto_days_total") and user["pto_committed"] > user["pto_days_total"]:
            problems.append(
                f"pto_committed: {user['pto_committed']} is more than pto_days_total {user['pto_days_total']}"
            )
    for key in ("max_stops_short", "max_stops_long"):
        if ok_int(key) and user[key] < 0:
            problems.append(f"{key}: must be 0 or more")

    nearby = list(data.get("nearby_airports") or [])
    dupes = sorted({c for c in nearby if c == data.get("home_airport") or nearby.count(c) > 1})
    if dupes:
        problems.append(f"nearby_airports: {dupes} repeat the home airport or each other")

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
        if not isinstance(w, dict):
            problems.append(f"windows[{i}]: expected {{start: YYYY-MM-DD, end: YYYY-MM-DD}}, got {w!r}")
            continue
        start = _as_date(w.get("start"), f"windows[{i}].start", problems)
        end = _as_date(w.get("end"), f"windows[{i}].end", problems)
        if start and end:
            if end < start:
                problems.append(f"windows[{i}]: ends {end} before it starts {start}")
            windows.append((start, end))
    if not windows:
        problems.append("at least one travel window is required")

    trackers = []
    seen = set()
    for i, t in enumerate(data.get("trackers") or []):
        if not isinstance(t, dict):
            problems.append(
                f"trackers[{i}]: expected {{destination: CODE, min_stay: N, max_stay: N}}, got {t!r}"
            )
            continue
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
        max_price = None
        if price is not None:
            try:
                max_price = Decimal(str(price))
            except InvalidOperation:
                max_price = None
            if max_price is None or isinstance(price, bool) or not max_price.is_finite() or max_price <= 0:
                problems.append(f"trackers[{i}] ({code}): max_price must be a positive number, got {price!r}")
                continue
        trackers.append(TrackerSpecRow(code, lo, hi, prio, max_price))
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
    invite = sub.add_parser("invite", help="allow an email address to sign in to the web app")
    invite.add_argument("email")
    args = parser.parse_args(argv)

    if args.command == "invite":
        email = args.email.strip().lower()
        if "@" not in email:
            print(f"not an email address: {args.email!r}", file=sys.stderr)
            return 2
        with Session(make_engine(Settings.from_env().database_url)) as s:
            s.execute(insert(Invite).values(email=email).on_conflict_do_nothing())
            s.commit()
        print(f"invited {email}")
        return 0

    try:
        profile = parse_profile(yaml.safe_load(args.path.read_text(encoding="utf-8")), load_geo())
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    engine = make_engine(Settings.from_env().database_url)
    try:
        with Session(engine) as s:
            summary = apply_profile(s, profile)
            if args.dry_run:
                s.rollback()
            else:
                s.commit()
    except SQLAlchemyError as exc:  # nothing was saved: the session rolls back on close
        print(
            f"database rejected the profile: {type(exc).__name__}: {str(exc).splitlines()[0]}",
            file=sys.stderr,
        )
        return 2
    verb = "would apply" if args.dry_run else "applied"
    print(f"{verb} profile for {profile.email}: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Write `ptopilot/web/forms.py` (full new contents)**

```python
"""Profile form <-> the YAML-shaped profile dict, so the web form reuses profiles.parse_profile/apply_profile.

The form flattens lists into numbered fields (window_start_0, tracker_dest_1, ...). Blank rows are
ignored. Values that don't parse as numbers are passed through as text so parse_profile reports them.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot.db.models import Tracker, TravelWindow, User

INT_FIELDS = (
    "pto_days_total", "pto_committed", "min_trip_days", "max_trip_days", "max_stops_short", "max_stops_long",
)  # fmt: skip
OPTIONAL_INT_FIELDS = ("ideal_trip_days",)  # blank means "no preference"
TEXT_FIELDS = ("home_airport", "country", "holiday_calendar", "weather_tolerance")
BOOL_FIELDS = ("allow_overnight_layover", "friday_evening_departure")
EXTRA_ROWS = 2  # blank rows offered for new windows and trackers


def _int(value: str):
    value = (value or "").strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value or None


def _list(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _rows(form: Mapping[str, str], prefix: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    rows, i = [], 0
    while any(f"{prefix}_{f}_{i}" in form for f in fields):
        row = {f: (form.get(f"{prefix}_{f}_{i}") or "").strip() for f in fields}
        if any(row.values()):
            rows.append(row)
        i += 1
    return rows


def form_to_profile(form: Mapping[str, str], email: str) -> dict:
    """Build a profile mapping (the YAML shape) from submitted form fields."""
    data: dict = {"email": email}
    for key in TEXT_FIELDS:
        value = (form.get(key) or "").strip()
        if value:
            data[key] = value.upper() if key in ("home_airport", "country") else value
    for key in INT_FIELDS + OPTIONAL_INT_FIELDS:
        value = _int(form.get(key, ""))
        if value is not None:
            data[key] = value
    for key in BOOL_FIELDS:
        data[key] = form.get(key) in ("on", "true", "1")
    data["nearby_airports"] = [code.upper() for code in _list(form.get("nearby_airports", ""))]
    data["ignored_holidays"] = _list(form.get("ignored_holidays", ""))
    data["extra_days_off"] = _list(form.get("extra_days_off", ""))
    if (form.get("friday_evening_min_time") or "").strip():
        data["friday_evening_min_time"] = form["friday_evening_min_time"].strip()
    data["windows"] = [
        {"start": r["start"], "end": r["end"]} for r in _rows(form, "window", ("start", "end"))
    ]
    trackers = []
    for r in _rows(form, "tracker", ("dest", "min", "max", "priority", "price")):
        if not (r["dest"] or r["min"] or r["max"] or r["price"]):
            continue  # a blank row that only carries the default priority
        t = {"destination": r["dest"], "min_stay": _int(r["min"]), "max_stay": _int(r["max"])}
        if r["priority"]:
            t["priority"] = _int(r["priority"])
        if r["price"]:
            t["max_price"] = r["price"]
        trackers.append(t)
    data["trackers"] = trackers
    return data


def profile_to_form(s: Session, user: User | None) -> dict[str, str]:
    """Current values as form fields (empty defaults for a new traveler)."""
    if user is None:
        form = {
            "weather_tolerance": "normal",
            "holiday_calendar": "US",
            "country": "US",
            "pto_committed": "0",
            "min_trip_days": "3",
            "max_stops_short": "1",
            "max_stops_long": "2",
            "friday_evening_min_time": "17:00",
            "ideal_trip_days": "",
        }
        windows, trackers = [], []
    else:
        form = {key: str(getattr(user, key)) for key in INT_FIELDS} | {
            "ideal_trip_days": str(user.ideal_trip_days) if user.ideal_trip_days is not None else "",
            "home_airport": user.home_airport,
            "country": user.country,
            "holiday_calendar": user.holiday_calendar,
            "weather_tolerance": user.weather_tolerance,
            "nearby_airports": ", ".join(user.nearby_airports or []),
            "ignored_holidays": ", ".join(user.ignored_holidays or []),
            "extra_days_off": ", ".join(d.isoformat() for d in user.extra_days_off or []),
            "friday_evening_min_time": user.friday_evening_min_time.strftime("%H:%M"),
        }
        for key in BOOL_FIELDS:
            if getattr(user, key):
                form[key] = "on"
        windows = list(
            s.scalars(
                select(TravelWindow).where(TravelWindow.user_id == user.id).order_by(TravelWindow.start_date)
            )
        )
        trackers = list(
            s.scalars(
                select(Tracker)
                .where(Tracker.user_id == user.id, Tracker.active.is_(True))
                .order_by(Tracker.id)
            )
        )
    for i, w in enumerate([*windows, *([None] * EXTRA_ROWS)]):
        form[f"window_start_{i}"] = w.start_date.isoformat() if w else ""
        form[f"window_end_{i}"] = w.end_date.isoformat() if w else ""
    for i, t in enumerate([*trackers, *([None] * EXTRA_ROWS)]):
        form[f"tracker_dest_{i}"] = t.destination_code if t else ""
        form[f"tracker_min_{i}"] = str(t.min_stay_days) if t else ""
        form[f"tracker_max_{i}"] = str(t.max_stay_days) if t else ""
        form[f"tracker_priority_{i}"] = str(t.priority) if t else "2"
        form[f"tracker_price_{i}"] = f"{t.max_price:.0f}" if t and t.max_price is not None else ""
    return form


def row_count(form: Mapping[str, str], prefix: str) -> int:
    """How many numbered rows the form has (so templates can render them, plus re-rendering after errors)."""
    i = 0
    while f"{prefix}_{'start' if prefix == 'window' else 'dest'}_{i}" in form:
        i += 1
    return i
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_ideal_trip_days.py`

Expected: PASS. Verified tail: `10 passed, 1 warning in 2.87s`

- [ ] **Step 9: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `355 passed, 1 deselected, 1 warning in 50.70s`; ruff reports nothing.

- [ ] **Step 10: Migrate Neon before pushing**

Render deploys on every push to `main`, and this commit adds `ideal_trip_days` to the `User` model. Apply migration 0005 to Neon first so the live app never selects a missing column. Load the direct URL from `.env.local` without printing it:

```powershell
$line = Select-String -Path .env.local -Pattern '^DATABASE_URL_UNPOOLED=' | Select-Object -First 1
$env:DATABASE_URL = $line.Line.Split('=', 2)[1].Trim('"')
if (-not $env:DATABASE_URL) { throw "DATABASE_URL_UNPOOLED not found in .env.local" }
.venv/Scripts/alembic upgrade head
Remove-Item Env:DATABASE_URL
```

Expected: alembic logs `Running upgrade 0004 -> 0005, preferred trip length`. The column is nullable, so the currently deployed V1 code keeps working against the migrated database.

- [ ] **Step 11: Commit and push**

```bash
git add -A
git commit -m "feat(profile): optional ideal trip length (migration 0005)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 3: Length fit in selection and the go-now score

Near-ideal trips rank higher both when choosing which trips to price and in the go-now score. With no preference, selection is exactly V1's.

**Files:**
- Modify: `ptopilot/config.py`
- Modify: `ptopilot/core/scoring.py`
- Modify: `ptopilot/core/selection.py`
- Create: `tests/core/test_length_preference.py`
- Modify: `tests/core/test_scoring.py`

**Interfaces:**
- Consumes: `TripShape.efficiency`, `TripShape.days_away` (existing).
- Produces: `ptopilot.core.scoring.length_fit(days_away: int, ideal: int | None) -> float`; `go_now(..., length_fit: float = 1.0)`; `select_top(..., ideal_days: int | None = None)`; config `LENGTH_FIT_SPAN = 4`, `LENGTH_SELECTION_BONUS = 0.25`, `GO_NOW_WEIGHTS["length"] = 0.1`.

> `tests/core/test_scoring.py` changes one existing test: the poor-trip score moves from 9 to 6 under the new weights, so it now passes `length_fit=0.0` explicitly.

- [ ] **Step 1: Write the failing test file `tests/core/test_length_preference.py`**

```python
"""Preferred trip length: how close a trip is to it, and how that steers selection and the go-now score."""

from datetime import date, timedelta

import pytest

from ptopilot import config
from ptopilot.core.scoring import go_now, length_fit
from ptopilot.core.selection import select_top
from ptopilot.core.shapes import TripShape


def shape(days_away, pto, start=date(2027, 3, 5)):
    return TripShape(start, start + timedelta(days=days_away - 1), pto, False)


@pytest.mark.parametrize(
    "days, expected", [(10, 1.0), (9, 0.75), (11, 0.75), (13, 0.25), (14, 0.0), (6, 0.0), (20, 0.0)]
)
def test_length_fit_fades_over_four_days(days, expected):
    assert length_fit(days, 10) == pytest.approx(expected)


def test_no_preference_fits_every_length():
    assert length_fit(3, None) == 1.0 and length_fit(16, None) == 1.0


def test_weights_still_sum_to_one():
    assert sum(config.GO_NOW_WEIGHTS.values()) == pytest.approx(1.0)


def test_length_fit_moves_the_go_now_score_by_its_weight():
    args = dict(z=-1.0, rating="good", efficiency=2.0, days_until_departure=60, international=True)
    gap = go_now(**args, length_fit=1.0) - go_now(**args, length_fit=0.0)
    assert abs(gap - 100 * config.GO_NOW_WEIGHTS["length"]) <= 1  # each score is rounded on its own


def test_go_now_defaults_to_a_full_length_fit():
    args = dict(z=-1.0, rating="good", efficiency=2.0, days_until_departure=60, international=True)
    assert go_now(**args) == go_now(**args, length_fit=1.0)


def test_near_ideal_trip_outranks_a_slightly_more_efficient_one():
    sixteen = shape(16, 8)  # efficiency 2.0, far from the ideal
    ten = shape(10, 6, start=date(2027, 3, 12))  # efficiency ~1.67 (2.08 with the bonus), the ideal
    assert select_top([sixteen, ten], n=1) == [sixteen]  # V1: efficiency alone
    assert select_top([sixteen, ten], n=1, ideal_days=10) == [ten]


def test_a_much_more_efficient_trip_still_wins():
    holiday_bridge = shape(9, 3)  # efficiency 3.0
    ideal = shape(10, 6, start=date(2027, 3, 12))  # efficiency ~1.67
    assert select_top([holiday_bridge, ideal], n=1, ideal_days=10) == [holiday_bridge]


def test_per_length_cap_still_applies_with_an_ideal():
    tens = [shape(10, 5, start=date(2027, 3, 1) + timedelta(days=7 * i)) for i in range(4)]
    seven = shape(7, 5, start=date(2027, 3, 3))
    picked = select_top([*tens, seven], n=4, max_per_length=2, ideal_days=10)
    assert sum(1 for s in picked if s.days_away == 10) == 2 and seven in picked
```

- [ ] **Step 2: Update the test file `tests/core/test_scoring.py` (full new contents)**

```python
import pytest

from ptopilot.core.scoring import deal_component, efficiency_component, go_now, timing_component


def test_perfect_trip_scores_100():
    assert go_now(z=-2.5, rating="good", efficiency=3.0, days_until_departure=60, international=True) == 100


def test_poor_trip_scores_low():
    # 0.5*0 + 0.2*0.2 + 0.15*0 + 0.1*0 + 0.05*0.5 = 0.065
    poor = go_now(
        z=0.0, rating="avoid", efficiency=1.0, days_until_departure=10, international=True, length_fit=0.0
    )
    assert poor == 6


def test_missing_z_contributes_nothing():
    assert deal_component(None) == 0.0


@pytest.mark.parametrize("z, expected", [(0.5, 0.0), (0.0, 0.0), (-1.25, 0.5), (-2.5, 1.0), (-4.0, 1.0)])
def test_deal_component(z, expected):
    assert deal_component(z) == pytest.approx(expected)


@pytest.mark.parametrize("eff, expected", [(0.8, 0.0), (1.0, 0.0), (2.0, 0.5), (3.0, 1.0), (8.0, 1.0)])
def test_efficiency_component(eff, expected):
    assert efficiency_component(eff) == pytest.approx(expected)


@pytest.mark.parametrize(
    "days, international, expected",
    [
        (29, True, 0.5),
        (30, True, 1.0),
        (120, True, 1.0),
        (121, True, 0.5),
        (20, False, 0.5),
        (21, False, 1.0),
        (90, False, 1.0),
        (91, False, 0.5),
    ],
)
def test_timing_sweet_spot(days, international, expected):
    assert timing_component(days, international) == expected
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/core/test_length_preference.py tests/core/test_scoring.py`

Expected: FAIL. Verified tail: `1 error in 0.66s`

- [ ] **Step 4: Write `ptopilot/config.py` (full new contents)**

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
GO_NOW_WEIGHTS = {"deal": 0.5, "weather": 0.2, "efficiency": 0.15, "length": 0.1, "timing": 0.05}
DEAL_Z_FOR_FULL_SCORE = 2.5
WEATHER_SCORES = {"good": 1.0, "shoulder": 0.6, "avoid": 0.2}
SWEET_SPOT_DAYS = {"international": (30, 120), "domestic": (21, 90)}
OFF_SWEET_SPOT_TIMING = 0.5
# Preferred trip length (V2): fit fades from 1 at the ideal to 0 this many days away from it.
LENGTH_FIT_SPAN = 4
LENGTH_SELECTION_BONUS = 0.25  # selection ranks by efficiency x (1 + bonus x fit)

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

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
```

- [ ] **Step 5: Write `ptopilot/core/scoring.py` (full new contents)**

```python
"""The 0-100 "go now" score combining deal strength, weather, PTO efficiency, trip length, and timing."""

from __future__ import annotations

from ptopilot import config
from ptopilot.core.seasons import Rating


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def deal_component(z: float | None) -> float:
    if z is None:
        return 0.0
    return _clamp(-z / config.DEAL_Z_FOR_FULL_SCORE)


def efficiency_component(efficiency: float) -> float:
    return _clamp((efficiency - 1) / 2)


def length_fit(days_away: int, ideal: int | None) -> float:
    """1.0 at the preferred length, fading to 0 at LENGTH_FIT_SPAN days off it. No preference fits all."""
    if ideal is None:
        return 1.0
    return max(0.0, 1 - abs(days_away - ideal) / config.LENGTH_FIT_SPAN)


def timing_component(days_until_departure: int, international: bool) -> float:
    lo, hi = config.SWEET_SPOT_DAYS["international" if international else "domestic"]
    return 1.0 if lo <= days_until_departure <= hi else config.OFF_SWEET_SPOT_TIMING


def go_now(
    z: float | None,
    rating: Rating,
    efficiency: float,
    days_until_departure: int,
    international: bool,
    length_fit: float = 1.0,
) -> int:
    w = config.GO_NOW_WEIGHTS
    total = (
        w["deal"] * deal_component(z)
        + w["weather"] * config.WEATHER_SCORES[rating]
        + w["efficiency"] * efficiency_component(efficiency)
        + w["length"] * _clamp(length_fit)
        + w["timing"] * timing_component(days_until_departure, international)
    )
    return round(100 * total)
```

- [ ] **Step 6: Write `ptopilot/core/selection.py` (full new contents)**

```python
"""Filtering trip shapes against a traveler's limits, and picking the best few."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ptopilot import config
from ptopilot.core.scoring import length_fit
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
    shapes: Iterable[TripShape],
    n: int = 6,
    max_per_length: int = 2,
    max_per_week: int | None = None,
    ideal_days: int | None = None,
) -> list[TripShape]:
    """Best n shapes by PTO efficiency, boosted near the preferred length (ideal_days; None = no boost),
    with diversity limits: at most max_per_length per trip length,
    at most max_per_week per departure week (ISO week; None = unlimited), and at most one per
    (depart, return) pair so an evening variant never duplicates its regular twin.

    Ties: fewer PTO days, then earlier departure, then the non-evening variant. Without a weekly limit,
    windows with no holidays (where every week ties) would only ever get trips from their first weeks.
    """

    def rank(s: TripShape) -> float:
        return s.efficiency * (1 + config.LENGTH_SELECTION_BONUS * length_fit(s.days_away, ideal_days))

    ranked = sorted(shapes, key=lambda s: (-rank(s), s.pto_cost, s.depart_date, s.evening_departure))
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

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/core/test_length_preference.py tests/core/test_scoring.py`

Expected: PASS. Verified tail: `35 passed in 0.43s`

- [ ] **Step 8: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `369 passed, 1 deselected, 1 warning in 50.59s`; ruff reports nothing.

- [ ] **Step 9: Commit and push**

```bash
git add -A
git commit -m "feat(scoring): preferred trip length in selection and go-now

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 4: Wire the preference through planning and scoring

The daily scan uses each user's ideal length: `expand` builds the profile with it, the planner passes it to `select_top`, and `score` passes its length fit to `go_now`.

**Files:**
- Modify: `ptopilot/core/planner.py`
- Modify: `ptopilot/pipeline/expand.py`
- Modify: `ptopilot/pipeline/score.py`
- Create: `tests/pipeline/test_length_preference.py`

**Interfaces:**
- Consumes: Task 2 `User.ideal_trip_days`; Task 3 `length_fit`, `select_top(ideal_days=)`, `go_now(length_fit=)`.
- Produces: `TravelerProfile.ideal_trip_days: int | None = None`.

- [ ] **Step 1: Write the failing test file `tests/pipeline/test_length_preference.py`**

```python
"""The preferred trip length flows from the user into planning (which trips get priced) and scoring."""

from datetime import date

from sqlalchemy import select

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.planner import TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.db.models import Candidate, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, score
from ptopilot.pipeline.expand import profile_for
from tests.pipeline.conftest import GEO, RUN, SEASONS, add_observation, add_tracker, add_user

JUNE = [Window(date(2027, 6, 1), date(2027, 6, 30))]
TRIP = (date(2027, 6, 12), date(2027, 6, 20))  # 9 days away


def profile(ideal=None) -> TravelerProfile:
    calendar = WorkCalendar.from_code("US", [], [])
    return TravelerProfile(("JFK",), calendar, 15, 7, 16, ideal_trip_days=ideal)


def lengths(ideal) -> list[int]:
    picked = plan_itineraries(profile(ideal), TrackerSpec("AZORES", 5, 14), JUNE, GEO, SEASONS, top_n=4)
    return sorted(it.shape.days_away for it in picked)


def test_profile_carries_the_users_ideal_length():
    user = User(
        home_airport="JFK",
        nearby_airports=[],
        holiday_calendar="US",
        extra_days_off=[],
        ignored_holidays=[],
        pto_days_total=15,
        pto_committed=0,
        min_trip_days=7,
        max_trip_days=16,
        ideal_trip_days=12,
        weather_tolerance="normal",
        friday_evening_departure=False,
    )
    assert profile_for(user).ideal_trip_days == 12


def test_no_preference_plans_exactly_as_before():
    assert lengths(None) == [9, 10, 10, 11]  # by PTO efficiency alone (Juneteenth makes 9 days cost 4)


def test_planner_prices_a_trip_near_the_ideal_ahead_of_a_slightly_more_efficient_one():
    # June offers 9-, 10-, 11- and 16-day weekend-to-weekend trips. With a 14-day ideal the 16-day trip
    # (fit 0.5) takes the 11-day trip's slot; the far more efficient Juneteenth trips keep theirs.
    assert lengths(14) == [9, 10, 10, 16]


def test_go_now_rewards_the_trip_matching_the_ideal(make_ctx):
    ctx = make_ctx()
    match = add_tracker(ctx.engine, add_user(ctx.engine, "a@example.com", ideal_trip_days=9))
    far = add_tracker(ctx.engine, add_user(ctx.engine, "b@example.com", ideal_trip_days=15))
    expand.run(ctx)
    add_observation(ctx.engine, *TRIP, 820, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    with session_scope(ctx.engine) as s:
        rows = s.scalars(select(Candidate).where(Candidate.evening_departure.is_(False)))
        go = {c.tracker_id: c.go_now for c in rows}
    assert go[match] - go[far] in (9, 10, 11)  # the length weight (0.1), up to rounding
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_length_preference.py`

Expected: FAIL. Verified tail: `4 failed in 2.41s`

- [ ] **Step 3: Write `ptopilot/core/planner.py` (full new contents)**

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
                ideal_days=profile.ideal_trip_days,
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

- [ ] **Step 4: Write `ptopilot/pipeline/expand.py` (full new contents)**

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
        ideal_trip_days=user.ideal_trip_days,
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

- [ ] **Step 5: Write `ptopilot/pipeline/score.py` (full new contents)**

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
from ptopilot.core.scoring import go_now, length_fit
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
                        length_fit=length_fit(link.days_away, user.ideal_trip_days),
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

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_length_preference.py`

Expected: PASS. Verified tail: `4 passed in 2.06s`

- [ ] **Step 7: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `373 passed, 1 deselected, 1 warning in 51.99s`; ruff reports nothing.

- [ ] **Step 8: Commit and push**

```bash
git add -A
git commit -m "feat(pipeline): plan and score with the preferred trip length

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 5: Price bar geometry and trend chart

Pure drawing helpers: the bar's dot and typical band as 0–100 percentages, and a small inline SVG of the cheapest price per scan day (gaps break the line).

**Files:**
- Modify: `ptopilot/config.py`
- Create: `ptopilot/web/viz.py`
- Create: `tests/web/test_viz.py`

**Interfaces:**
- Consumes: Task 1 `Palette`; `config.SIGMA_FLOOR_FRACTION` (existing).
- Produces: `ptopilot.web.viz`: `BarGeometry(dot, band_start, band_end)`, `TrendPoint(run_date, price)`, `TrendChart(svg, low, high, first, last)`, `bar_geometry(price, median, sigma) -> BarGeometry | None`, `trend_chart(points, band, palette) -> TrendChart | None`; config `MIN_TREND_POINTS = 3`.

- [ ] **Step 1: Write the failing test file `tests/web/test_viz.py`**

```python
from datetime import date, timedelta
from decimal import Decimal

from ptopilot.core.geo import Palette
from ptopilot.web.viz import BarGeometry, TrendPoint, bar_geometry, trend_chart

TEAL = Palette("#0e7490", "#c3dde3")
D0 = date(2027, 3, 1)


def points(*prices, gaps=()):
    """One point per day from D0, skipping the day offsets in `gaps`."""
    out, day = [], D0
    for price in prices:
        while (day - D0).days in gaps:
            day += timedelta(days=1)
        out.append(TrendPoint(day, Decimal(price)))
        day += timedelta(days=1)
    return out


def test_bar_puts_the_typical_band_around_the_median():
    g = bar_geometry(Decimal(700), median=700, sigma=50)
    assert g == BarGeometry(dot=50.0, band_start=33.3, band_end=66.7)


def test_cheaper_price_sits_left_of_the_band():
    g = bar_geometry(Decimal(600), median=700, sigma=50)
    assert g.dot < g.band_start


def test_dot_never_leaves_the_track():
    assert bar_geometry(Decimal(1), median=700, sigma=50).dot == 2.0
    assert bar_geometry(Decimal(99999), median=700, sigma=50).dot == 98.0


def test_no_baseline_means_no_bar():
    assert bar_geometry(Decimal(700), median=None, sigma=None) is None


def test_zero_sigma_uses_the_floor_instead_of_dividing_by_zero():
    g = bar_geometry(Decimal(700), median=700, sigma=0)
    assert g.band_start < g.dot < g.band_end


def test_fewer_than_three_points_has_no_chart():
    assert trend_chart(points(700, 690), None, TEAL) is None


def test_chart_reports_its_range_and_dates():
    chart = trend_chart(points(700, 650, 680), None, TEAL)
    assert (chart.low, chart.high) == (Decimal(650), Decimal(700))
    assert (chart.first, chart.last) == (D0, D0 + timedelta(days=2))
    assert chart.svg.count("<polyline") == 1 and "#0e7490" in chart.svg


def test_missing_days_break_the_line_into_segments():
    chart = trend_chart(points(700, 690, 680, 670, gaps=(2,)), None, TEAL)
    assert chart.svg.count("<polyline") == 2


def test_band_is_drawn_when_known_and_widens_the_range():
    chart = trend_chart(points(700, 690, 680), (Decimal(600), Decimal(760)), TEAL)
    assert "<rect" in chart.svg and "#c3dde3" in chart.svg
    assert (chart.low, chart.high) == (Decimal(600), Decimal(760))
    assert "<rect" not in trend_chart(points(700, 690, 680), None, TEAL).svg


def test_latest_price_is_marked():
    assert trend_chart(points(700, 690, 680), None, TEAL).svg.count("<circle") == 1


def test_flat_prices_still_draw():
    chart = trend_chart(points(700, 700, 700), None, TEAL)
    assert "nan" not in chart.svg.lower() and chart.svg.count("<polyline") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_viz.py`

Expected: FAIL. Verified tail: `1 warning, 1 error in 0.60s`

- [ ] **Step 3: Write `ptopilot/config.py` (full new contents)**

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
GO_NOW_WEIGHTS = {"deal": 0.5, "weather": 0.2, "efficiency": 0.15, "length": 0.1, "timing": 0.05}
DEAL_Z_FOR_FULL_SCORE = 2.5
WEATHER_SCORES = {"good": 1.0, "shoulder": 0.6, "avoid": 0.2}
SWEET_SPOT_DAYS = {"international": (30, 120), "domestic": (21, 90)}
OFF_SWEET_SPOT_TIMING = 0.5
# Preferred trip length (V2): fit fades from 1 at the ideal to 0 this many days away from it.
LENGTH_FIT_SPAN = 4
LENGTH_SELECTION_BONUS = 0.25  # selection ranks by efficiency x (1 + bonus x fit)

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

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
MIN_TREND_POINTS = 3  # the destination page draws a price trend from this many scan days
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
```

- [ ] **Step 4: Write `ptopilot/web/viz.py`**

```python
"""Server-side drawing for the web app and digest: the "where this price sits" bar and the price trend.

No JavaScript: the bar is a set of percentages for CSS (or email table cells), and the trend is a small
inline SVG.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from markupsafe import Markup

from ptopilot import config
from ptopilot.core.geo import Palette

BAR_SIGMAS = 3  # the bar spans median +/- 3 sigma; the typical band is median +/- 1 sigma
BAR_MIN, BAR_MAX = 2.0, 98.0  # keep the dot on the track
CHART_W, CHART_H, CHART_PAD = 300, 80, 6


@dataclass(frozen=True)
class BarGeometry:
    dot: float  # 0-100, left to right
    band_start: float
    band_end: float


@dataclass(frozen=True)
class TrendPoint:
    run_date: date
    price: Decimal


@dataclass(frozen=True)
class TrendChart:
    svg: Markup
    low: Decimal
    high: Decimal
    first: date
    last: date


def bar_geometry(price: Decimal, median: float | None, sigma: float | None) -> BarGeometry | None:
    if median is None:
        return None
    median = float(median)
    sigma = max(float(sigma or 0), config.SIGMA_FLOOR_FRACTION * median, 1.0)
    lo, span = median - BAR_SIGMAS * sigma, 2 * BAR_SIGMAS * sigma

    def pos(x: float) -> float:
        return round(min(max((x - lo) / span * 100, BAR_MIN), BAR_MAX), 1)

    return BarGeometry(pos(float(price)), pos(median - sigma), pos(median + sigma))


def trend_chart(
    points: list[TrendPoint], band: tuple[Decimal, Decimal] | None, palette: Palette
) -> TrendChart | None:
    """A line of the cheapest price per scan day; missing days break the line. None below MIN_TREND_POINTS."""
    if len(points) < config.MIN_TREND_POINTS:
        return None
    points = sorted(points, key=lambda p: p.run_date)
    prices = [p.price for p in points] + (list(band) if band else [])
    low, high = min(prices), max(prices)
    first, last = points[0].run_date, points[-1].run_date
    days = max((last - first).days, 1)
    spread = float(high - low) or 1.0

    def xy(p: TrendPoint) -> tuple[float, float]:
        x = CHART_PAD + (p.run_date - first).days / days * (CHART_W - 2 * CHART_PAD)
        y = CHART_H - CHART_PAD - float(p.price - low) / spread * (CHART_H - 2 * CHART_PAD)
        if high == low:
            y = CHART_H / 2
        return round(x, 1), round(y, 1)

    segments: list[list[TrendPoint]] = [[points[0]]]
    for prev, cur in zip(points, points[1:], strict=False):
        if (cur.run_date - prev.run_date).days > 1:
            segments.append([])
        segments[-1].append(cur)

    parts = [
        f'<svg class="trend" viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
        f'aria-label="Cheapest fare from {first:%b %d} to {last:%b %d}">'
    ]
    if band:
        top = xy(TrendPoint(first, band[1]))[1]
        bottom = xy(TrendPoint(first, band[0]))[1]
        height = round(bottom - top, 1)
        parts.append(f'<rect x="0" y="{top}" width="{CHART_W}" height="{height}" fill="{palette.tint}"/>')
    for seg in segments:
        coords = " ".join(f"{x},{y}" for x, y in map(xy, seg))
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{palette.color}" stroke-width="2.5" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    cx, cy = xy(points[-1])
    parts.append(
        f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{palette.color}" stroke="#fff" stroke-width="2"/>'
    )
    parts.append("</svg>")
    return TrendChart(Markup("".join(parts)), low, high, first, last)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_viz.py`

Expected: PASS. Verified tail: `11 passed, 1 warning in 0.12s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `384 passed, 1 deselected, 1 warning in 52.72s`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(web): price bar geometry and trend chart

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 6: Trip options, trend and destination summaries

Read-only queries over `candidates` for the dashboard cards and destination page. No new tables.

**Files:**
- Create: `ptopilot/web/history.py`
- Create: `tests/web/test_history.py`

**Interfaces:**
- Consumes: Task 1 `palette`; Task 5 `bar_geometry`, `TrendPoint`; `digest.select.latest_run_date`, `_next_good_month`; `pipeline.queries.load_baselines`, `rq_baseline_key` (existing).
- Produces: `ptopilot.web.history`: `TripOption` (with `.open_jaw`, `.dimmed`, `.pct_below`, `.bar`), `DestinationSummary(tracker_id, code, name, palette, stay, best, snoozed_until, next_good_month)`, `trip_options(engine, geo, seasons, tracker_id, today)`, `trend(engine, tracker_id, today)`, `typical_band(options)`, `destination_summaries(engine, geo, seasons, user_id, today)`.

- [ ] **Step 1: Write the failing test file `tests/web/test_history.py`**

```python
"""Queries behind the dashboard cards and the destination page."""

from datetime import date, timedelta
from decimal import Decimal

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from ptopilot.web.history import destination_summaries, trend, trip_options, typical_band
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user

GEO, SEASONS = load_geo(), load_seasons()


def options(engine, tracker_id, today=RUN):
    return trip_options(engine, GEO, SEASONS, tracker_id, today)


def test_trip_options_are_the_latest_scan_cheapest_first(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 700, depart=date(2027, 3, 12), ret=date(2027, 3, 21))
    add_candidate(clean_engine, t, 603)
    add_candidate(clean_engine, t, 999, run_date=RUN - timedelta(days=1), depart=date(2027, 3, 19))
    got = options(clean_engine, t)
    assert [o.price for o in got] == [603, 700]
    first = got[0]
    assert (first.depart_date, first.return_date, first.pto_cost, first.days_away) == (
        date(2027, 3, 5), date(2027, 3, 14), 5, 10,
    )  # fmt: skip
    assert (first.carrier, first.stops) == ("Tap Air Portugal", 1)
    assert first.deep_link.startswith("https://www.google.com/travel/flights")


def test_trip_options_ignore_scans_after_today(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 650)
    add_candidate(clean_engine, t, 500, run_date=RUN + timedelta(days=1))
    assert [o.price for o in options(clean_engine, t)] == [650]


def test_trip_options_carry_bar_geometry_when_a_baseline_exists(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_candidate(clean_engine, t, 700, dest="FNC")
    add_baseline(clean_engine, 700)  # JFK-PDL only, sigma 50
    by_dest = {o.dest_airport: o for o in options(clean_engine, t)}
    assert by_dest["PDL"].bar is not None and by_dest["PDL"].bar.dot < by_dest["PDL"].bar.band_start
    assert by_dest["PDL"].pct_below == 14
    assert by_dest["FNC"].bar is None and by_dest["FNC"].pct_below is None


def test_snoozed_and_excluded_trips_are_kept_but_dimmed(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    keep = add_candidate(clean_engine, t, 603)
    hidden = add_candidate(clean_engine, t, 650, depart=date(2027, 3, 12), ret=date(2027, 3, 21))
    with session_scope(clean_engine) as s:
        s.get(Candidate, hidden).state = "excluded"
    dimmed = {o.candidate_id: o.dimmed for o in options(clean_engine, t)}
    assert dimmed == {keep: False, hidden: True}


def test_open_jaw_options_know_where_they_fly_home_from(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine), code="CAMINO_PORTUGUES")
    add_candidate(clean_engine, t, 852, dest="OPO", return_airport="SCQ")
    (o,) = options(clean_engine, t)
    assert o.open_jaw and (o.dest_airport, o.return_airport) == ("OPO", "SCQ")


def test_trend_is_the_cheapest_price_per_scan_day(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    for days_ago, prices in [(2, (720, 700)), (1, (690,)), (0, (650, 680))]:
        for i, price in enumerate(prices):
            add_candidate(
                clean_engine, t, price, run_date=RUN - timedelta(days=days_ago), depart=date(2027, 3, 5 + i)
            )
    assert [(p.run_date, p.price) for p in trend(clean_engine, t, RUN)] == [
        (RUN - timedelta(days=2), Decimal(700)),
        (RUN - timedelta(days=1), Decimal(690)),
        (RUN, Decimal(650)),
    ]


def test_trend_covers_only_the_last_30_days_and_this_tracker(clean_engine):
    user = add_user(clean_engine)
    t, other = add_tracker(clean_engine, user), add_tracker(clean_engine, user, code="MADEIRA")
    add_candidate(clean_engine, t, 650)
    add_candidate(clean_engine, t, 600, run_date=RUN - timedelta(days=30))  # just outside the window
    add_candidate(clean_engine, other, 500, dest="FNC")
    assert [p.price for p in trend(clean_engine, t, RUN)] == [Decimal(650)]
    assert trend(clean_engine, t, RUN - timedelta(days=60)) == []


def test_typical_band_comes_from_the_cheapest_trips_baseline(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_baseline(clean_engine, 700)
    assert typical_band(options(clean_engine, t)) == (Decimal(650), Decimal(750))
    assert typical_band([]) is None


def test_summaries_list_priced_destinations_cheapest_first_then_the_rest(clean_engine):
    user = add_user(clean_engine)
    azores = add_tracker(clean_engine, user)
    madeira = add_tracker(clean_engine, user, code="MADEIRA")
    patagonia = add_tracker(clean_engine, user, code="PATAGONIA")
    add_candidate(clean_engine, azores, 700)
    add_candidate(clean_engine, madeira, 603, dest="FNC")
    got = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert [(s.tracker_id, s.best.price if s.best else None) for s in got] == [
        (madeira, 603), (azores, 700), (patagonia, None),
    ]  # fmt: skip
    assert got[0].name == "Madeira" and got[0].palette.color == "#15803d"
    assert got[0].stay == (7, 10)


def test_summaries_show_snoozes_and_skip_inactive_trackers(clean_engine):
    user = add_user(clean_engine)
    snoozed = add_tracker(clean_engine, user, snoozed_until=RUN + timedelta(days=10))
    gone = add_tracker(clean_engine, user, code="MADEIRA")
    with session_scope(clean_engine) as s:
        s.get(Tracker, gone).active = False
    (only,) = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert only.tracker_id == snoozed and only.snoozed_until == RUN + timedelta(days=10)


def test_summaries_ignore_other_users(clean_engine):
    mine = add_user(clean_engine)
    add_tracker(clean_engine, add_user(clean_engine, "other@example.com"))
    assert destination_summaries(clean_engine, GEO, SEASONS, mine, RUN) == []


def test_a_summarys_best_trip_skips_excluded_ones(clean_engine):
    user = add_user(clean_engine)
    t = add_tracker(clean_engine, user)
    excluded = add_candidate(clean_engine, t, 500)
    add_candidate(clean_engine, t, 650, depart=date(2027, 3, 12), ret=date(2027, 3, 21))
    with session_scope(clean_engine) as s:
        s.get(Candidate, excluded).state = "excluded"
    (summary,) = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert summary.best.price == 650
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_history.py`

Expected: FAIL. Verified tail: `1 warning, 1 error in 0.57s`

- [ ] **Step 3: Write `ptopilot/web/history.py`**

```python
"""What the dashboard and destination pages show: each tracker's trips from the latest scan, and its trend.

Read-only. Prices come from `candidates` (one row per trip per scan day), so no extra history table is needed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ptopilot.core.geo import Geo, Palette, palette
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.db.models import Candidate, PriceObservation, RouteQuery, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.digest.select import _next_good_month as next_good_month
from ptopilot.digest.select import latest_run_date
from ptopilot.pipeline.queries import load_baselines, rq_baseline_key
from ptopilot.web.viz import BarGeometry, TrendPoint, bar_geometry

TREND_DAYS = 30
DIMMED_STATES = frozenset({"snoozed", "excluded"})


@dataclass(frozen=True)
class TripOption:
    candidate_id: int
    tracker_id: int
    origin: str
    dest_airport: str
    return_airport: str
    depart_date: date
    return_date: date
    evening_departure: bool
    price: Decimal
    currency: str
    pto_cost: int
    days_away: int
    season_rating: str
    weather_note: str | None
    carrier: str | None
    stops: int | None
    overnight: bool | None
    deep_link: str | None
    deal_level: str
    go_now: int
    state: str
    median: float | None
    sigma: float | None
    bar: BarGeometry | None

    @property
    def open_jaw(self) -> bool:
        return self.return_airport != self.dest_airport

    @property
    def dimmed(self) -> bool:
        return self.state in DIMMED_STATES

    @property
    def pct_below(self) -> int | None:
        if not self.median:
            return None
        return round(100 * (1 - float(self.price) / self.median))


@dataclass(frozen=True)
class DestinationSummary:
    tracker_id: int
    code: str
    name: str
    palette: Palette
    stay: tuple[int, int]  # days on the ground, min..max
    best: TripOption | None
    snoozed_until: date | None
    next_good_month: str | None


def _options(
    s: Session, geo: Geo, seasons: SeasonTable, trackers: list[Tracker], run_date: date
) -> dict[int, list[TripOption]]:
    """Every candidate on run_date for these trackers, cheapest first."""
    by_id = {t.id: t for t in trackers}
    if not by_id:
        return {}
    baselines = load_baselines(s)
    rows = s.execute(
        select(Candidate, RouteQuery, TrackerRouteLink, PriceObservation)
        .join(RouteQuery, RouteQuery.id == Candidate.route_query_id)
        .join(
            TrackerRouteLink,
            (TrackerRouteLink.tracker_id == Candidate.tracker_id)
            & (TrackerRouteLink.route_query_id == Candidate.route_query_id)
            & (TrackerRouteLink.run_date == Candidate.run_date)
            & (TrackerRouteLink.evening_departure == Candidate.evening_departure),
        )
        .outerjoin(PriceObservation, PriceObservation.id == Candidate.price_observation_id)
        .where(Candidate.run_date == run_date, Candidate.tracker_id.in_(by_id))
        .order_by(Candidate.price, RouteQuery.depart_date, Candidate.id)
    ).all()
    out: defaultdict[int, list[TripOption]] = defaultdict(list)
    for c, rq, link, obs in rows:
        dest = geo.destination(by_id[c.tracker_id].destination_code)
        b = baselines.get(rq_baseline_key(rq))
        out[c.tracker_id].append(
            TripOption(
                candidate_id=c.id,
                tracker_id=c.tracker_id,
                origin=rq.origin,
                dest_airport=rq.dest_airport,
                return_airport=rq.return_airport,
                depart_date=rq.depart_date,
                return_date=rq.return_date,
                evening_departure=c.evening_departure,
                price=c.price,
                currency=c.currency,
                pto_cost=link.pto_cost,
                days_away=link.days_away,
                season_rating=link.season_rating,
                weather_note=seasons.note(
                    (dest.code, dest.country), trip_month(rq.depart_date, rq.return_date)
                ),
                carrier=obs.carrier if obs else None,
                stops=obs.stops if obs else None,
                overnight=obs.overnight_layover if obs else None,
                deep_link=obs.deep_link if obs else None,
                deal_level=c.deal_level,
                go_now=c.go_now,
                state=c.state,
                median=b.median if b else None,
                sigma=b.sigma if b else None,
                bar=bar_geometry(c.price, b.median, b.sigma) if b else None,
            )
        )
    return out


def trip_options(
    engine: Engine, geo: Geo, seasons: SeasonTable, tracker_id: int, today: date
) -> list[TripOption]:
    """The tracker's trips from the latest scan on or before today, cheapest first."""
    run_date = latest_run_date(engine, today)
    if run_date is None:
        return []
    with session_scope(engine) as s:
        tracker = s.get(Tracker, tracker_id)
        return _options(s, geo, seasons, [tracker], run_date).get(tracker_id, []) if tracker else []


def trend(engine: Engine, tracker_id: int, today: date) -> list[TrendPoint]:
    """The cheapest price per scan day over the last TREND_DAYS days, oldest first."""
    with session_scope(engine) as s:
        rows = s.execute(
            select(Candidate.run_date, func.min(Candidate.price))
            .where(
                Candidate.tracker_id == tracker_id,
                Candidate.run_date > today - timedelta(days=TREND_DAYS),
                Candidate.run_date <= today,
            )
            .group_by(Candidate.run_date)
            .order_by(Candidate.run_date)
        ).all()
    return [TrendPoint(run_date, price) for run_date, price in rows]


def typical_band(options: list[TripOption]) -> tuple[Decimal, Decimal] | None:
    """Median +/- sigma for the cheapest trip's route, the band drawn behind the trend line."""
    best = options[0] if options else None
    if best is None or best.median is None:
        return None
    median, sigma = Decimal(str(round(best.median))), Decimal(str(round(best.sigma or 0)))
    return median - sigma, median + sigma


def destination_summaries(
    engine: Engine, geo: Geo, seasons: SeasonTable, user_id: int, today: date
) -> list[DestinationSummary]:
    """One card per active tracker: priced ones cheapest first, then the rest in the order they were added."""
    run_date = latest_run_date(engine, today)
    with session_scope(engine) as s:
        trackers = list(
            s.scalars(
                select(Tracker)
                .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                .order_by(Tracker.id)
            )
        )
        options = _options(s, geo, seasons, trackers, run_date) if run_date else {}
        summaries = []
        for t in trackers:
            dest = geo.destination(t.destination_code)
            mine = options.get(t.id, [])
            summaries.append(
                DestinationSummary(
                    tracker_id=t.id,
                    code=dest.code,
                    name=dest.name,
                    palette=palette(dest),
                    stay=(t.min_stay_days, t.max_stay_days),
                    best=next((o for o in mine if not o.dimmed), mine[0] if mine else None),
                    snoozed_until=t.snoozed_until if t.snoozed_until and t.snoozed_until >= today else None,
                    next_good_month=next_good_month(seasons, (dest.code, dest.country), today),
                )
            )
    priced = sorted((x for x in summaries if x.best), key=lambda x: (x.best.price, x.tracker_id))
    return priced + [x for x in summaries if not x.best]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_history.py`

Expected: PASS. Verified tail: `12 passed, 1 warning in 5.80s`

- [ ] **Step 5: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `396 passed, 1 deselected, 1 warning in 57.11s`; ruff reports nothing.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "feat(web): trip options, price trend and destination summaries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 7: Design system: stylesheet, base layout, components

One stylesheet of tokens and classes, Fraunces + Inter, the base layout, the component macros, restyled message/confirm pages, and a styled 400 page for malformed requests instead of FastAPI's 422 JSON.

**Files:**
- Modify: `ptopilot/digest/render.py`
- Modify: `ptopilot/web/app.py`
- Create: `ptopilot/web/static/app.css`
- Create: `ptopilot/web/templates/_components.html`
- Modify: `ptopilot/web/templates/action_confirm.html`
- Modify: `ptopilot/web/templates/base.html`
- Modify: `ptopilot/web/templates/login_sent.html`
- Modify: `ptopilot/web/templates/message.html`
- Modify: `pyproject.toml`
- Create: `tests/web/test_design_system.py`

**Interfaces:**
- Consumes: Task 5 `BarGeometry` (via templates); `digest.render.money`, `day` (existing).
- Produces: `/static/app.css`; `templates/_components.html` macros `dest_style`, `price_bar`, `vs_typical`, `season`, `pto_bar`, `dest_card`, `field`; Jinja filter `dates` (`digest.render.date_range`); base template variable `active`.

- [ ] **Step 1: Write the failing test file `tests/web/test_design_system.py`**

```python
"""The shared look: one stylesheet, the base layout, and friendly pages for malformed requests."""

import tomllib
from datetime import date
from pathlib import Path

from ptopilot.digest.render import date_range
from tests.web.conftest import sign_in

ROOT = Path(__file__).resolve().parents[2]


def test_stylesheet_is_served(client):
    response = client.get("/static/app.css")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
    assert "--bg: #fbf7f0" in response.text


def test_pages_use_the_stylesheet_and_fonts(client):
    page = client.get("/s/not-a-token").text
    assert '<link rel="stylesheet" href="/static/app.css">' in page
    assert "family=Fraunces" in page and "family=Inter" in page


def test_stylesheet_ships_with_the_package():
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]
    assert "static/*.css" in package_data["ptopilot.web"]


def test_malformed_form_input_gets_a_page_not_json(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    response = client.post("/trackers/1/snooze", data={"days": "lots"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "didn&#39;t look right" in response.text and "/static/app.css" in response.text


def test_malformed_path_gets_a_page_not_json(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    response = client.post("/trackers/not-a-number/snooze")
    assert response.status_code == 400 and "didn&#39;t look right" in response.text


def test_date_range_is_compact():
    assert date_range(date(2027, 3, 5), date(2027, 3, 15)) == "Mar 5–15"
    assert date_range(date(2027, 2, 27), date(2027, 3, 14)) == "Feb 27–Mar 14"
    assert date_range(date(2027, 12, 28), date(2028, 1, 4)) == "Dec 28, 2027–Jan 4, 2028"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_design_system.py`

Expected: FAIL. Verified tail: `1 warning, 1 error in 0.56s`

- [ ] **Step 3: Write `ptopilot/digest/render.py` (full new contents)**

```python
"""Render a Digest as an email: subject, HTML (inline styles, table layout for mail clients), plain text."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ptopilot.digest.select import DealCard, Digest

LinkBuilder = Callable[[DealCard], list[tuple[str, str]]]

LEVEL_LABEL = {"great": "Great deal", "good": "Good deal", "none": "Tracking"}
TREND_ARROW = {"down": "↓", "up": "↑", "flat": "→", "new": "·"}


def money(value: Decimal | float | None, currency: str = "USD") -> str:
    if value is None:
        return "—"
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.0f}"


def day(d) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def date_range(start, end) -> str:
    """Mar 5–15, Feb 27–Mar 14, or Dec 28, 2027–Jan 4, 2028."""
    if start.year != end.year:
        return f"{start:%b} {start.day}, {start.year}–{end:%b} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start:%b} {start.day}–{end:%b} {end.day}"
    return f"{start:%b} {start.day}–{end.day}"


def duration(minutes: int | None) -> str:
    if not minutes:
        return ""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def clock(dt) -> str:
    if dt is None:
        return ""
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"


def checked_ago(observed: datetime | None, now: datetime) -> str:
    if observed is None:
        return ""
    hours = int((now - observed).total_seconds() // 3600)
    if hours < 1:
        return "checked under an hour ago"
    if hours < 48:
        return f"checked {hours} hour{'s' if hours != 1 else ''} ago"
    return f"checked {hours // 24} days ago"


def stops(n: int | None) -> str:
    if n is None:
        return ""
    return "nonstop" if n == 0 else f"{n} stop{'s' if n != 1 else ''}"


_env = Environment(
    loader=PackageLoader("ptopilot.digest", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False, default_for_string=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters.update(money=money, day=day, dates=date_range, duration=duration, clock=clock, stops=stops)


def subject(digest: Digest) -> str:
    if digest.quiet:
        return "ptopilot: a quiet week for your trips"
    top = digest.deals[0]
    count = len(digest.deals)
    lead = f"{top.destination} {money(top.price, top.currency)}"
    if top.pct_below and top.pct_below > 0:
        lead += f" ({top.pct_below}% below typical)"
    more = f" + {count - 1} more" if count > 1 else ""
    return f"ptopilot: {lead}{more}"


def render(
    digest: Digest, now: datetime | None = None, links: LinkBuilder | None = None
) -> tuple[str, str, str]:
    """(subject, html, text). `links` adds snooze buttons (label, url) under each deal card."""
    now = now or datetime.now(UTC)
    context = {
        "actions": {d.candidate_id: links(d) if links else [] for d in digest.deals},
        "digest": digest,
        "levels": LEVEL_LABEL,
        "arrows": TREND_ARROW,
        "checked": {d.candidate_id: checked_ago(d.observed_at, now) for d in digest.deals},
    }
    html = _env.get_template("digest.html.j2").render(**context)
    text = _env.get_template("digest.txt.j2").render(**context)
    return subject(digest), html, text
```

- [ ] **Step 4: Write `ptopilot/web/app.py` (full new contents)**

```python
"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import date_range, day, money
from ptopilot.digest.select import TrackerRow, build_digests
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
TEMPLATES.env.filters.update(money=money, day=day, dates=date_range)
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_COOLDOWN_S = 120  # at most one sign-in email per address per 2 minutes


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
    now: Callable[[], float] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    now = now or time.monotonic
    last_link_sent: dict[str, float] = {}  # per process; enough for one small instance
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def is_invited(email: str) -> bool:
        with session_scope(engine) as s:
            return s.scalar(select(Invite.email).where(Invite.email == email)) is not None

    def current_email(request: Request) -> str | None:
        """The signed-in email, as long as it is still invited; removing an invite ends the session."""
        email = request.session.get("email")
        if email and not is_invited(email):
            request.session.clear()
            return None
        return email

    def signed_in_user(s, request: Request) -> User | None:
        email = current_email(request)
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError):
        """Malformed form fields or URLs (e.g. a non-numeric id) get a page, not FastAPI's JSON."""
        message = "Something in that request didn't look right. Go back and try again."
        return page(request, "message.html", 400, title="That didn't work", message=message)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form(request: Request):
        return page(request, "login.html")

    def send_link(email: str, link: str) -> None:
        if emailer is None:
            log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            return
        try:
            emailer.send(
                email,
                "Your ptopilot sign-in link",
                f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                f"Sign in to ptopilot (link works for 15 minutes): {link}",
            )
        except EmailError as exc:
            log.error("sign-in email not sent: %s", exc)

    @app.post("/login")
    def login(request: Request, background: BackgroundTasks, email: str = Form("")):
        email = email.strip().lower()
        cooled_down = now() - last_link_sent.get(email, float("-inf")) >= LOGIN_COOLDOWN_S
        if email and cooled_down and is_invited(email):
            last_link_sent[email] = now()
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            # Sent after the response, so invited and uninvited addresses answer equally fast.
            background.add_task(send_link, email, link)
        # Same answer either way, so the form doesn't reveal who is invited.
        return page(request, "login_sent.html")

    @app.get("/auth")
    def auth(request: Request, token: str = ""):
        try:
            email = read_login_token(settings.secret_key, token)
        except TokenError as exc:
            return page(
                request, "message.html", 400, title="Sign-in link problem", message=f"{exc}.", login=True
            )
        if not is_invited(email):
            message = "this address is no longer invited."
            return page(request, "message.html", 400, title="Sign-in link problem", message=message)
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/login")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not current_email(request):
            return redirect("/login")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        # The dashboard shows everything current, including deals already emailed.
        digests = build_digests(engine, geo, seasons, today(), "none", user_id=user_id, skip_sent=False)
        digest = digests[0] if digests else None
        trackers = digest.trackers if digest else []
        if digest is None:  # no scan has priced anything yet: list the trackers without prices
            with session_scope(engine) as s:
                rows = s.scalars(
                    select(Tracker)
                    .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                    .order_by(Tracker.id)
                )
                trackers = [
                    TrackerRow(t.id, geo.destination(t.destination_code).name, None, None, "new", None,
                               t.snoozed_until if t.snoozed_until and t.snoozed_until >= today() else None)
                    for t in rows
                ]  # fmt: skip
        return page(
            request,
            "dashboard.html",
            digest=digest,
            deals=(sorted(digest.deals, key=lambda d: (d.price, -d.go_now))[:5] if digest else []),
            trackers=trackers,
            pto_total=pto_total,
            pto_committed=pto_committed,
            saved=bool(saved),
        )

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: int, days: int = Form(30)):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            snooze(tracker, date.fromordinal(today().toordinal() + max(days, 1)))
        return redirect("/")

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: int):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            unsnooze(tracker)
        return redirect("/")

    # --- profile / onboarding --------------------------------------------------------------------

    def profile_page(request: Request, form: dict, errors: list[str], status: int = 200):
        return page(
            request,
            "profile.html",
            status,
            form=form,
            errors=errors,
            destinations=geo.destinations(),
            windows=row_count(form, "window"),
            trackers=row_count(form, "tracker"),
        )

    @app.get("/profile")
    def profile_form(request: Request):
        if not current_email(request):
            return redirect("/login")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = current_email(request)
        if not email:
            return redirect("/login")
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            profile = parse_profile(form_to_profile(form, email), geo)
        except ValueError as exc:
            errors = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            apply_profile(s, profile)
        return redirect("/?saved=1")

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, geo.destination(tracker.destination_code).name

    @app.get("/s/{token}")
    def confirm_action(request: Request, token: str):
        with session_scope(engine) as s:
            try:
                action, _, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
        return page(
            request,
            "action_confirm.html",
            action=action,
            label=ACTION_LABELS[action.kind],
            destination=destination,
        )

    @app.post("/s/{token}")
    def do_action(request: Request, token: str, price: str = Form("")):
        with session_scope(engine) as s:
            try:
                action, tracker, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
            amount = None
            if action.kind == "under":
                try:
                    amount = Decimal(price.replace("$", "").replace(",", "").strip())
                except InvalidOperation:
                    amount = None
            try:
                message = apply_action(s, tracker, action, today(), price=amount)
            except ValueError as exc:
                return page(
                    request,
                    "action_confirm.html",
                    400,
                    action=action,
                    label=ACTION_LABELS[action.kind],
                    destination=destination,
                    error=str(exc),
                )
        return page(request, "message.html", title=f"Done: {destination}", message=message)

    return app
```

- [ ] **Step 5: Write `ptopilot/web/static/app.css`**

```css
/* ptopilot design system (V2 spec §3). Every page uses these tokens and classes; no page-specific styles. */

:root {
  color-scheme: light;
  --bg: #fbf7f0;
  --surface: #ffffff;
  --ink: #1f2937;
  --muted: #6b7280;
  --line: #f3f4f6;
  --track: #e5e7eb;
  --btn: #111827;
  --danger: #b91c1c;
  --ok: #15803d;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 3px rgba(0, 0, 0, .08);
  --serif: "Fraunces", Georgia, "Times New Roman", serif;
  --sans: "Inter", system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  --gutter: 16px;
  --dest: #374151;       /* set per destination with style="--dest:…;--dest-tint:…" */
  --dest-tint: #cdcfd3;
}
@media (min-width: 768px) { :root { --gutter: 24px; } }

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--sans); }
a { color: inherit; }
img, svg { max-width: 100%; }
h1, h2, h3 { font-family: var(--serif); font-weight: 600; line-height: 1.2; margin: 0; }
h1 { font-size: 30px; letter-spacing: -.01em; }
h2 { font-size: 20px; }
h3 { font-size: 17px; }
p { margin: 0 0 12px; }
.num { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.error { color: var(--danger); }
.ok { color: var(--ok); }
.eyebrow { font: 600 11px/1.4 var(--sans); letter-spacing: .12em; text-transform: uppercase; }

/* Layout */
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 var(--gutter); }
.site-header .wrap { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 18px; padding-bottom: 18px; }
.logo { font: 600 22px/1 var(--serif); text-decoration: none; letter-spacing: -.01em; }
.nav { display: flex; align-items: center; gap: 16px; font-size: 14px; }
.nav a { color: var(--muted); text-decoration: none; }
.nav a:hover, .nav a[aria-current="page"] { color: var(--ink); }
main.wrap { padding-bottom: 56px; }
.page-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 8px 16px; margin: 8px 0 18px; }
.page-head p { margin: 4px 0 0; }
.stack > * + * { margin-top: 14px; }
.site-footer { color: var(--muted); font-size: 13px; padding: 24px 0 40px; }

/* Surfaces */
.panel { background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); padding: 18px; }
.panel > h2:first-child, .panel > h3:first-child { margin-bottom: 10px; }
.panel-narrow { max-width: 460px; margin: 32px auto 0; }
.notice { border-left: 4px solid var(--ok); }
.notice-error { border-left: 4px solid var(--danger); }

/* Buttons and forms */
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 16px; border-radius: var(--radius-sm); border: 1px solid var(--btn); background: var(--btn); color: #fff; font: 600 14px/1.2 var(--sans); text-decoration: none; cursor: pointer; }
.btn:hover { background: #000; }
.btn-ghost { background: transparent; color: var(--ink); border-color: #d6d3d1; }
.btn-ghost:hover { background: var(--surface); }
.btn-sm { padding: 6px 10px; font-size: 13px; }
.link-btn { background: none; border: 0; padding: 0; font: inherit; color: var(--muted); text-decoration: underline; cursor: pointer; }
form.inline { display: inline; }
.field { display: block; margin: 0 0 12px; }
.field > span { display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.field small { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
input, select { width: 100%; padding: 9px 11px; border: 1px solid #d6d3d1; border-radius: var(--radius-sm); background: #fff; color: var(--ink); font: inherit; }
input:focus, select:focus { outline: 2px solid var(--dest, #111827); outline-offset: 1px; border-color: transparent; }
input[type="checkbox"] { width: auto; margin: 0 8px 0 0; }
.check { display: flex; align-items: center; font-size: 14px; margin: 6px 0; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0 14px; }
.row-fields { display: grid; grid-template-columns: 2fr repeat(4, 1fr); gap: 0 10px; align-items: end; }
@media (max-width: 640px) { .row-fields { grid-template-columns: 1fr 1fr; } .row-fields > :first-child { grid-column: 1 / -1; } }
.form-actions { display: flex; gap: 10px; align-items: center; margin-top: 18px; }

/* "Where this price sits" bar: the typical band (tint) and today's price (dot) */
.pbar { position: relative; height: 8px; border-radius: 999px; background: var(--track); margin: 10px 0 8px; }
.pbar .band { position: absolute; top: 0; height: 8px; border-radius: 999px; background: var(--dest-tint); }
.pbar .dot { position: absolute; top: -3px; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; background: var(--dest); border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0, 0, 0, .06); }
.vs { font-size: 13px; font-weight: 600; color: var(--muted); }
.vs-below { color: var(--dest); }

/* PTO bar */
.pto { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 14px 18px; }
.pto-track { flex: 1 1 200px; display: flex; gap: 3px; height: 10px; }
.pto-track span { border-radius: 999px; }
.pto-used { background: #9ca3af; }
.pto-left { background: var(--track); }

/* Destination cards */
.grid { display: grid; gap: 14px; grid-template-columns: 1fr; }
@media (min-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
.dest-card { display: block; background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; text-decoration: none; transition: box-shadow .15s, transform .15s; }
a.dest-card:hover { box-shadow: 0 6px 18px rgba(0, 0, 0, .1); transform: translateY(-1px); }
.dest-head { background: var(--dest); background: linear-gradient(135deg, var(--dest), color-mix(in srgb, var(--dest) 70%, #000)); color: #fff; padding: 14px 18px; }
.dest-head .eyebrow { opacity: .85; }
.dest-head h2, .dest-head h3 { color: #fff; }
.dest-body { padding: 14px 18px 16px; }
.price { font: 700 24px/1.1 var(--sans); font-variant-numeric: tabular-nums; }
.price-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; }
.meta { color: var(--muted); font-size: 13px; }
.dimmed { opacity: .55; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--line); color: var(--muted); font-size: 12px; font-weight: 600; }

/* Destination page */
.hero { border-radius: var(--radius); padding: 22px 22px 24px; margin-bottom: 16px; }
.hero h1 { color: #fff; font-size: 34px; margin-top: 4px; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.hero .btn-ghost { color: #fff; border-color: rgba(255, 255, 255, .5); }
.hero .btn-ghost:hover { background: rgba(255, 255, 255, .12); }
.trips { width: 100%; border-collapse: collapse; font-size: 14px; }
.trips th { text-align: left; font: 600 11px/1.4 var(--sans); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 0 8px 8px; }
.trips td { padding: 10px 8px; border-top: 1px solid var(--line); vertical-align: middle; }
.trips td.bar-cell { width: 26%; min-width: 120px; }
.trips .pbar { margin: 0; }
@media (max-width: 640px) {
  .trips thead { display: none; }
  .trips, .trips tbody, .trips tr, .trips td { display: block; width: 100%; }
  .trips tr { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 12px 0; border-top: 1px solid var(--line); }
  .trips td { border: 0; padding: 0; }
  .trips td.bar-cell { grid-column: 1 / -1; width: auto; padding: 6px 0; }
  .trips td.flights { grid-column: 1 / -1; }
}
.trend-panel .trend { display: block; width: 100%; height: auto; margin: 8px 0 4px; }
.trend-axis { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }

/* Landing */
.landing-hero { display: grid; gap: 28px; align-items: center; padding: 24px 0 36px; }
@media (min-width: 768px) { .landing-hero { grid-template-columns: 1.1fr 1fr; padding: 48px 0 56px; } }
.landing-hero h1 { font-size: clamp(32px, 5vw, 46px); line-height: 1.08; }
.lede { font-size: 17px; color: #4b5563; margin: 14px 0 22px; max-width: 34em; }
.signin { display: flex; flex-wrap: wrap; gap: 8px; max-width: 440px; }
.signin input { flex: 1 1 220px; }
.samples { display: grid; gap: 12px; }
.sample-label { position: absolute; top: 10px; right: 12px; background: rgba(255, 255, 255, .2); color: #fff; }
.samples .dest-card { position: relative; }
.steps { display: grid; gap: 12px; grid-template-columns: 1fr; counter-reset: step; }
@media (min-width: 768px) { .steps { grid-template-columns: repeat(3, 1fr); } }
.step { counter-increment: step; }
.step::before { content: counter(step); display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: var(--btn); color: #fff; font: 700 13px/1 var(--sans); margin-bottom: 10px; }
```

- [ ] **Step 6: Write `ptopilot/web/templates/_components.html`**

```html
{# Shared building blocks (V2 spec §3.3). Pages compose these instead of styling things themselves. #}

{% macro dest_style(palette) -%}
--dest:{{ palette.color }};--dest-tint:{{ palette.tint }}
{%- endmacro %}

{% macro price_bar(bar) -%}
{% if bar %}<div class="pbar" role="img" aria-label="Price compared with the typical range">
  <span class="band" style="left:{{ bar.band_start }}%;width:{{ (bar.band_end - bar.band_start) | round(1) }}%"></span>
  <span class="dot" style="left:{{ bar.dot }}%"></span>
</div>{% endif %}
{%- endmacro %}

{% macro vs_typical(option) -%}
{% set pct = option.pct_below %}
{% if pct is none %}<span class="vs">typical price still being learned</span>
{% elif pct >= 2 %}<span class="vs vs-below">{{ pct }}% below typical</span>
{% elif pct <= -2 %}<span class="vs">{{ -pct }}% above typical</span>
{% else %}<span class="vs">about typical</span>{% endif %}
{%- endmacro %}

{% macro season(option) -%}
{% if option.season_rating == "good" %}Good season{% elif option.season_rating == "shoulder" %}Shoulder season{% else %}Off-season{% endif %}{% if option.weather_note %} · {{ option.weather_note }}{% endif %}
{%- endmacro %}

{% macro pto_bar(total, committed) -%}
{% set left = total - committed %}
<div class="panel pto">
  <span><b class="num">{{ left }}</b> PTO day{{ "s" if left != 1 }} left</span>
  <div class="pto-track" aria-hidden="true">
    {% if committed %}<span class="pto-used" style="flex:{{ committed }}"></span>{% endif %}
    {% if left > 0 %}<span class="pto-left" style="flex:{{ left }}"></span>{% endif %}
  </div>
  <span class="muted small">{{ committed }} of {{ total }} committed</span>
</div>
{%- endmacro %}

{% macro dest_card(s, href=None, sample=False) -%}
<{{ "a" if href else "div" }} class="dest-card{{ ' dimmed' if s.snoozed_until }}" style="{{ dest_style(s.palette) }}"{% if href %} href="{{ href }}"{% endif %}>
  <div class="dest-head">
    {% if sample %}<span class="tag sample-label">Example</span>{% endif %}
    <div class="eyebrow">{{ s.stay[0] }}–{{ s.stay[1] }} days on the ground</div>
    <h2>{{ s.name }}</h2>
  </div>
  <div class="dest-body">
    {% if s.best %}
    {% set o = s.best %}
    <div class="price-line"><span class="price">{{ o.price | money(o.currency) }}</span>{{ vs_typical(o) }}</div>
    {{ price_bar(o.bar) }}
    <div class="meta">{{ o.depart_date | dates(o.return_date) }} · {{ o.pto_cost }} PTO for {{ o.days_away }} days{% if o.open_jaw %} · open-jaw{% endif %}</div>
    <div class="meta">{{ season(o) }}</div>
    {% else %}
    <div class="meta">First prices after the next daily scan.</div>
    {% endif %}
    {% if s.snoozed_until %}<div class="meta">Snoozed until {{ s.snoozed_until | day }}</div>{% endif %}
  </div>
</{{ "a" if href else "div" }}>
{%- endmacro %}

{% macro field(name, label, value="", type="text", hint=None, attrs="") -%}
<label class="field"><span>{{ label }}</span>
  <input id="{{ name }}" name="{{ name }}" type="{{ type }}" value="{{ value }}" {{ attrs | safe }}>
  {% if hint %}<small>{{ hint }}</small>{% endif %}
</label>
{%- endmacro %}
```

- [ ] **Step 7: Write `ptopilot/web/templates/action_confirm.html` (full new contents)**

```html
{% extends "base.html" %}
{% block title %}{{ label }} · ptopilot{% endblock %}
{% block content %}
<div class="panel panel-narrow">
  <h1>{{ destination }}: {{ label | replace("…", "a price") }}?</h1>
  <div style="margin-top:10px;">
  {% if action.kind == "trip" %}
  <p>Stop suggesting <b>{{ action.depart | day }} → {{ action.ret | day }}</b> for {{ destination }}. Other dates keep being tracked.</p>
  {% elif action.kind == "snooze30" %}
  <p>Pause all {{ destination }} alerts for 30 days. Prices keep being collected in the background.</p>
  {% elif action.kind == "year" %}
  <p>Pause {{ destination }} alerts until the end of {{ action.depart.year if action.depart else "this year" }}.</p>
  {% else %}
  <p>Only tell me about {{ destination }} trips under this price (round trip, per person):</p>
  {% endif %}
  </div>
  <form method="post">
    {% if action.kind == "under" %}
    <label class="field"><span>Maximum price (USD)</span>
      <input id="price" name="price" inputmode="numeric" placeholder="e.g. 750" required></label>
    {% endif %}
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <div class="form-actions"><button class="btn" type="submit">Confirm</button></div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 8: Write `ptopilot/web/templates/base.html` (full new contents)**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}ptopilot{% endblock %}</title>
<meta name="description" content="ptopilot watches flight prices for the trips your PTO can actually take, and emails you when one is genuinely cheap.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Inter:wght@400;600;700&display=swap">
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <a class="logo" href="/">ptopilot</a>
    <nav class="nav" aria-label="Main">
      {% if signed_in %}
      <a href="/" {% if active == "dashboard" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/profile" {% if active == "profile" %}aria-current="page"{% endif %}>Profile</a>
      <form class="inline" method="post" action="/logout"><button class="link-btn" type="submit">Sign out</button></form>
      {% else %}
      <a class="btn btn-ghost btn-sm" href="/#sign-in">Sign in</a>
      {% endif %}
    </nav>
  </div>
</header>
<main class="wrap">
{% block content %}{% endblock %}
</main>
<footer class="site-footer wrap">ptopilot · flight prices for the PTO you actually have · invite-only for now</footer>
</body>
</html>
```

- [ ] **Step 9: Write `ptopilot/web/templates/login_sent.html` (full new contents)**

```html
{% extends "base.html" %}
{% block title %}Check your email · ptopilot{% endblock %}
{% block content %}
<div class="panel panel-narrow">
  <h1>Check your email</h1>
  <p style="margin-top:10px;">If that address is invited, a sign-in link is on its way. It works for 15 minutes.</p>
  <p class="muted small">Not there? Check spam, or <a href="/#sign-in">try again</a>.</p>
</div>
{% endblock %}
```

- [ ] **Step 10: Write `ptopilot/web/templates/message.html` (full new contents)**

```html
{% extends "base.html" %}
{% block title %}{{ title }} · ptopilot{% endblock %}
{% block content %}
<div class="panel panel-narrow">
  <h1>{{ title }}</h1>
  <p style="margin-top:10px;">{{ message }}</p>
  {% if login %}<p><a class="btn" href="/#sign-in">Get a new link</a></p>{% endif %}
  {% if signed_in %}<p class="small"><a href="/">Back to your dashboard</a></p>{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 11: Write `pyproject.toml` (full new contents)**

```toml
[project]
name = "ptopilot"
version = "0.1.0"
description = "PTO-aware flight deal tracker"
requires-python = ">=3.12"
dependencies = [
    "holidays>=0.60",
    "pyyaml>=6.0",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "httpx>=0.27",
    "fast-flights>=3.1,<4",
    # fast-flights 3.1.0 imports typing_extensions without declaring it
    "typing_extensions>=4.12",
    "jinja2>=3.1",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "itsdangerous>=2.2",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["ptopilot*"]

[tool.setuptools.package-data]
"ptopilot.data" = ["*.yaml"]
"ptopilot.digest" = ["templates/*.j2"]
"ptopilot.web" = ["templates/*.html", "static/*.css"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits real external APIs; run manually with -m live"]
addopts = "-m 'not live'"

[tool.ruff]
line-length = 110
target-version = "py312"
extend-exclude = ["docs"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 12: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_design_system.py`

Expected: PASS. Verified tail: `6 passed, 1 warning in 3.11s`

- [ ] **Step 13: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `402 passed, 1 deselected, 1 warning in 55.20s`; ruff reports nothing.

- [ ] **Step 14: Commit and push**

```bash
git add -A
git commit -m "feat(web): design system stylesheet, base layout and components

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 8: Landing page

Signed out, `/` is the product hero with the sign-in form and two clearly labelled example cards. `GET /login` and sign-out now go to `/`.

**Files:**
- Modify: `ptopilot/web/app.py`
- Create: `ptopilot/web/samples.py`
- Modify: `ptopilot/web/static/app.css`
- Create: `ptopilot/web/templates/landing.html`
- Delete: `ptopilot/web/templates/login.html`
- Modify: `tests/web/conftest.py`
- Modify: `tests/web/test_auth.py`
- Modify: `tests/web/test_hardening.py`
- Create: `tests/web/test_landing.py`

**Interfaces:**
- Consumes: Task 6 `DestinationSummary`, `TripOption`; Task 7 `dest_card`.
- Produces: `ptopilot.web.samples.sample_cards(geo)`; `templates/landing.html`; test helper `tests.web.conftest.is_landing(response)`. Deletes `templates/login.html`.

> `test_auth.py` and `test_hardening.py` change where they expected a redirect to `/login`: signed out, `/` is now the landing page, and other pages redirect to `/`.

- [ ] **Step 1: Update the test file `tests/web/conftest.py` (full new contents)**

```python
"""Web app fixtures: the app on the test database, a capturing emailer, and a sign-in helper."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import insert

from ptopilot.db.models import Invite
from ptopilot.db.session import session_scope
from ptopilot.settings import Settings
from ptopilot.web.app import create_app

TODAY = date(2027, 3, 4)
KEY = "test-secret-key"


class CapturingEmailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, html, text):
        self.sent.append({"to": to, "subject": subject, "text": text})
        return "msg"

    def last_link(self) -> str:
        return re.search(r"https?://\S+", self.sent[-1]["text"]).group(0)


@pytest.fixture
def emailer():
    return CapturingEmailer()


@pytest.fixture
def client(clean_engine, emailer):
    settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
    app = create_app(settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def invite(engine, email):
    with session_scope(engine) as s:
        s.execute(insert(Invite).values(email=email).on_conflict_do_nothing())


def is_landing(response) -> bool:
    """The signed-out home page: the product pitch with the sign-in form."""
    return response.status_code == 200 and 'id="sign-in"' in response.text


def sign_in(client, emailer, engine, email="nick@example.com"):
    invite(engine, email)
    client.post("/login", data={"email": email})
    link = emailer.last_link()
    response = client.get(link.replace("http://testserver", ""))
    assert response.status_code == 303
    return response


PROFILE_FORM = {
    "home_airport": "jfk",
    "nearby_airports": "EWR, PHL",
    "country": "US",
    "holiday_calendar": "US",
    "ignored_holidays": "Columbus Day, Veterans Day",
    "extra_days_off": "",
    "pto_days_total": "22",
    "pto_committed": "7",
    "min_trip_days": "7",
    "max_trip_days": "16",
    "weather_tolerance": "normal",
    "max_stops_short": "3",
    "max_stops_long": "3",
    "friday_evening_min_time": "17:00",
    "allow_overnight_layover": "on",
    "friday_evening_departure": "on",
    "window_start_0": "2027-03-01",
    "window_end_0": "2027-03-31",
    "window_start_1": "",
    "window_end_1": "",
    "tracker_dest_0": "AZORES",
    "tracker_min_0": "7",
    "tracker_max_0": "10",
    "tracker_priority_0": "1",
    "tracker_price_0": "",
    "tracker_dest_1": "",
    "tracker_min_1": "",
    "tracker_max_1": "",
    "tracker_priority_1": "2",
    "tracker_price_1": "",
}
```

- [ ] **Step 2: Update the test file `tests/web/test_auth.py` (full new contents)**

```python
from ptopilot.links import login_token
from tests.web.conftest import KEY, invite, is_landing, sign_in


def test_health_check(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/favicon.ico").status_code == 204


def test_pages_require_sign_in(client):
    assert is_landing(client.get("/"))
    response = client.get("/profile")
    assert (response.status_code, response.headers["location"]) == (303, "/")


def test_uninvited_email_gets_the_same_answer_and_no_email(client, emailer):
    response = client.post("/login", data={"email": "stranger@example.com"})
    assert response.status_code == 200 and "If that address is invited" in response.text
    assert emailer.sent == []


def test_invited_email_gets_a_link_that_signs_in(client, emailer, clean_engine):
    invite(clean_engine, "nick@example.com")
    response = client.post("/login", data={"email": " Nick@Example.com "})
    assert "If that address is invited" in response.text
    assert emailer.sent[0]["to"] == "nick@example.com"
    assert emailer.last_link().startswith("http://testserver/auth?token=")
    signed_in = client.get(emailer.last_link().replace("http://testserver", ""))
    assert (signed_in.status_code, signed_in.headers["location"]) == (303, "/")
    assert client.get("/").headers["location"] == "/profile"  # signed in, but no profile yet


def test_bad_and_expired_links_are_refused(client):
    assert client.get("/auth?token=garbage").status_code == 400
    forged = login_token("some-other-key", "nick@example.com")
    response = client.get(f"/auth?token={forged}")
    assert response.status_code == 400 and "not valid" in response.text
    assert is_landing(client.get("/"))


def test_sign_out(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/logout").headers["location"] == "/"
    assert is_landing(client.get("/"))


def test_token_for_a_valid_key_signs_in_directly(client, clean_engine):
    invite(clean_engine, "nick@example.com")
    response = client.get(f"/auth?token={login_token(KEY, 'nick@example.com')}")
    assert response.status_code == 303
```

- [ ] **Step 3: Update the test file `tests/web/test_hardening.py` (full new contents)**

```python
"""Behaviour that matters because the app is public: revoked access, link floods, odd input."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.digest.send import deliver
from ptopilot.links import Action, action_token
from ptopilot.settings import Settings
from ptopilot.web.app import create_app
from tests.digest.conftest import add_candidate, add_tracker, add_user
from tests.web.conftest import KEY, PROFILE_FORM, TODAY, CapturingEmailer, invite, is_landing, sign_in


def test_dashboard_still_shows_deals_after_they_were_emailed(client, emailer, clean_engine):
    from ptopilot.data import load_geo, load_seasons
    from ptopilot.digest.select import build_digests

    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    add_candidate(clean_engine, tracker_id, 700, level="good", go_now=90, run_date=TODAY)
    add_candidate(clean_engine, tracker_id, 603, level="good", go_now=40, run_date=TODAY,
                  depart=TODAY.replace(day=12), ret=TODAY.replace(day=21))  # fmt: skip
    digests = build_digests(clean_engine, load_geo(), load_seasons(), TODAY)
    deliver(clean_engine, digests, TODAY, emailer=CapturingEmailer())  # both deals now count as "sent"
    page = client.get("/").text
    assert "$603" in page and "$700" in page
    assert page.index("$603") < page.index("$700")  # cheapest first, not by go-now


def test_removing_an_invite_ends_the_session(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    assert is_landing(client.get("/"))
    assert client.get("/profile").headers["location"] == "/"


def test_a_removed_traveler_cannot_recreate_themselves(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    response = client.post("/profile", data=PROFILE_FORM)
    assert response.headers["location"] == "/"
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None and s.scalar(select(Invite)) is None


def test_a_sign_in_link_for_a_revoked_invite_does_not_work(client, emailer, clean_engine):
    invite(clean_engine, "nick@example.com")
    client.post("/login", data={"email": "nick@example.com"})
    link = emailer.last_link().replace("http://testserver", "")
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    assert client.get(link).status_code == 400


def test_sign_in_links_are_rate_limited_per_address(clean_engine):
    clock = {"t": 1000.0}
    emailer = CapturingEmailer()
    settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
    app = create_app(
        settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY, now=lambda: clock["t"]
    )
    invite(clean_engine, "nick@example.com")
    with TestClient(app, follow_redirects=False) as c:
        for _ in range(5):
            assert "If that address is invited" in c.post("/login", data={"email": "nick@example.com"}).text
        assert len(emailer.sent) == 1
        clock["t"] += 121
        c.post("/login", data={"email": "nick@example.com"})
        assert len(emailer.sent) == 2


@pytest.mark.parametrize("price", ["NaN", "sNaN", "Infinity", "-5", "1e20", "1e999999999", "0"])
def test_only_if_under_rejects_odd_prices_with_a_message(client, clean_engine, price):
    tid = add_tracker(clean_engine, add_user(clean_engine))
    token = action_token(KEY, Action(tid, "under"))
    response = client.post(f"/s/{token}", data={"price": price})
    assert response.status_code == 400 and "between $1 and $99,999" in response.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).max_price is None
```

- [ ] **Step 4: Write the failing test file `tests/web/test_landing.py`**

```python
"""The signed-out home page: what ptopilot is, and the sign-in form."""

from tests.web.conftest import is_landing, sign_in


def test_signed_out_home_is_the_landing_page_with_sign_in(client):
    page = client.get("/")
    assert is_landing(page)
    assert "Your PTO, spent on the right trips" in page.text
    assert 'action="/login"' in page.text and 'type="email"' in page.text
    assert "How it works" in page.text and "Invite-only" in page.text


def test_sample_cards_are_labelled_examples_not_real_trips(client):
    page = client.get("/").text
    assert page.count("Example</span>") == 2
    assert "Azores" in page and "Patagonia" in page and "below typical" in page


def test_old_sign_in_address_redirects_home(client):
    response = client.get("/login")
    assert (response.status_code, response.headers["location"]) == (303, "/")


def test_signing_in_from_the_landing_form_still_works(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.get("/").headers["location"] == "/profile"  # signed in, no profile yet
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_landing.py tests/web/test_auth.py tests/web/test_hardening.py`

Expected: FAIL. Verified tail: `8 failed, 15 passed, 1 warning in 10.24s`

- [ ] **Step 6: Write `ptopilot/web/app.py` (full new contents)**

```python
"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import date_range, day, money
from ptopilot.digest.select import TrackerRow, build_digests
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count
from ptopilot.web.samples import sample_cards

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
TEMPLATES.env.filters.update(money=money, day=day, dates=date_range)
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_COOLDOWN_S = 120  # at most one sign-in email per address per 2 minutes


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
    now: Callable[[], float] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    now = now or time.monotonic
    last_link_sent: dict[str, float] = {}  # per process; enough for one small instance
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def is_invited(email: str) -> bool:
        with session_scope(engine) as s:
            return s.scalar(select(Invite.email).where(Invite.email == email)) is not None

    def current_email(request: Request) -> str | None:
        """The signed-in email, as long as it is still invited; removing an invite ends the session."""
        email = request.session.get("email")
        if email and not is_invited(email):
            request.session.clear()
            return None
        return email

    def signed_in_user(s, request: Request) -> User | None:
        email = current_email(request)
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError):
        """Malformed form fields or URLs (e.g. a non-numeric id) get a page, not FastAPI's JSON."""
        message = "Something in that request didn't look right. Go back and try again."
        return page(request, "message.html", 400, title="That didn't work", message=message)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form():
        return redirect("/")  # the sign-in form lives on the landing page

    def send_link(email: str, link: str) -> None:
        if emailer is None:
            log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            return
        try:
            emailer.send(
                email,
                "Your ptopilot sign-in link",
                f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                f"Sign in to ptopilot (link works for 15 minutes): {link}",
            )
        except EmailError as exc:
            log.error("sign-in email not sent: %s", exc)

    @app.post("/login")
    def login(request: Request, background: BackgroundTasks, email: str = Form("")):
        email = email.strip().lower()
        cooled_down = now() - last_link_sent.get(email, float("-inf")) >= LOGIN_COOLDOWN_S
        if email and cooled_down and is_invited(email):
            last_link_sent[email] = now()
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            # Sent after the response, so invited and uninvited addresses answer equally fast.
            background.add_task(send_link, email, link)
        # Same answer either way, so the form doesn't reveal who is invited.
        return page(request, "login_sent.html")

    @app.get("/auth")
    def auth(request: Request, token: str = ""):
        try:
            email = read_login_token(settings.secret_key, token)
        except TokenError as exc:
            return page(
                request, "message.html", 400, title="Sign-in link problem", message=f"{exc}.", login=True
            )
        if not is_invited(email):
            message = "this address is no longer invited."
            return page(request, "message.html", 400, title="Sign-in link problem", message=message)
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not current_email(request):
            return page(request, "landing.html", samples=sample_cards(geo))
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        # The dashboard shows everything current, including deals already emailed.
        digests = build_digests(engine, geo, seasons, today(), "none", user_id=user_id, skip_sent=False)
        digest = digests[0] if digests else None
        trackers = digest.trackers if digest else []
        if digest is None:  # no scan has priced anything yet: list the trackers without prices
            with session_scope(engine) as s:
                rows = s.scalars(
                    select(Tracker)
                    .where(Tracker.user_id == user_id, Tracker.active.is_(True))
                    .order_by(Tracker.id)
                )
                trackers = [
                    TrackerRow(t.id, geo.destination(t.destination_code).name, None, None, "new", None,
                               t.snoozed_until if t.snoozed_until and t.snoozed_until >= today() else None)
                    for t in rows
                ]  # fmt: skip
        return page(
            request,
            "dashboard.html",
            digest=digest,
            deals=(sorted(digest.deals, key=lambda d: (d.price, -d.go_now))[:5] if digest else []),
            trackers=trackers,
            pto_total=pto_total,
            pto_committed=pto_committed,
            saved=bool(saved),
        )

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: int, days: int = Form(30)):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            snooze(tracker, date.fromordinal(today().toordinal() + max(days, 1)))
        return redirect("/")

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: int):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            unsnooze(tracker)
        return redirect("/")

    # --- profile / onboarding --------------------------------------------------------------------

    def profile_page(request: Request, form: dict, errors: list[str], status: int = 200):
        return page(
            request,
            "profile.html",
            status,
            form=form,
            errors=errors,
            destinations=geo.destinations(),
            windows=row_count(form, "window"),
            trackers=row_count(form, "tracker"),
        )

    @app.get("/profile")
    def profile_form(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = current_email(request)
        if not email:
            return redirect("/")
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            profile = parse_profile(form_to_profile(form, email), geo)
        except ValueError as exc:
            errors = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            apply_profile(s, profile)
        return redirect("/?saved=1")

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, geo.destination(tracker.destination_code).name

    @app.get("/s/{token}")
    def confirm_action(request: Request, token: str):
        with session_scope(engine) as s:
            try:
                action, _, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
        return page(
            request,
            "action_confirm.html",
            action=action,
            label=ACTION_LABELS[action.kind],
            destination=destination,
        )

    @app.post("/s/{token}")
    def do_action(request: Request, token: str, price: str = Form("")):
        with session_scope(engine) as s:
            try:
                action, tracker, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
            amount = None
            if action.kind == "under":
                try:
                    amount = Decimal(price.replace("$", "").replace(",", "").strip())
                except InvalidOperation:
                    amount = None
            try:
                message = apply_action(s, tracker, action, today(), price=amount)
            except ValueError as exc:
                return page(
                    request,
                    "action_confirm.html",
                    400,
                    action=action,
                    label=ACTION_LABELS[action.kind],
                    destination=destination,
                    error=str(exc),
                )
        return page(request, "message.html", title=f"Done: {destination}", message=message)

    return app
```

- [ ] **Step 7: Write `ptopilot/web/samples.py`**

```python
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
```

- [ ] **Step 8: Write `ptopilot/web/static/app.css` (full new contents)**

```css
/* ptopilot design system (V2 spec §3). Every page uses these tokens and classes; no page-specific styles. */

:root {
  color-scheme: light;
  --bg: #fbf7f0;
  --surface: #ffffff;
  --ink: #1f2937;
  --muted: #6b7280;
  --line: #f3f4f6;
  --track: #e5e7eb;
  --btn: #111827;
  --danger: #b91c1c;
  --ok: #15803d;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 3px rgba(0, 0, 0, .08);
  --serif: "Fraunces", Georgia, "Times New Roman", serif;
  --sans: "Inter", system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  --gutter: 16px;
  --dest: #374151;       /* set per destination with style="--dest:…;--dest-tint:…" */
  --dest-tint: #cdcfd3;
}
@media (min-width: 768px) { :root { --gutter: 24px; } }

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--sans); }
a { color: inherit; }
img, svg { max-width: 100%; }
h1, h2, h3 { font-family: var(--serif); font-weight: 600; line-height: 1.2; margin: 0; }
h1 { font-size: 30px; letter-spacing: -.01em; }
h2 { font-size: 20px; }
h3 { font-size: 17px; }
p { margin: 0 0 12px; }
.num { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.error { color: var(--danger); }
.ok { color: var(--ok); }
.eyebrow { font: 600 11px/1.4 var(--sans); letter-spacing: .12em; text-transform: uppercase; }

/* Layout */
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 var(--gutter); }
.site-header .wrap { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 18px; padding-bottom: 18px; }
.logo { font: 600 22px/1 var(--serif); text-decoration: none; letter-spacing: -.01em; }
.nav { display: flex; align-items: center; gap: 16px; font-size: 14px; }
.nav a { color: var(--muted); text-decoration: none; }
.nav a:hover, .nav a[aria-current="page"] { color: var(--ink); }
main.wrap { padding-bottom: 56px; }
.page-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 8px 16px; margin: 8px 0 18px; }
.page-head p { margin: 4px 0 0; }
.stack > * + * { margin-top: 14px; }
.site-footer { color: var(--muted); font-size: 13px; padding: 24px 0 40px; }

/* Surfaces */
.panel { background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); padding: 18px; }
.panel > h2:first-child, .panel > h3:first-child { margin-bottom: 10px; }
.panel-narrow { max-width: 460px; margin: 32px auto 0; }
.notice { border-left: 4px solid var(--ok); }
.notice-error { border-left: 4px solid var(--danger); }

/* Buttons and forms */
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 16px; border-radius: var(--radius-sm); border: 1px solid var(--btn); background: var(--btn); color: #fff; font: 600 14px/1.2 var(--sans); text-decoration: none; cursor: pointer; }
.btn:hover { background: #000; }
.btn-ghost { background: transparent; color: var(--ink); border-color: #d6d3d1; }
.btn-ghost:hover { background: var(--surface); }
.btn-sm { padding: 6px 10px; font-size: 13px; }
.link-btn { background: none; border: 0; padding: 0; font: inherit; color: var(--muted); text-decoration: underline; cursor: pointer; }
form.inline { display: inline; }
.field { display: block; margin: 0 0 12px; }
.field > span { display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.field small { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
input, select { width: 100%; padding: 9px 11px; border: 1px solid #d6d3d1; border-radius: var(--radius-sm); background: #fff; color: var(--ink); font: inherit; }
input:focus, select:focus { outline: 2px solid var(--dest, #111827); outline-offset: 1px; border-color: transparent; }
input[type="checkbox"] { width: auto; margin: 0 8px 0 0; }
.check { display: flex; align-items: center; font-size: 14px; margin: 6px 0; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0 14px; }
.row-fields { display: grid; grid-template-columns: 2fr repeat(4, 1fr); gap: 0 10px; align-items: end; }
@media (max-width: 640px) { .row-fields { grid-template-columns: 1fr 1fr; } .row-fields > :first-child { grid-column: 1 / -1; } }
.form-actions { display: flex; gap: 10px; align-items: center; margin-top: 18px; }

/* "Where this price sits" bar: the typical band (tint) and today's price (dot) */
.pbar { position: relative; height: 8px; border-radius: 999px; background: var(--track); margin: 10px 0 8px; }
.pbar .band { position: absolute; top: 0; height: 8px; border-radius: 999px; background: var(--dest-tint); }
.pbar .dot { position: absolute; top: -3px; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; background: var(--dest); border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0, 0, 0, .06); }
.vs { font-size: 13px; font-weight: 600; color: var(--muted); }
.vs-below { color: var(--dest); }

/* PTO bar */
.pto { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 14px 18px; }
.pto-track { flex: 1 1 200px; display: flex; gap: 3px; height: 10px; }
.pto-track span { border-radius: 999px; }
.pto-used { background: #9ca3af; }
.pto-left { background: var(--track); }

/* Destination cards */
.grid { display: grid; gap: 14px; grid-template-columns: 1fr; }
@media (min-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
.dest-card { display: block; background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; text-decoration: none; transition: box-shadow .15s, transform .15s; }
a.dest-card:hover { box-shadow: 0 6px 18px rgba(0, 0, 0, .1); transform: translateY(-1px); }
.dest-head { background: var(--dest); background: linear-gradient(135deg, var(--dest), color-mix(in srgb, var(--dest) 70%, #000)); color: #fff; padding: 14px 18px; }
.dest-head .eyebrow { opacity: .85; }
.dest-head h2, .dest-head h3 { color: #fff; }
.dest-body { padding: 14px 18px 16px; }
.price { font: 700 24px/1.1 var(--sans); font-variant-numeric: tabular-nums; }
.price-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; }
.meta { color: var(--muted); font-size: 13px; }
.dimmed { opacity: .55; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--line); color: var(--muted); font-size: 12px; font-weight: 600; }

/* Destination page */
.hero { border-radius: var(--radius); padding: 22px 22px 24px; margin-bottom: 16px; }
.hero h1 { color: #fff; font-size: 34px; margin-top: 4px; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.hero .btn-ghost { color: #fff; border-color: rgba(255, 255, 255, .5); }
.hero .btn-ghost:hover { background: rgba(255, 255, 255, .12); }
.trips { width: 100%; border-collapse: collapse; font-size: 14px; }
.trips th { text-align: left; font: 600 11px/1.4 var(--sans); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 0 8px 8px; }
.trips td { padding: 10px 8px; border-top: 1px solid var(--line); vertical-align: middle; }
.trips td.bar-cell { width: 26%; min-width: 120px; }
.trips .pbar { margin: 0; }
@media (max-width: 640px) {
  .trips thead { display: none; }
  .trips, .trips tbody, .trips tr, .trips td { display: block; width: 100%; }
  .trips tr { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 12px 0; border-top: 1px solid var(--line); }
  .trips td { border: 0; padding: 0; }
  .trips td.bar-cell { grid-column: 1 / -1; width: auto; padding: 6px 0; }
  .trips td.flights { grid-column: 1 / -1; }
}
.trend-panel .trend { display: block; width: 100%; height: auto; margin: 8px 0 4px; }
.trend-axis { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }

/* Landing */
.landing-hero { display: grid; gap: 28px; align-items: center; padding: 24px 0 36px; }
@media (min-width: 768px) { .landing-hero { grid-template-columns: 1.1fr 1fr; padding: 48px 0 56px; } }
.landing-hero h1 { font-size: clamp(32px, 5vw, 46px); line-height: 1.08; }
.lede { font-size: 17px; color: #4b5563; margin: 14px 0 22px; max-width: 34em; }
.signin { display: flex; flex-wrap: wrap; gap: 8px; max-width: 440px; }
.signin input { flex: 1 1 220px; }
.samples { display: grid; gap: 12px; }
.sample-label { position: absolute; top: 10px; right: 12px; background: rgba(255, 255, 255, .2); color: #fff; }
.samples .dest-card { position: relative; }
.steps { display: grid; gap: 12px; grid-template-columns: 1fr; counter-reset: step; }
@media (min-width: 768px) { .steps { grid-template-columns: repeat(3, 1fr); } }
.step { counter-increment: step; }
.step::before { content: counter(step); display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: var(--btn); color: #fff; font: 700 13px/1 var(--sans); margin-bottom: 10px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
```

- [ ] **Step 9: Write `ptopilot/web/templates/landing.html`**

```html
{% extends "base.html" %}
{% from "_components.html" import dest_card %}
{% block title %}ptopilot · flight deals that fit your PTO{% endblock %}
{% block content %}
<section class="landing-hero">
  <div>
    <h1>Your PTO, spent on the right trips at the right price.</h1>
    <p class="lede">Tell ptopilot your days off, holidays and bucket list. It works out which dates stretch your PTO furthest, watches those fares every day, and emails you when a trip is genuinely cheap.</p>
    <form id="sign-in" class="signin" method="post" action="/login">
      <label class="sr-only" for="email">Email</label>
      <input id="email" name="email" type="email" autocomplete="email" placeholder="you@example.com" required>
      <button class="btn" type="submit">Send sign-in link</button>
    </form>
    <p class="muted small" style="margin-top:10px;">Invite-only for now. We'll email a link that signs you in, with no password.</p>
  </div>
  <div class="samples" aria-label="Example deals">
    {% for card in samples %}{{ dest_card(card, sample=True) }}{% endfor %}
  </div>
</section>

<section>
  <h2 style="margin-bottom:14px;">How it works</h2>
  <div class="steps">
    <div class="panel step"><h3>Your PTO and windows</h3><p class="muted small" style="margin:6px 0 0;">Days off, your holiday calendar, when you can travel, and where you've been meaning to go.</p></div>
    <div class="panel step"><h3>A daily fare watch</h3><p class="muted small" style="margin:6px 0 0;">Every morning it prices the date combinations that cost you the fewest PTO days, in the right season.</p></div>
    <div class="panel step"><h3>Deals, twice a week</h3><p class="muted small" style="margin:6px 0 0;">Monday and Thursday emails flag trips well below their typical price, with one-click snoozes.</p></div>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 10: Delete `ptopilot/web/templates/login.html`**

Run: `git rm ptopilot/web/templates/login.html`

- [ ] **Step 11: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_landing.py tests/web/test_auth.py tests/web/test_hardening.py`

Expected: PASS. Verified tail: `23 passed, 1 warning in 9.76s`

- [ ] **Step 12: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `406 passed, 1 deselected, 1 warning in 59.52s`; ruff reports nothing.

- [ ] **Step 13: Commit and push**

```bash
git add -A
git commit -m "feat(web): landing page with sign-in and example deals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 9: Dashboard: destination grid

The PTO bar and one card per destination with its best current trip, cheapest first, each linking to its destination page.

**Files:**
- Modify: `ptopilot/web/app.py`
- Modify: `ptopilot/web/templates/dashboard.html`
- Create: `tests/web/test_dashboard.py`
- Modify: `tests/web/test_hardening.py`
- Modify: `tests/web/test_profile_and_dashboard.py`

**Interfaces:**
- Consumes: Task 6 `destination_summaries`; Task 7 `pto_bar`, `dest_card`.
- Produces: `templates/dashboard.html` (context: `summaries`, `run_date`, `pto_total`, `pto_committed`, `saved`).

> Two existing tests change: the dashboard shows each destination's best trip only (the $700 alternative moves to the destination page), and the PTO and empty-state wording is new.

- [ ] **Step 1: Write the failing test file `tests/web/test_dashboard.py`**

```python
"""The signed-in dashboard: PTO bar and one card per destination."""

from sqlalchemy import select

from ptopilot.db.models import Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, sign_in

TWO_DESTINATIONS = {**PROFILE_FORM, "tracker_dest_1": "MADEIRA", "tracker_min_1": "6", "tracker_max_1": "9"}


def setup(client, emailer, engine, form=TWO_DESTINATIONS) -> dict[str, int]:
    sign_in(client, emailer, engine)
    client.post("/profile", data=form)
    with session_scope(engine) as s:
        return {t.destination_code: t.id for t in s.scalars(select(Tracker))}


def test_cards_show_each_destinations_best_trip_cheapest_first(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, ids["AZORES"], 700, run_date=TODAY)
    add_candidate(clean_engine, ids["AZORES"], 650, run_date=TODAY, depart=TODAY.replace(day=12),
                  ret=TODAY.replace(day=21))  # fmt: skip
    add_candidate(clean_engine, ids["MADEIRA"], 603, run_date=TODAY, dest="FNC")
    page = client.get("/").text
    assert page.index("Madeira") < page.index("Azores")
    assert "$603" in page and "$650" in page and "$700" not in page  # best trip per destination only
    assert f'href="/trackers/{ids["AZORES"]}"' in page and "--dest:#0e7490" in page
    assert "Mar 12–21 · 5 PTO for 10 days" in page


def test_card_places_the_price_against_the_typical_range(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    add_baseline(clean_engine, 700)
    page = client.get("/").text
    assert "14% below typical" in page and 'class="pbar"' in page


def test_dashboard_says_when_prices_were_last_checked(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    assert "Prices from the Thu Mar 4 scan" in client.get("/").text


def test_pto_bar_shows_days_left_and_committed(client, emailer, clean_engine):
    setup(client, emailer, clean_engine, PROFILE_FORM)
    page = client.get("/").text
    assert "15</b> PTO days left" in page and "7 of 22 committed" in page


def test_no_trackers_points_to_the_profile(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    with session_scope(clean_engine) as s:
        s.get(Tracker, ids["AZORES"]).active = False
    assert 'No destinations yet. <a href="/profile">' in client.get("/").text
```

- [ ] **Step 2: Update the test file `tests/web/test_hardening.py` (full new contents)**

```python
"""Behaviour that matters because the app is public: revoked access, link floods, odd input."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.digest.send import deliver
from ptopilot.links import Action, action_token
from ptopilot.settings import Settings
from ptopilot.web.app import create_app
from tests.digest.conftest import add_candidate, add_tracker, add_user
from tests.web.conftest import KEY, PROFILE_FORM, TODAY, CapturingEmailer, invite, is_landing, sign_in


def test_dashboard_still_shows_deals_after_they_were_emailed(client, emailer, clean_engine):
    from ptopilot.data import load_geo, load_seasons
    from ptopilot.digest.select import build_digests

    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    add_candidate(clean_engine, tracker_id, 700, level="good", go_now=90, run_date=TODAY)
    add_candidate(clean_engine, tracker_id, 603, level="good", go_now=40, run_date=TODAY,
                  depart=TODAY.replace(day=12), ret=TODAY.replace(day=21))  # fmt: skip
    digests = build_digests(clean_engine, load_geo(), load_seasons(), TODAY)
    deliver(clean_engine, digests, TODAY, emailer=CapturingEmailer())  # both deals now count as "sent"
    page = client.get("/").text
    assert "$603" in page  # the destination's best trip, although it was emailed already


def test_removing_an_invite_ends_the_session(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    assert is_landing(client.get("/"))
    assert client.get("/profile").headers["location"] == "/"


def test_a_removed_traveler_cannot_recreate_themselves(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    response = client.post("/profile", data=PROFILE_FORM)
    assert response.headers["location"] == "/"
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None and s.scalar(select(Invite)) is None


def test_a_sign_in_link_for_a_revoked_invite_does_not_work(client, emailer, clean_engine):
    invite(clean_engine, "nick@example.com")
    client.post("/login", data={"email": "nick@example.com"})
    link = emailer.last_link().replace("http://testserver", "")
    with session_scope(clean_engine) as s:
        s.execute(delete(Invite))
    assert client.get(link).status_code == 400


def test_sign_in_links_are_rate_limited_per_address(clean_engine):
    clock = {"t": 1000.0}
    emailer = CapturingEmailer()
    settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
    app = create_app(
        settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY, now=lambda: clock["t"]
    )
    invite(clean_engine, "nick@example.com")
    with TestClient(app, follow_redirects=False) as c:
        for _ in range(5):
            assert "If that address is invited" in c.post("/login", data={"email": "nick@example.com"}).text
        assert len(emailer.sent) == 1
        clock["t"] += 121
        c.post("/login", data={"email": "nick@example.com"})
        assert len(emailer.sent) == 2


@pytest.mark.parametrize("price", ["NaN", "sNaN", "Infinity", "-5", "1e20", "1e999999999", "0"])
def test_only_if_under_rejects_odd_prices_with_a_message(client, clean_engine, price):
    tid = add_tracker(clean_engine, add_user(clean_engine))
    token = action_token(KEY, Action(tid, "under"))
    response = client.post(f"/s/{token}", data={"price": price})
    assert response.status_code == 400 and "between $1 and $99,999" in response.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).max_price is None
```

- [ ] **Step 3: Update the test file `tests/web/test_profile_and_dashboard.py` (full new contents)**

```python
from datetime import date, timedelta

from sqlalchemy import select

from ptopilot.db.models import Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from ptopilot.web.forms import form_to_profile
from tests.digest.conftest import add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, sign_in


def test_form_to_profile_maps_fields_and_skips_blank_rows():
    data = form_to_profile(PROFILE_FORM, "nick@example.com")
    assert data["home_airport"] == "JFK" and data["nearby_airports"] == ["EWR", "PHL"]
    assert data["pto_days_total"] == 22 and data["allow_overnight_layover"] is True
    assert data["windows"] == [{"start": "2027-03-01", "end": "2027-03-31"}]
    assert data["trackers"] == [{"destination": "AZORES", "min_stay": 7, "max_stay": 10, "priority": 1}]
    assert (
        form_to_profile({**PROFILE_FORM, "pto_days_total": "lots"}, "x@example.com")["pto_days_total"]
        == "lots"
    )


def test_new_traveler_fills_in_the_profile_and_lands_on_the_dashboard(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    form_page = client.get("/profile")
    assert form_page.status_code == 200 and "Your travel profile" in form_page.text
    saved = client.post("/profile", data=PROFILE_FORM)
    assert (saved.status_code, saved.headers["location"]) == (303, "/?saved=1")
    with session_scope(clean_engine) as s:
        user = s.scalar(select(User).where(User.email == "nick@example.com"))
        assert (user.home_airport, user.pto_days_total, user.pto_committed) == ("JFK", 22, 7)
        assert [t.destination_code for t in s.scalars(select(Tracker))] == ["AZORES"]
        assert len(list(s.scalars(select(TravelWindow)))) == 1
    dashboard = client.get("/?saved=1")
    assert "Profile saved" in dashboard.text and "15</b> PTO days left" in dashboard.text
    assert "Azores" in dashboard.text and "First prices after the next daily scan" in dashboard.text


def test_invalid_profile_lists_every_problem_and_saves_nothing(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    bad = {**PROFILE_FORM, "pto_committed": "30", "home_airport": "XXX", "window_end_0": "2027-02-01"}
    response = client.post("/profile", data=bad)
    assert response.status_code == 400
    for fragment in ("Please fix 3 things", "pto_committed", "XXX", "before it starts"):
        assert fragment in response.text
    assert 'value="XXX"' in response.text  # the submitted values are kept
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User)) is None


def test_existing_profile_is_prefilled(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    page = client.get("/profile").text
    assert 'value="JFK"' in page and 'value="EWR, PHL"' in page and 'value="2027-03-01"' in page
    assert '<option value="AZORES" selected>' in page


def test_dashboard_shows_prices_and_snooze_controls(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    add_candidate(clean_engine, tracker_id, 603, level="good", run_date=TODAY)
    page = client.get("/").text
    assert "$603" in page and f'href="/trackers/{tracker_id}"' in page
    assert client.post(f"/trackers/{tracker_id}/snooze", data={"days": "30"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until == TODAY + timedelta(days=30)
    snoozed = client.get("/").text
    assert "Snoozed until Sat Apr 3" in snoozed and f'action="/trackers/{tracker_id}/unsnooze"' in snoozed
    client.post(f"/trackers/{tracker_id}/unsnooze")
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until is None


def test_cannot_touch_someone_elses_tracker(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine, "owner@example.com")
    client.post("/profile", data=PROFILE_FORM)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    client.post("/logout")
    sign_in(client, emailer, clean_engine, "intruder@example.com")
    assert client.post(f"/trackers/{tracker_id}/snooze", data={"days": "30"}).status_code == 404
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until is None


def test_dashboard_pto_bar_handles_zero_pto(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data={**PROFILE_FORM, "pto_days_total": "0", "pto_committed": "0"})
    assert client.get("/").status_code == 200


def test_unused_date_helper():
    assert date(2027, 3, 4) == TODAY
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_dashboard.py tests/web/test_profile_and_dashboard.py tests/web/test_hardening.py`

Expected: FAIL. Verified tail: `7 failed, 6 passed, 1 warning in 7.19s`

- [ ] **Step 5: Write `ptopilot/web/app.py` (full new contents)**

```python
"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import date_range, day, money
from ptopilot.digest.select import latest_run_date
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count
from ptopilot.web.history import destination_summaries
from ptopilot.web.samples import sample_cards

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
TEMPLATES.env.filters.update(money=money, day=day, dates=date_range)
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_COOLDOWN_S = 120  # at most one sign-in email per address per 2 minutes


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
    now: Callable[[], float] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    now = now or time.monotonic
    last_link_sent: dict[str, float] = {}  # per process; enough for one small instance
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def is_invited(email: str) -> bool:
        with session_scope(engine) as s:
            return s.scalar(select(Invite.email).where(Invite.email == email)) is not None

    def current_email(request: Request) -> str | None:
        """The signed-in email, as long as it is still invited; removing an invite ends the session."""
        email = request.session.get("email")
        if email and not is_invited(email):
            request.session.clear()
            return None
        return email

    def signed_in_user(s, request: Request) -> User | None:
        email = current_email(request)
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError):
        """Malformed form fields or URLs (e.g. a non-numeric id) get a page, not FastAPI's JSON."""
        message = "Something in that request didn't look right. Go back and try again."
        return page(request, "message.html", 400, title="That didn't work", message=message)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form():
        return redirect("/")  # the sign-in form lives on the landing page

    def send_link(email: str, link: str) -> None:
        if emailer is None:
            log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            return
        try:
            emailer.send(
                email,
                "Your ptopilot sign-in link",
                f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                f"Sign in to ptopilot (link works for 15 minutes): {link}",
            )
        except EmailError as exc:
            log.error("sign-in email not sent: %s", exc)

    @app.post("/login")
    def login(request: Request, background: BackgroundTasks, email: str = Form("")):
        email = email.strip().lower()
        cooled_down = now() - last_link_sent.get(email, float("-inf")) >= LOGIN_COOLDOWN_S
        if email and cooled_down and is_invited(email):
            last_link_sent[email] = now()
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            # Sent after the response, so invited and uninvited addresses answer equally fast.
            background.add_task(send_link, email, link)
        # Same answer either way, so the form doesn't reveal who is invited.
        return page(request, "login_sent.html")

    @app.get("/auth")
    def auth(request: Request, token: str = ""):
        try:
            email = read_login_token(settings.secret_key, token)
        except TokenError as exc:
            return page(
                request, "message.html", 400, title="Sign-in link problem", message=f"{exc}.", login=True
            )
        if not is_invited(email):
            message = "this address is no longer invited."
            return page(request, "message.html", 400, title="Sign-in link problem", message=message)
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not current_email(request):
            return page(request, "landing.html", samples=sample_cards(geo))
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        # Every current trip counts, including deals already emailed.
        return page(
            request,
            "dashboard.html",
            active="dashboard",
            summaries=destination_summaries(engine, geo, seasons, user_id, today()),
            run_date=latest_run_date(engine, today()),
            pto_total=pto_total,
            pto_committed=pto_committed,
            saved=bool(saved),
        )

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: int, days: int = Form(30)):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            snooze(tracker, date.fromordinal(today().toordinal() + max(days, 1)))
        return redirect("/")

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: int):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            unsnooze(tracker)
        return redirect("/")

    # --- profile / onboarding --------------------------------------------------------------------

    def profile_page(request: Request, form: dict, errors: list[str], status: int = 200):
        return page(
            request,
            "profile.html",
            status,
            form=form,
            errors=errors,
            destinations=geo.destinations(),
            windows=row_count(form, "window"),
            trackers=row_count(form, "tracker"),
        )

    @app.get("/profile")
    def profile_form(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = current_email(request)
        if not email:
            return redirect("/")
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            profile = parse_profile(form_to_profile(form, email), geo)
        except ValueError as exc:
            errors = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            apply_profile(s, profile)
        return redirect("/?saved=1")

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, geo.destination(tracker.destination_code).name

    @app.get("/s/{token}")
    def confirm_action(request: Request, token: str):
        with session_scope(engine) as s:
            try:
                action, _, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
        return page(
            request,
            "action_confirm.html",
            action=action,
            label=ACTION_LABELS[action.kind],
            destination=destination,
        )

    @app.post("/s/{token}")
    def do_action(request: Request, token: str, price: str = Form("")):
        with session_scope(engine) as s:
            try:
                action, tracker, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
            amount = None
            if action.kind == "under":
                try:
                    amount = Decimal(price.replace("$", "").replace(",", "").strip())
                except InvalidOperation:
                    amount = None
            try:
                message = apply_action(s, tracker, action, today(), price=amount)
            except ValueError as exc:
                return page(
                    request,
                    "action_confirm.html",
                    400,
                    action=action,
                    label=ACTION_LABELS[action.kind],
                    destination=destination,
                    error=str(exc),
                )
        return page(request, "message.html", title=f"Done: {destination}", message=message)

    return app
```

- [ ] **Step 6: Write `ptopilot/web/templates/dashboard.html` (full new contents)**

```html
{% extends "base.html" %}
{% from "_components.html" import dest_card, pto_bar %}
{% block title %}Your trips · ptopilot{% endblock %}
{% block content %}
{% if saved %}<div class="panel notice" style="margin-bottom:14px;">Profile saved. The next morning scan will use it.</div>{% endif %}
<div class="page-head">
  <div>
    <h1>Your trips</h1>
    <p class="muted small">{% if run_date %}Prices from the {{ run_date | day }} scan.{% else %}Prices appear after the first daily scan (06:00 UTC).{% endif %}</p>
  </div>
</div>
<div class="stack">
  {{ pto_bar(pto_total, pto_committed) }}
  {% if summaries %}
  <div class="grid">
    {% for s in summaries %}
    <div>
      {{ dest_card(s, href="/trackers/%d" % s.tracker_id) }}
      {% if s.snoozed_until %}
      <form class="inline" method="post" action="/trackers/{{ s.tracker_id }}/unsnooze">
        <button class="link-btn small" type="submit" style="margin:8px 4px 0;">Unsnooze {{ s.name }}</button>
      </form>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="panel"><p style="margin:0;">No destinations yet. <a href="/profile">Add your bucket list to your profile.</a></p></div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_dashboard.py tests/web/test_profile_and_dashboard.py tests/web/test_hardening.py`

Expected: PASS. Verified tail: `13 passed, 1 warning in 6.42s`

- [ ] **Step 8: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `411 passed, 1 deselected, 1 warning in 63.33s (0:01:03)`; ruff reports nothing.

- [ ] **Step 9: Commit and push**

```bash
git add -A
git commit -m "feat(web): destination-grid dashboard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 10: Destination page

`GET /trackers/{id}`: colored hero with snooze controls, every date option from the latest scan, and the 30-day trend. Another user's or a missing tracker is a 404.

**Files:**
- Modify: `ptopilot/web/app.py`
- Create: `ptopilot/web/templates/destination.html`
- Create: `tests/web/test_destination_page.py`

**Interfaces:**
- Consumes: Task 5 `trend_chart`; Task 6 `trip_options`, `trend`, `typical_band`; Task 7 components.
- Produces: Route `GET /trackers/{tracker_id}`; `templates/destination.html`; Jinja filter `stops`.

- [ ] **Step 1: Write the failing test file `tests/web/test_destination_page.py`**

```python
"""The destination page: every date option from the latest scan, and the cheapest fare over 30 days."""

from datetime import timedelta

from sqlalchemy import select

from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, sign_in

CAMINO = {**PROFILE_FORM, "tracker_dest_0": "CAMINO_PORTUGUES", "tracker_min_0": "11", "tracker_max_0": "14"}


def setup(client, emailer, engine, form=PROFILE_FORM, email="nick@example.com") -> int:
    sign_in(client, emailer, engine, email)
    client.post("/profile", data=form)
    with session_scope(engine) as s:
        return s.scalar(select(Tracker.id).order_by(Tracker.id.desc()))


def test_lists_every_trip_from_the_latest_scan_cheapest_first(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    later = {"depart": TODAY.replace(day=12), "ret": TODAY.replace(day=21)}
    add_candidate(clean_engine, t, 700, run_date=TODAY, **later)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    add_baseline(clean_engine, 700)
    page = client.get(f"/trackers/{t}")
    assert page.status_code == 200
    text = page.text
    assert "<h1>Azores</h1>" in text and "7–10 days on the ground" in text
    assert text.index("$603") < text.index("$700")
    assert "Fri Mar 5 → Sun Mar 14" in text and "Tap Air Portugal · 1 stop" in text
    assert 'href="https://www.google.com/travel/flights/search?tfs=X"' in text and "View flights" in text
    assert "14% below typical" in text


def test_open_jaw_trips_say_where_they_fly_home_from(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine, CAMINO)
    add_candidate(clean_engine, t, 852, run_date=TODAY, dest="OPO", return_airport="SCQ")
    assert "into OPO · home from SCQ" in client.get(f"/trackers/{t}").text


def test_excluded_trips_stay_visible_but_dimmed(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 603, run_date=TODAY)
    with session_scope(clean_engine) as s:
        s.get(Candidate, c).state = "excluded"
    assert '<tr class="dimmed">' in client.get(f"/trackers/{t}").text


def test_trend_needs_a_few_scans_before_it_draws(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    page = client.get(f"/trackers/{t}").text
    assert "Price history fills in after a few daily scans" in page and "<svg" not in page
    for days_ago, price in [(1, 640), (2, 660)]:
        add_candidate(clean_engine, t, price, run_date=TODAY - timedelta(days=days_ago))
    page = client.get(f"/trackers/{t}").text
    assert 'class="trend"' in page and "Cheapest fare, last 30 days" in page
    assert "Tue Mar 2" in page and "Thu Mar 4" in page  # first and last scan days


def test_no_scan_yet_says_so(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert "First prices after the next daily scan" in client.get(f"/trackers/{t}").text


def test_snooze_from_the_destination_page(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert f'action="/trackers/{t}/snooze"' in client.get(f"/trackers/{t}").text
    client.post(f"/trackers/{t}/snooze", data={"days": "30"})
    assert f'action="/trackers/{t}/unsnooze"' in client.get(f"/trackers/{t}").text


def test_someone_elses_or_a_missing_tracker_is_not_found(client, emailer, clean_engine):
    theirs = setup(client, emailer, clean_engine, email="owner@example.com")
    client.post("/logout")
    setup(client, emailer, clean_engine, email="intruder@example.com")
    assert client.get(f"/trackers/{theirs}").status_code == 404
    assert client.get("/trackers/999999").status_code == 404


def test_signed_out_visitors_go_home(client):
    response = client.get("/trackers/1")
    assert (response.status_code, response.headers["location"]) == (303, "/")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_destination_page.py`

Expected: FAIL. Verified tail: `7 failed, 1 passed, 1 warning in 5.84s`

- [ ] **Step 3: Write `ptopilot/web/app.py` (full new contents)**

```python
"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo, palette
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import date_range, day, money, stops
from ptopilot.digest.select import latest_run_date
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count
from ptopilot.web.history import destination_summaries, trend, trip_options, typical_band
from ptopilot.web.samples import sample_cards
from ptopilot.web.viz import trend_chart

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
TEMPLATES.env.filters.update(money=money, day=day, dates=date_range, stops=stops)
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_COOLDOWN_S = 120  # at most one sign-in email per address per 2 minutes


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
    now: Callable[[], float] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    now = now or time.monotonic
    last_link_sent: dict[str, float] = {}  # per process; enough for one small instance
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def is_invited(email: str) -> bool:
        with session_scope(engine) as s:
            return s.scalar(select(Invite.email).where(Invite.email == email)) is not None

    def current_email(request: Request) -> str | None:
        """The signed-in email, as long as it is still invited; removing an invite ends the session."""
        email = request.session.get("email")
        if email and not is_invited(email):
            request.session.clear()
            return None
        return email

    def signed_in_user(s, request: Request) -> User | None:
        email = current_email(request)
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError):
        """Malformed form fields or URLs (e.g. a non-numeric id) get a page, not FastAPI's JSON."""
        message = "Something in that request didn't look right. Go back and try again."
        return page(request, "message.html", 400, title="That didn't work", message=message)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form():
        return redirect("/")  # the sign-in form lives on the landing page

    def send_link(email: str, link: str) -> None:
        if emailer is None:
            log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            return
        try:
            emailer.send(
                email,
                "Your ptopilot sign-in link",
                f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                f"Sign in to ptopilot (link works for 15 minutes): {link}",
            )
        except EmailError as exc:
            log.error("sign-in email not sent: %s", exc)

    @app.post("/login")
    def login(request: Request, background: BackgroundTasks, email: str = Form("")):
        email = email.strip().lower()
        cooled_down = now() - last_link_sent.get(email, float("-inf")) >= LOGIN_COOLDOWN_S
        if email and cooled_down and is_invited(email):
            last_link_sent[email] = now()
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            # Sent after the response, so invited and uninvited addresses answer equally fast.
            background.add_task(send_link, email, link)
        # Same answer either way, so the form doesn't reveal who is invited.
        return page(request, "login_sent.html")

    @app.get("/auth")
    def auth(request: Request, token: str = ""):
        try:
            email = read_login_token(settings.secret_key, token)
        except TokenError as exc:
            return page(
                request, "message.html", 400, title="Sign-in link problem", message=f"{exc}.", login=True
            )
        if not is_invited(email):
            message = "this address is no longer invited."
            return page(request, "message.html", 400, title="Sign-in link problem", message=message)
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not current_email(request):
            return page(request, "landing.html", samples=sample_cards(geo))
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        # Every current trip counts, including deals already emailed.
        return page(
            request,
            "dashboard.html",
            active="dashboard",
            summaries=destination_summaries(engine, geo, seasons, user_id, today()),
            run_date=latest_run_date(engine, today()),
            pto_total=pto_total,
            pto_committed=pto_committed,
            saved=bool(saved),
        )

    @app.get("/trackers/{tracker_id}")
    def destination_page(request: Request, tracker_id: int):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:  # someone else's or missing: same answer, so ids reveal nothing
                return page(request, "message.html", 404, title="Not found", message="No such destination.")
            code, stay = tracker.destination_code, (tracker.min_stay_days, tracker.max_stay_days)
            snoozed = tracker.snoozed_until
        if snoozed is not None and snoozed < today():
            snoozed = None
        dest = geo.destination(code)
        options = trip_options(engine, geo, seasons, tracker_id, today())
        band = typical_band(options)
        return page(
            request,
            "destination.html",
            tracker_id=tracker_id,
            dest=dest,
            palette=palette(dest),
            stay=stay,
            snoozed_until=snoozed,
            options=options,
            run_date=latest_run_date(engine, today()),
            band=band,
            chart=trend_chart(trend(engine, tracker_id, today()), band, palette(dest)),
        )

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: int, days: int = Form(30)):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            snooze(tracker, date.fromordinal(today().toordinal() + max(days, 1)))
        return redirect("/")

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: int):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            unsnooze(tracker)
        return redirect("/")

    # --- profile / onboarding --------------------------------------------------------------------

    def profile_page(request: Request, form: dict, errors: list[str], status: int = 200):
        return page(
            request,
            "profile.html",
            status,
            form=form,
            errors=errors,
            destinations=geo.destinations(),
            windows=row_count(form, "window"),
            trackers=row_count(form, "tracker"),
        )

    @app.get("/profile")
    def profile_form(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = current_email(request)
        if not email:
            return redirect("/")
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            profile = parse_profile(form_to_profile(form, email), geo)
        except ValueError as exc:
            errors = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            apply_profile(s, profile)
        return redirect("/?saved=1")

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, geo.destination(tracker.destination_code).name

    @app.get("/s/{token}")
    def confirm_action(request: Request, token: str):
        with session_scope(engine) as s:
            try:
                action, _, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
        return page(
            request,
            "action_confirm.html",
            action=action,
            label=ACTION_LABELS[action.kind],
            destination=destination,
        )

    @app.post("/s/{token}")
    def do_action(request: Request, token: str, price: str = Form("")):
        with session_scope(engine) as s:
            try:
                action, tracker, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
            amount = None
            if action.kind == "under":
                try:
                    amount = Decimal(price.replace("$", "").replace(",", "").strip())
                except InvalidOperation:
                    amount = None
            try:
                message = apply_action(s, tracker, action, today(), price=amount)
            except ValueError as exc:
                return page(
                    request,
                    "action_confirm.html",
                    400,
                    action=action,
                    label=ACTION_LABELS[action.kind],
                    destination=destination,
                    error=str(exc),
                )
        return page(request, "message.html", title=f"Done: {destination}", message=message)

    return app
```

- [ ] **Step 4: Write `ptopilot/web/templates/destination.html`**

```html
{% extends "base.html" %}
{% from "_components.html" import dest_style, price_bar, vs_typical, season %}
{% block title %}{{ dest.name }} · ptopilot{% endblock %}
{% block content %}
<div class="hero dest-head" style="{{ dest_style(palette) }}">
  <div class="eyebrow">{{ stay[0] }}–{{ stay[1] }} days on the ground</div>
  <h1>{{ dest.name }}</h1>
  <div class="hero-actions">
    {% if snoozed_until %}
    <span class="tag">Snoozed until {{ snoozed_until | day }}</span>
    <form class="inline" method="post" action="/trackers/{{ tracker_id }}/unsnooze"><button class="btn btn-ghost btn-sm" type="submit">Unsnooze</button></form>
    {% else %}
    <form class="inline" method="post" action="/trackers/{{ tracker_id }}/snooze"><input type="hidden" name="days" value="30"><button class="btn btn-ghost btn-sm" type="submit">Snooze 30 days</button></form>
    {% endif %}
    <a class="btn btn-ghost btn-sm" href="/">All trips</a>
  </div>
</div>

<div class="stack" style="{{ dest_style(palette) }}">
  <section class="panel">
    <h2>Date options</h2>
    {% if options %}
    <p class="muted small">From the {{ run_date | day }} scan, cheapest first. Prices are per person, economy, and change fast.</p>
    <table class="trips">
      <thead><tr><th>Dates</th><th>Price</th><th>vs typical</th><th>PTO</th><th>Flights</th></tr></thead>
      <tbody>
      {% for o in options %}
      <tr{% if o.dimmed %} class="dimmed"{% endif %}>
        <td><b>{{ o.depart_date | day }} → {{ o.return_date | day }}</b>
          <div class="meta">{{ o.origin }} → {% if o.open_jaw %}into {{ o.dest_airport }} · home from {{ o.return_airport }}{% else %}{{ o.dest_airport }}{% endif %}{% if o.evening_departure %} · leave after work{% endif %}</div>
          <div class="meta">{{ season(o) }}</div></td>
        <td><span class="price" style="font-size:18px;">{{ o.price | money(o.currency) }}</span><div>{{ vs_typical(o) }}</div></td>
        <td class="bar-cell">{{ price_bar(o.bar) }}</td>
        <td class="num"><b>{{ o.pto_cost }}</b> <span class="meta">for {{ o.days_away }} days</span></td>
        <td class="flights">
          {% if o.carrier %}<div class="meta">{{ o.carrier }} · {{ o.stops | stops }}{% if o.overnight %} · overnight{% endif %}</div>{% endif %}
          {% if o.deep_link %}<a class="btn btn-sm" href="{{ o.deep_link }}" rel="noopener" target="_blank">View flights</a>{% endif %}
          {% if o.dimmed %}<span class="tag">{{ o.state }}</span>{% endif %}
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="muted" style="margin:0;">First prices after the next daily scan.</p>
    {% endif %}
  </section>

  <section class="panel trend-panel">
    <h2>Cheapest fare, last 30 days</h2>
    {% if chart %}
    <div class="trend-axis"><span>{{ chart.high | money }}</span>{% if band %}<span>shaded: typical {{ band[0] | money }}–{{ band[1] | money }}</span>{% endif %}</div>
    {{ chart.svg }}
    <div class="trend-axis"><span>{{ chart.first | day }} · low {{ chart.low | money }}</span><span>{{ chart.last | day }}</span></div>
    {% else %}
    <p class="muted" style="margin:0;">Price history fills in after a few daily scans.</p>
    {% endif %}
  </section>
</div>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_destination_page.py`

Expected: PASS. Verified tail: `8 passed, 1 warning in 5.56s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `419 passed, 1 deselected, 1 warning in 68.81s (0:01:08)`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(web): destination page with trip table and price trend

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 11: Profile page

The profile form in grouped panels built from the `field` macro, with the new Ideal trip field.

**Files:**
- Modify: `ptopilot/web/app.py`
- Modify: `ptopilot/web/templates/profile.html`
- Create: `tests/web/test_profile_page.py`

**Interfaces:**
- Consumes: Task 2 form key `ideal_trip_days`; Task 7 `field`.
- Produces: `templates/profile.html`.

- [ ] **Step 1: Write the failing test file `tests/web/test_profile_page.py`**

```python
"""The profile form: grouped sections and the preferred trip length."""

from sqlalchemy import select

from ptopilot.db.models import User
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, sign_in


def test_profile_is_grouped_into_sections(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    page = client.get("/profile").text
    sections = ("Home and calendar", "PTO and trip length", "Travel windows", "Bucket list", "Preferences")
    assert all(f"<h2>{heading}</h2>" in page for heading in sections)
    assert 'name="ideal_trip_days"' in page and 'aria-current="page"' in page


def test_saving_an_ideal_length_stores_it_and_shows_it_again(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "10"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User.ideal_trip_days)) == 10
    assert 'name="ideal_trip_days" type="text" value="10"' in client.get("/profile").text


def test_clearing_the_ideal_length_removes_the_preference(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "10"})
    client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": ""})
    with session_scope(clean_engine) as s:
        assert s.scalar(select(User.ideal_trip_days)) is None


def test_an_ideal_outside_the_trip_range_is_explained_on_the_page(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    response = client.post("/profile", data={**PROFILE_FORM, "ideal_trip_days": "30"})
    assert response.status_code == 400
    assert "ideal_trip_days: 30 is outside your trip length 7..16" in response.text
    assert 'class="panel notice-error"' in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_profile_page.py`

Expected: FAIL. Verified tail: `3 failed, 1 passed, 1 warning in 3.28s`

- [ ] **Step 3: Write `ptopilot/web/app.py` (full new contents)**

```python
"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo, palette
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import date_range, day, money, stops
from ptopilot.digest.select import latest_run_date
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count
from ptopilot.web.history import destination_summaries, trend, trip_options, typical_band
from ptopilot.web.samples import sample_cards
from ptopilot.web.viz import trend_chart

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
TEMPLATES.env.filters.update(money=money, day=day, dates=date_range, stops=stops)
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_COOLDOWN_S = 120  # at most one sign-in email per address per 2 minutes


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
    now: Callable[[], float] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    now = now or time.monotonic
    last_link_sent: dict[str, float] = {}  # per process; enough for one small instance
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="ptopilot_session",
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.app_base_url.startswith("https://"),
    )

    def page(request: Request, name: str, status: int = 200, **context):
        context = {"signed_in": request.session.get("email"), **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def is_invited(email: str) -> bool:
        with session_scope(engine) as s:
            return s.scalar(select(Invite.email).where(Invite.email == email)) is not None

    def current_email(request: Request) -> str | None:
        """The signed-in email, as long as it is still invited; removing an invite ends the session."""
        email = request.session.get("email")
        if email and not is_invited(email):
            request.session.clear()
            return None
        return email

    def signed_in_user(s, request: Request) -> User | None:
        email = current_email(request)
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError):
        """Malformed form fields or URLs (e.g. a non-numeric id) get a page, not FastAPI's JSON."""
        message = "Something in that request didn't look right. Go back and try again."
        return page(request, "message.html", 400, title="That didn't work", message=message)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    # --- sign-in ---------------------------------------------------------------------------------

    @app.get("/login")
    def login_form():
        return redirect("/")  # the sign-in form lives on the landing page

    def send_link(email: str, link: str) -> None:
        if emailer is None:
            log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            return
        try:
            emailer.send(
                email,
                "Your ptopilot sign-in link",
                f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                f"Sign in to ptopilot (link works for 15 minutes): {link}",
            )
        except EmailError as exc:
            log.error("sign-in email not sent: %s", exc)

    @app.post("/login")
    def login(request: Request, background: BackgroundTasks, email: str = Form("")):
        email = email.strip().lower()
        cooled_down = now() - last_link_sent.get(email, float("-inf")) >= LOGIN_COOLDOWN_S
        if email and cooled_down and is_invited(email):
            last_link_sent[email] = now()
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            # Sent after the response, so invited and uninvited addresses answer equally fast.
            background.add_task(send_link, email, link)
        # Same answer either way, so the form doesn't reveal who is invited.
        return page(request, "login_sent.html")

    @app.get("/auth")
    def auth(request: Request, token: str = ""):
        try:
            email = read_login_token(settings.secret_key, token)
        except TokenError as exc:
            return page(
                request, "message.html", 400, title="Sign-in link problem", message=f"{exc}.", login=True
            )
        if not is_invited(email):
            message = "this address is no longer invited."
            return page(request, "message.html", 400, title="Sign-in link problem", message=message)
        request.session.clear()
        request.session["email"] = email
        return redirect("/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/")

    # --- dashboard -------------------------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request, saved: int = 0):
        if not current_email(request):
            return page(request, "landing.html", samples=sample_cards(geo))
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        # Every current trip counts, including deals already emailed.
        return page(
            request,
            "dashboard.html",
            active="dashboard",
            summaries=destination_summaries(engine, geo, seasons, user_id, today()),
            run_date=latest_run_date(engine, today()),
            pto_total=pto_total,
            pto_committed=pto_committed,
            saved=bool(saved),
        )

    @app.get("/trackers/{tracker_id}")
    def destination_page(request: Request, tracker_id: int):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:  # someone else's or missing: same answer, so ids reveal nothing
                return page(request, "message.html", 404, title="Not found", message="No such destination.")
            code, stay = tracker.destination_code, (tracker.min_stay_days, tracker.max_stay_days)
            snoozed = tracker.snoozed_until
        if snoozed is not None and snoozed < today():
            snoozed = None
        dest = geo.destination(code)
        options = trip_options(engine, geo, seasons, tracker_id, today())
        band = typical_band(options)
        return page(
            request,
            "destination.html",
            tracker_id=tracker_id,
            dest=dest,
            palette=palette(dest),
            stay=stay,
            snoozed_until=snoozed,
            options=options,
            run_date=latest_run_date(engine, today()),
            band=band,
            chart=trend_chart(trend(engine, tracker_id, today()), band, palette(dest)),
        )

    @app.post("/trackers/{tracker_id}/snooze")
    def snooze_tracker(request: Request, tracker_id: int, days: int = Form(30)):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            snooze(tracker, date.fromordinal(today().toordinal() + max(days, 1)))
        return redirect("/")

    @app.post("/trackers/{tracker_id}/unsnooze")
    def unsnooze_tracker(request: Request, tracker_id: int):
        with session_scope(engine) as s:
            tracker = owned_tracker(s, request, tracker_id)
            if tracker is None:
                return page(request, "message.html", 404, title="Not found", message="No such tracker.")
            unsnooze(tracker)
        return redirect("/")

    # --- profile / onboarding --------------------------------------------------------------------

    def profile_page(request: Request, form: dict, errors: list[str], status: int = 200):
        return page(
            request,
            "profile.html",
            status,
            active="profile",
            form=form,
            errors=errors,
            destinations=geo.destinations(),
            windows=row_count(form, "window"),
            trackers=row_count(form, "tracker"),
        )

    @app.get("/profile")
    def profile_form(request: Request):
        if not current_email(request):
            return redirect("/")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = current_email(request)
        if not email:
            return redirect("/")
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            profile = parse_profile(form_to_profile(form, email), geo)
        except ValueError as exc:
            errors = [line.removeprefix("  - ") for line in str(exc).splitlines()[1:]]
            return profile_page(request, form, errors, 400)
        with session_scope(engine) as s:
            apply_profile(s, profile)
        return redirect("/?saved=1")

    # --- snooze links from the digest ------------------------------------------------------------

    def action_context(s, token: str):
        action = read_action_token(settings.secret_key, token)
        tracker = s.get(Tracker, action.tracker_id)
        if tracker is None:
            raise TokenError("this tracker no longer exists")
        return action, tracker, geo.destination(tracker.destination_code).name

    @app.get("/s/{token}")
    def confirm_action(request: Request, token: str):
        with session_scope(engine) as s:
            try:
                action, _, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
        return page(
            request,
            "action_confirm.html",
            action=action,
            label=ACTION_LABELS[action.kind],
            destination=destination,
        )

    @app.post("/s/{token}")
    def do_action(request: Request, token: str, price: str = Form("")):
        with session_scope(engine) as s:
            try:
                action, tracker, destination = action_context(s, token)
            except TokenError as exc:
                return page(request, "message.html", 400, title="Link problem", message=f"{exc}.")
            amount = None
            if action.kind == "under":
                try:
                    amount = Decimal(price.replace("$", "").replace(",", "").strip())
                except InvalidOperation:
                    amount = None
            try:
                message = apply_action(s, tracker, action, today(), price=amount)
            except ValueError as exc:
                return page(
                    request,
                    "action_confirm.html",
                    400,
                    action=action,
                    label=ACTION_LABELS[action.kind],
                    destination=destination,
                    error=str(exc),
                )
        return page(request, "message.html", title=f"Done: {destination}", message=message)

    return app
```

- [ ] **Step 4: Write `ptopilot/web/templates/profile.html` (full new contents)**

```html
{% extends "base.html" %}
{% from "_components.html" import field %}
{% block title %}Profile · ptopilot{% endblock %}
{% block content %}
<div class="page-head">
  <div>
    <h1>Your travel profile</h1>
    <p class="muted small">Changes apply from the next morning scan.</p>
  </div>
</div>
{% if errors %}
<div class="panel notice-error" style="margin-bottom:14px;">
  <p class="error" style="margin-bottom:6px;"><b>Please fix {{ errors | length }} thing{{ "s" if errors | length != 1 }}:</b></p>
  <ul class="error" style="margin:0;padding-left:20px;">{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
</div>
{% endif %}
<form method="post" action="/profile" class="stack">
  <section class="panel">
    <h2>Home and calendar</h2>
    <div class="fields">
      {{ field("home_airport", "Home airport", form.home_airport, attrs='placeholder="JFK" required') }}
      {{ field("nearby_airports", "Also fly from", form.nearby_airports, attrs='placeholder="EWR, PHL"') }}
      {{ field("country", "Country", form.country, attrs='maxlength="2"') }}
      {{ field("holiday_calendar", "Holiday calendar", form.holiday_calendar, attrs='placeholder="US or GB-ENG"') }}
    </div>
    {{ field("ignored_holidays", "Holidays your office works", form.ignored_holidays, hint="Comma-separated, e.g. Columbus Day, Veterans Day") }}
    {{ field("extra_days_off", "Company days off", form.extra_days_off, hint="YYYY-MM-DD, comma-separated") }}
  </section>

  <section class="panel">
    <h2>PTO and trip length</h2>
    <div class="fields">
      {{ field("pto_days_total", "PTO days this year", form.pto_days_total, attrs='inputmode="numeric" required') }}
      {{ field("pto_committed", "Already committed", form.pto_committed, attrs='inputmode="numeric"') }}
      {{ field("min_trip_days", "Shortest trip", form.min_trip_days, hint="Days away from home", attrs='inputmode="numeric"') }}
      {{ field("max_trip_days", "Longest trip", form.max_trip_days, hint="Days away from home", attrs='inputmode="numeric" required') }}
      {{ field("ideal_trip_days", "Ideal trip", form.ideal_trip_days, hint="Optional. Trips near it are priced first.", attrs='inputmode="numeric" placeholder="no preference"') }}
    </div>
  </section>

  <section class="panel">
    <h2>Travel windows</h2>
    {% for i in range(windows) %}
    <div class="fields">
      {{ field("window_start_%d" % i, "From", form["window_start_%d" % i], type="date") }}
      {{ field("window_end_%d" % i, "To", form["window_end_%d" % i], type="date") }}
    </div>
    {% endfor %}
    <p class="muted small" style="margin:0;">Leave a row blank to remove it.</p>
  </section>

  <section class="panel">
    <h2>Bucket list</h2>
    <p class="muted small">Days on the ground, after travel days. Priority 1 is checked first.</p>
    {% for i in range(trackers) %}
    <div class="row-fields">
      <label class="field"><span>Destination</span>
        <select id="tracker_dest_{{ i }}" name="tracker_dest_{{ i }}">
          <option value=""></option>
          {% for d in destinations %}<option value="{{ d.code }}" {{ "selected" if form['tracker_dest_%d' % i] == d.code }}>{{ d.name }}</option>{% endfor %}
        </select></label>
      {{ field("tracker_min_%d" % i, "Min days", form["tracker_min_%d" % i], attrs='inputmode="numeric"') }}
      {{ field("tracker_max_%d" % i, "Max days", form["tracker_max_%d" % i], attrs='inputmode="numeric"') }}
      {{ field("tracker_priority_%d" % i, "Priority", form["tracker_priority_%d" % i], attrs='inputmode="numeric"') }}
      {{ field("tracker_price_%d" % i, "Max price", form["tracker_price_%d" % i], attrs='inputmode="numeric" placeholder="any"') }}
    </div>
    {% endfor %}
    <p class="muted small" style="margin:0;">Missing a destination? It has to be added to the app's data first.</p>
  </section>

  <section class="panel">
    <h2>Preferences</h2>
    <div class="fields">
      <label class="field"><span>Weather</span>
        <select id="weather_tolerance" name="weather_tolerance">
          {% for value, text in [("strict", "Only the best months"), ("normal", "Skip bad-weather months"), ("relaxed", "Any month")] %}
          <option value="{{ value }}" {{ "selected" if form.weather_tolerance == value }}>{{ text }}</option>
          {% endfor %}
        </select></label>
      {{ field("max_stops_short", "Max stops (short haul)", form.max_stops_short, attrs='inputmode="numeric"') }}
      {{ field("max_stops_long", "Max stops (long haul)", form.max_stops_long, attrs='inputmode="numeric"') }}
      {{ field("friday_evening_min_time", "Leave-after-work time", form.friday_evening_min_time, type="time") }}
    </div>
    <label class="check"><input type="checkbox" name="allow_overnight_layover" {{ "checked" if form.allow_overnight_layover }}> Overnight layovers are OK</label>
    <label class="check"><input type="checkbox" name="friday_evening_departure" {{ "checked" if form.friday_evening_departure }}> I can leave after work on my last workday</label>
  </section>

  <div class="form-actions"><button class="btn" type="submit">Save profile</button><a class="muted small" href="/">Cancel</a></div>
</form>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/web/test_profile_page.py`

Expected: PASS. Verified tail: `4 passed, 1 warning in 3.07s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `423 passed, 1 deselected, 1 warning in 65.17s (0:01:05)`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(web): restyled profile with ideal trip length

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 12: Digest email redesign

The top deal as a full card in its destination color with a table-cell price bar; other deals as compact rows linking to their destination pages; a preheader; an Outlook width wrapper; quiet-digest wording that knows whether deals were held back.

**Files:**
- Modify: `ptopilot/core/geo.py`
- Modify: `ptopilot/digest/__main__.py`
- Modify: `ptopilot/digest/render.py`
- Modify: `ptopilot/digest/select.py`
- Modify: `ptopilot/digest/send.py`
- Modify: `ptopilot/digest/templates/digest.html.j2`
- Modify: `ptopilot/digest/templates/digest.txt.j2`
- Create: `tests/digest/test_digest_design.py`
- Modify: `tests/digest/test_render.py`

**Interfaces:**
- Consumes: Task 1 `palette`, `NEUTRAL_PALETTE`; Task 5 `bar_geometry`, `BarGeometry`; Task 10 route `/trackers/{id}`.
- Produces: `DealCard.palette`, `DealCard.sigma`, `TrackerRow.palette` (all defaulted); `Digest.held_back: int = 0`; `render(..., base_url=None)`; `deliver(..., base_url=None)`; `digest.render.bar_cells(bar) -> list[tuple[float, str]]`; `ptopilot.core.geo.NEUTRAL_PALETTE`.

> `tests/digest/test_render.py` changes one fragment: the lead card's button now reads "View flights", matching the site.

- [ ] **Step 1: Write the failing test file `tests/digest/test_digest_design.py`**

```python
"""The V2 digest: a lead deal card, compact rows for the rest, and email-safe structure."""

from datetime import timedelta

from ptopilot.core.geo import Palette
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest.render import bar_cells, render
from ptopilot.digest.select import Digest, build_digests
from ptopilot.web.viz import BarGeometry
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user
from tests.digest.test_render import NOW, ROW, card

TEAL = Palette("#0e7490", "#c3dde3")
GREEN = Palette("#15803d", "#c5dfcf")


def two_deals(**digest_fields) -> Digest:
    lead = card(palette=TEAL, sigma=50.0, typical=700)
    other = card(candidate_id=2, tracker_id=2, destination="Madeira", palette=GREEN, price=828, go_now=60)
    return Digest(1, "nick@example.com", RUN, [lead, other], [ROW], **digest_fields)


def test_lead_deal_gets_the_full_card_in_its_color():
    _, html, _ = render(two_deals(), now=NOW)
    assert "Best this week" in html and "background:#0e7490" in html
    assert html.count("View flights") == 1  # only the lead card has the button


def test_lead_card_draws_the_price_bar_from_table_cells():
    _, html, _ = render(two_deals(), now=NOW)
    assert 'bgcolor="#c3dde3"' in html and 'bgcolor="#0e7490"' in html


def test_other_deals_are_compact_rows_linking_to_the_site_when_it_is_configured():
    _, html, _ = render(two_deals(), now=NOW, base_url="https://ptopilot.example")
    assert 'href="https://ptopilot.example/trackers/2"' in html and "Madeira" in html and "$828" in html
    _, html, _ = render(two_deals(), now=NOW)
    assert "/trackers/2" not in html and 'href="https://www.google.com/travel/flights' in html


def test_preheader_and_outlook_wrapper():
    _, html, _ = render(two_deals(), now=NOW)
    assert "Azores $603 (14% below typical) + 1 more" in html.split("<table")[0]  # hidden, before the layout
    assert "<!--[if mso]>" in html and 'width="600"' in html


def test_quiet_digest_wording_depends_on_whether_deals_went_out_before():
    _, html, text = render(Digest(1, "nick@example.com", RUN, [], [ROW], held_back=2), now=NOW)
    assert "No new deals since your last digest" in html and "No new deals since your last digest" in text
    _, html, _ = render(Digest(1, "nick@example.com", RUN, [], [ROW]), now=NOW)
    assert "Nothing below typical yet" in html


def test_text_version_keeps_the_same_order():
    _, _, text = render(two_deals(), now=NOW)
    assert text.index("Azores") < text.index("Madeira") < text.index("Your trackers")


def test_bar_cells_cover_the_track_once():
    cells = bar_cells(BarGeometry(dot=24.0, band_start=33.3, band_end=66.7))
    assert [kind for _, kind in cells] == ["track", "dot", "track", "band", "track"]
    assert abs(sum(width for width, _ in cells) - 100) < 0.5
    inside = bar_cells(BarGeometry(dot=50.0, band_start=33.3, band_end=66.7))
    assert [kind for _, kind in inside] == ["track", "band", "dot", "band", "track"]


def test_selection_counts_deals_held_back_as_already_sent(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    old = add_candidate(clean_engine, t, 600, run_date=RUN - timedelta(days=3))
    with session_scope(clean_engine) as s:
        item = {
            "candidate_id": old,
            "tracker_id": t,
            "route_query_id": 1,
            "evening_departure": True,
            "price": 600,
        }
        s.add(DigestSend(user_id=uid, items=[item]))
    add_candidate(clean_engine, t, 590, run_date=RUN)
    (d,) = build_digests(clean_engine, load_geo(), load_seasons(), RUN)
    assert d.deals == [] and d.held_back == 1


def test_selection_gives_cards_their_destination_palette_and_spread(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_baseline(clean_engine, 700)
    (d,) = build_digests(clean_engine, load_geo(), load_seasons(), RUN)
    assert d.deals[0].palette.color == "#0e7490" and d.deals[0].sigma == 50.0
    assert d.trackers[0].palette.color == "#0e7490"
```

- [ ] **Step 2: Update the test file `tests/digest/test_render.py` (full new contents)**

```python
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ptopilot.digest.render import checked_ago, clock, duration, money, render, subject
from ptopilot.digest.select import DealCard, Digest, TrackerRow

NOW = datetime(2027, 3, 4, 12, 0, tzinfo=UTC)


def card(**overrides) -> DealCard:
    fields = dict(
        candidate_id=1,
        tracker_id=1,
        route_query_id=1,
        destination="Azores",
        origin="JFK",
        dest_airport="PDL",
        return_airport="PDL",
        depart_date=date(2027, 3, 5),
        return_date=date(2027, 3, 14),
        evening_departure=True,
        price=Decimal(603),
        currency="USD",
        typical=Decimal(870),
        deal_level="great",
        go_now=84,
        confidence="normal",
        verified=True,
        pto_cost=5,
        days_away=10,
        days_off=(),
        season_rating="shoulder",
        weather_note="Mild (~16°C) but rainy",
        carrier="Tap Air Portugal",
        stops=1,
        duration_min=600,
        outbound_departure=datetime(2027, 3, 5, 22, 0),
        flight_numbers=("TP 202",),
        deep_link="https://www.google.com/travel/flights/search?tfs=X&curr=USD",
        observed_at=NOW - timedelta(hours=9),
    )  # noqa: C408
    return DealCard(**(fields | overrides))


ROW = TrackerRow(1, "Azores", Decimal(603), Decimal(870), "down", "May", None)


def digest(*deals) -> Digest:
    return Digest(1, "nick@example.com", date(2027, 3, 4), list(deals), [ROW])


def test_helpers():
    assert money(Decimal("1239.4")) == "$1,239"
    assert money(None) == "—"
    assert duration(1195) == "19h 55m"
    assert clock(datetime(2027, 3, 5, 18, 25)) == "6:25pm" and clock(datetime(2027, 3, 5, 0, 5)) == "12:05am"
    assert checked_ago(NOW - timedelta(minutes=10), NOW) == "checked under an hour ago"
    assert checked_ago(NOW - timedelta(hours=9), NOW) == "checked 9 hours ago"
    assert checked_ago(NOW - timedelta(days=3), NOW) == "checked 3 days ago"


def test_subject_leads_with_the_top_deal():
    assert (
        subject(digest(card(), card(candidate_id=2))) == "ptopilot: Azores $603 (31% below typical) + 1 more"
    )
    assert subject(digest()) == "ptopilot: a quiet week for your trips"


def test_html_card_contents():
    _, html, _ = render(digest(card(days_off=("Memorial Day",))), now=NOW)
    for fragment in (
        "Azores", "Great deal", "Go-now 84", "Fri Mar 5 → Sun Mar 14", "leave after work", "$603", "~$870",
        "31% below", "5 PTO days", "Memorial Day gives you a free day", "1 stop", "10h 00m out",
        "departs 10:00pm", "TP 202", "(outbound flight)", "checked 9 hours ago", "View flights",
        "tfs=X&amp;curr=USD", "Your trackers", "↓",
    ):  # fmt: skip
        assert fragment in html, fragment


def test_open_jaw_and_low_confidence_wording():
    _, html, text = render(
        digest(card(dest_airport="OPO", return_airport="SCQ", confidence="low", verified=False)), now=NOW
    )
    assert "JFK → OPO, home from SCQ" in html and "both flights" in html
    assert "Cached price, not yet confirmed live" in html and "still being learned" in html
    assert "JFK -> OPO, home from SCQ" in text and "both flights" in text


def test_html_escapes_but_text_does_not():
    _, html, text = render(digest(card(carrier="Trains & <Planes>")), now=NOW)
    assert "Trains &amp; &lt;Planes&gt;" in html
    assert "Trains & <Planes>" in text
    assert "&amp;" not in text


def test_quiet_digest_still_shows_trackers():
    subj, html, text = render(digest(), now=NOW)
    assert "A quiet week" in html and "Your trackers" in html
    assert "Azores: best $603, typical $870" in text


def test_snooze_links_appear_under_each_card_when_provided():
    def links(c):
        return [("Not this trip", f"https://app.example/s/tok{c.candidate_id}")]

    _, html, text = render(digest(card()), now=NOW, links=links)
    assert 'href="https://app.example/s/tok1"' in html and "Not this trip" in html
    assert "Not this trip: https://app.example/s/tok1" in text
    _, html, _ = render(digest(card()), now=NOW)
    assert "/s/" not in html
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/digest/test_digest_design.py tests/digest/test_render.py`

Expected: FAIL. Verified tail: `1 error in 0.45s`

- [ ] **Step 4: Write `ptopilot/core/geo.py` (full new contents)**

```python
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
```

- [ ] **Step 5: Write `ptopilot/digest/__main__.py` (full new contents)**

```python
"""CLI: python -m ptopilot.digest send [--date D] [--min-level good|great|none] [--preview DIR]

--preview writes each digest to DIR as HTML + text instead of emailing it (no database writes), which
is the way to tune the layout. --min-level none includes trips that aren't deals yet. Exits 1 if any
email failed to send, 2 if sending is requested but no emailer is configured.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.session import make_engine
from ptopilot.digest.select import LEVELS, build_digests
from ptopilot.digest.send import deliver
from ptopilot.links import action_links
from ptopilot.notify.email import ResendEmailer
from ptopilot.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.digest")
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="build and send (or preview) the digests")
    send.add_argument(
        "--date", type=date.fromisoformat, default=None, help="as of this date (default: today, UTC)"
    )
    send.add_argument(
        "--min-level", choices=list(LEVELS), default="good", help="lowest deal level to include"
    )
    send.add_argument(
        "--preview", type=Path, default=None, help="write digests to this folder instead of sending"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if args.preview is None and not settings.resend_api_key:
        print(
            "RESEND_API_KEY is not set; use --preview DIR to write digests to files instead", file=sys.stderr
        )
        return 2
    today = args.date or datetime.now(UTC).date()
    engine = make_engine(settings.database_url)
    digests = build_digests(engine, load_geo(), load_seasons(), today, args.min_level)
    if args.min_level == "none" and args.preview is None:
        # Tuning digests include non-deals: send them to the admin only, never to other travelers.
        if not settings.admin_email:
            print("--min-level none sends only to ADMIN_EMAIL, which is not set", file=sys.stderr)
            return 2
        digests = [d for d in digests if d.email.lower() == settings.admin_email.strip().lower()]
    emailer = None if args.preview else ResendEmailer(settings.resend_api_key, settings.email_from)
    links = None
    if settings.app_base_url and settings.secret_key:  # snooze buttons need the web app and the shared key

        def links(card):
            return action_links(
                settings.app_base_url,
                settings.secret_key,
                card.tracker_id,
                card.depart_date,
                card.return_date,
            )

    counts = deliver(
        engine,
        digests,
        today,
        emailer=emailer,
        preview_dir=args.preview,
        links=links,
        base_url=settings.app_base_url or None,
    )
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to send"
    print(f"digests for {today}: {len(digests)} built; {summary}")
    if args.preview:
        print(f"preview written to {args.preview.resolve()}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Write `ptopilot/digest/render.py` (full new contents)**

```python
"""Render a Digest as an email: subject, HTML (inline styles, table layout for mail clients), plain text."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ptopilot.digest.select import DealCard, Digest
from ptopilot.web.viz import BarGeometry, bar_geometry

LinkBuilder = Callable[[DealCard], list[tuple[str, str]]]

LEVEL_LABEL = {"great": "Great deal", "good": "Good deal", "none": "Tracking"}
TREND_ARROW = {"down": "↓", "up": "↑", "flat": "→", "new": "·"}


def money(value: Decimal | float | None, currency: str = "USD") -> str:
    if value is None:
        return "—"
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.0f}"


def day(d) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def date_range(start, end) -> str:
    """Mar 5–15, Feb 27–Mar 14, or Dec 28, 2027–Jan 4, 2028."""
    if start.year != end.year:
        return f"{start:%b} {start.day}, {start.year}–{end:%b} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start:%b} {start.day}–{end:%b} {end.day}"
    return f"{start:%b} {start.day}–{end.day}"


def duration(minutes: int | None) -> str:
    if not minutes:
        return ""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def clock(dt) -> str:
    if dt is None:
        return ""
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"


def checked_ago(observed: datetime | None, now: datetime) -> str:
    if observed is None:
        return ""
    hours = int((now - observed).total_seconds() // 3600)
    if hours < 1:
        return "checked under an hour ago"
    if hours < 48:
        return f"checked {hours} hour{'s' if hours != 1 else ''} ago"
    return f"checked {hours // 24} days ago"


def stops(n: int | None) -> str:
    if n is None:
        return ""
    return "nonstop" if n == 0 else f"{n} stop{'s' if n != 1 else ''}"


_env = Environment(
    loader=PackageLoader("ptopilot.digest", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False, default_for_string=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters.update(money=money, day=day, dates=date_range, duration=duration, clock=clock, stops=stops)


BAR_DOT_WIDTH = 3.0  # percent of the bar


def bar_cells(bar: BarGeometry) -> list[tuple[float, str]]:
    """The price bar as table cells for email: (width %, "track" | "band" | "dot"), left to right."""
    d0 = min(max(bar.dot - BAR_DOT_WIDTH / 2, 0.0), 100 - BAR_DOT_WIDTH)
    d1 = d0 + BAR_DOT_WIDTH
    edges = sorted({0.0, bar.band_start, bar.band_end, d0, d1, 100.0})
    cells: list[tuple[float, str]] = []
    for lo, hi in zip(edges, edges[1:], strict=False):
        mid = (lo + hi) / 2
        kind = "dot" if d0 <= mid <= d1 else "band" if bar.band_start <= mid <= bar.band_end else "track"
        if cells and cells[-1][1] == kind:
            cells[-1] = (round(cells[-1][0] + hi - lo, 1), kind)
        else:
            cells.append((round(hi - lo, 1), kind))
    return cells


def subject(digest: Digest) -> str:
    if digest.quiet:
        return "ptopilot: a quiet week for your trips"
    top = digest.deals[0]
    count = len(digest.deals)
    lead = f"{top.destination} {money(top.price, top.currency)}"
    if top.pct_below and top.pct_below > 0:
        lead += f" ({top.pct_below}% below typical)"
    more = f" + {count - 1} more" if count > 1 else ""
    return f"ptopilot: {lead}{more}"


def render(
    digest: Digest,
    now: datetime | None = None,
    links: LinkBuilder | None = None,
    base_url: str | None = None,
) -> tuple[str, str, str]:
    """(subject, html, text). `links` adds snooze buttons (label, url) to the lead deal; `base_url` (the web
    app) makes the other deals link to their destination pages."""
    now = now or datetime.now(UTC)
    bars = {
        d.candidate_id: bar_cells(bar)
        for d in digest.deals
        if d.typical and (bar := bar_geometry(d.price, float(d.typical), d.sigma))
    }
    context = {
        "actions": {d.candidate_id: links(d) if links else [] for d in digest.deals},
        "bars": bars,
        "base_url": (base_url or "").rstrip("/"),
        "preheader": subject(digest).removeprefix("ptopilot: "),
        "digest": digest,
        "levels": LEVEL_LABEL,
        "arrows": TREND_ARROW,
        "checked": {d.candidate_id: checked_ago(d.observed_at, now) for d in digest.deals},
    }
    html = _env.get_template("digest.html.j2").render(**context)
    text = _env.get_template("digest.txt.j2").render(**context)
    return subject(digest), html, text
```

- [ ] **Step 7: Write `ptopilot/digest/select.py` (full new contents)**

```python
"""Choose what goes into each traveler's digest (spec §8)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select

from ptopilot import config
from ptopilot.core.geo import NEUTRAL_PALETTE, Geo, Palette, palette
from ptopilot.core.seasons import SeasonTable, trip_month
from ptopilot.db.models import (
    Candidate,
    DigestSend,
    PriceObservation,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    User,
)
from ptopilot.db.session import session_scope
from ptopilot.pipeline.queries import load_baselines, rq_baseline_key

LEVELS = {"none": 0, "good": 1, "great": 2}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class DealCard:
    candidate_id: int
    tracker_id: int
    route_query_id: int
    destination: str
    origin: str
    dest_airport: str
    return_airport: str
    depart_date: date
    return_date: date
    evening_departure: bool
    price: Decimal
    currency: str
    typical: Decimal | None
    deal_level: str
    go_now: int
    confidence: str
    verified: bool
    pto_cost: int
    days_away: int
    days_off: tuple[str, ...]
    season_rating: str
    weather_note: str | None
    carrier: str | None
    stops: int | None
    duration_min: int | None
    outbound_departure: datetime | None
    flight_numbers: tuple[str, ...]
    deep_link: str | None
    observed_at: datetime | None
    palette: Palette = NEUTRAL_PALETTE
    sigma: float | None = None  # spread of the typical price, for the "where this price sits" bar

    @property
    def open_jaw(self) -> bool:
        return self.return_airport != self.dest_airport

    @property
    def pct_below(self) -> int | None:
        if not self.typical or self.typical <= 0:
            return None
        return round(100 * (1 - self.price / self.typical))


@dataclass(frozen=True)
class TrackerRow:
    tracker_id: int
    destination: str
    best_price: Decimal | None
    typical: Decimal | None
    trend: str  # "down" | "up" | "flat" | "new"
    next_good_month: str | None
    snoozed_until: date | None
    palette: Palette = NEUTRAL_PALETTE


@dataclass
class Digest:
    user_id: int
    email: str
    run_date: date
    deals: list[DealCard]
    trackers: list[TrackerRow]
    held_back: int = 0  # deals left out because they were already sent at (about) this price

    @property
    def quiet(self) -> bool:
        return not self.deals


def _next_good_month(seasons: SeasonTable, codes: tuple[str, ...], start: date) -> str | None:
    for i in range(12):
        month = (start.month - 1 + i) % 12 + 1
        if seasons.rating(codes, month) == "good":
            return MONTHS[month - 1]
    return None


def _trend(today: Decimal | None, week_ago: Decimal | None) -> str:
    if today is None or week_ago is None:
        return "new"
    band = Decimal(str(config.TREND_BAND))
    if today < week_ago * (1 - band):
        return "down"
    if today > week_ago * (1 + band):
        return "up"
    return "flat"


def latest_run_date(engine: Engine, today: date) -> date | None:
    with session_scope(engine) as s:
        return s.scalar(select(func.max(Candidate.run_date)).where(Candidate.run_date <= today))


def build_digests(
    engine: Engine,
    geo: Geo,
    seasons: SeasonTable,
    today: date,
    min_level: str = "good",
    user_id: int | None = None,
    skip_sent: bool = True,
) -> list[Digest]:
    """One digest per user with active trackers (or only `user_id`), from the latest scan up to today."""
    run_date = latest_run_date(engine, today)
    if run_date is None:
        return []
    floor = LEVELS[min_level]
    with session_scope(engine) as s:
        baselines = load_baselines(s)
        user_filter = User.id == user_id if user_id is not None else User.id.is_not(None)
        users = list(s.scalars(select(User).where(user_filter).order_by(User.id)))
        trackers = list(s.scalars(select(Tracker).where(Tracker.active.is_(True)).order_by(Tracker.id)))
        rows = s.execute(
            select(Candidate, RouteQuery, TrackerRouteLink, PriceObservation)
            .join(RouteQuery, RouteQuery.id == Candidate.route_query_id)
            .join(
                TrackerRouteLink,
                (TrackerRouteLink.tracker_id == Candidate.tracker_id)
                & (TrackerRouteLink.route_query_id == Candidate.route_query_id)
                & (TrackerRouteLink.run_date == Candidate.run_date)
                & (TrackerRouteLink.evening_departure == Candidate.evening_departure),
            )
            .outerjoin(PriceObservation, PriceObservation.id == Candidate.price_observation_id)
            .where(Candidate.run_date == run_date)
        ).all()
        week_ago = dict(
            s.execute(
                select(Candidate.tracker_id, func.min(Candidate.price))
                .where(Candidate.run_date == run_date - timedelta(days=7))
                .group_by(Candidate.tracker_id)
            ).all()
        )
        # Lowest price already sent per (tracker, route, evening variant). Matched on the identity stored in
        # each item, not on candidate ids: a re-run of the score stage deletes and recreates candidates.
        # Items without that identity (recorded before it was stored) are ignored.
        sent_price: dict[tuple, Decimal] = {}
        for send in s.scalars(select(DigestSend)):
            for item in send.items or []:
                if "route_query_id" not in item:
                    continue
                key = (item["tracker_id"], item["route_query_id"], item["evening_departure"])
                price = Decimal(str(item["price"]))
                sent_price[key] = min(price, sent_price.get(key, price))

    tracker_by_id = {t.id: t for t in trackers}
    cards_by_tracker: defaultdict[int, list[DealCard]] = defaultdict(list)
    held_back: defaultdict[int, int] = defaultdict(int)
    best_today: dict[int, tuple[Decimal, Decimal | None]] = {}
    for c, rq, link, obs in rows:
        tracker = tracker_by_id.get(c.tracker_id)
        if tracker is None:
            continue
        b = baselines.get(rq_baseline_key(rq))
        typical = Decimal(str(round(b.median))) if b else None
        if c.tracker_id not in best_today or c.price < best_today[c.tracker_id][0]:
            best_today[c.tracker_id] = (c.price, typical)
        if LEVELS[c.deal_level] < floor or c.state == "excluded":
            continue
        if tracker.snoozed_until is not None and tracker.snoozed_until >= today:
            continue
        prior = sent_price.get((c.tracker_id, c.route_query_id, c.evening_departure))
        if skip_sent and prior is not None and c.price > prior * Decimal(str(config.DIGEST_RESEND_FACTOR)):
            held_back[c.tracker_id] += 1
            continue
        dest = geo.destination(tracker.destination_code)
        codes = (dest.code, dest.country)
        cards_by_tracker[c.tracker_id].append(
            DealCard(
                candidate_id=c.id,
                tracker_id=c.tracker_id,
                route_query_id=c.route_query_id,
                destination=dest.name,
                origin=rq.origin,
                dest_airport=rq.dest_airport,
                return_airport=rq.return_airport,
                depart_date=rq.depart_date,
                return_date=rq.return_date,
                evening_departure=c.evening_departure,
                price=c.price,
                currency=c.currency,
                typical=typical,
                deal_level=c.deal_level,
                go_now=c.go_now,
                confidence=c.confidence,
                verified=c.verified,
                pto_cost=link.pto_cost,
                days_away=link.days_away,
                days_off=tuple(link.days_off or ()),
                season_rating=link.season_rating,
                weather_note=seasons.note(codes, trip_month(rq.depart_date, rq.return_date)),
                carrier=obs.carrier if obs else None,
                stops=obs.stops if obs else None,
                duration_min=obs.duration_min if obs else None,
                outbound_departure=obs.outbound_departure if obs else None,
                flight_numbers=tuple(obs.flight_numbers or ()) if obs else (),
                deep_link=obs.deep_link if obs else None,
                observed_at=obs.observed_at if obs else None,
                palette=palette(dest),
                sigma=b.sigma if b else None,
            )
        )

    digests = []
    for user in users:
        mine = [t for t in trackers if t.user_id == user.id]
        if not mine:
            continue
        tops, alternates = [], []
        for t in mine:
            ranked = sorted(cards_by_tracker[t.id], key=lambda d: (-d.go_now, d.price, d.candidate_id))
            tops += ranked[:1]
            alternates += ranked[1 : 1 + config.DIGEST_ALTERNATES_PER_TRACKER]
        by_score = lambda d: (-d.go_now, d.price, d.candidate_id)  # noqa: E731
        chosen = (sorted(tops, key=by_score) + sorted(alternates, key=by_score))[: config.DIGEST_MAX_DEALS]
        rows_for_user = []
        for t in mine:
            dest = geo.destination(t.destination_code)
            best, typical = best_today.get(t.id, (None, None))
            rows_for_user.append(
                TrackerRow(
                    tracker_id=t.id,
                    destination=dest.name,
                    best_price=best,
                    typical=typical,
                    trend=_trend(best, week_ago.get(t.id)),
                    next_good_month=_next_good_month(seasons, (dest.code, dest.country), run_date),
                    snoozed_until=t.snoozed_until if t.snoozed_until and t.snoozed_until >= today else None,
                    palette=palette(dest),
                )
            )
        held = sum(held_back[t.id] for t in mine)
        digests.append(
            Digest(user.id, user.email, run_date, sorted(chosen, key=by_score), rows_for_user, held)
        )
    return digests
```

- [ ] **Step 8: Write `ptopilot/digest/send.py` (full new contents)**

```python
"""Send (or preview) digests and record what went out (spec §8)."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, update

from ptopilot import config
from ptopilot.db.models import Candidate, DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest.render import LinkBuilder, render
from ptopilot.digest.select import Digest
from ptopilot.notify.email import Emailer, EmailError

log = logging.getLogger(__name__)
REAL_DEALS = frozenset({"good", "great"})


def deliver(
    engine: Engine,
    digests: Sequence[Digest],
    today: date,
    emailer: Emailer | None = None,
    preview_dir: Path | None = None,
    links: LinkBuilder | None = None,
    base_url: str | None = None,
) -> Counter[str]:
    """Send each digest (or write it to preview_dir), recording sends.

    A digest with no deals ("quiet") goes out only on QUIET_DIGEST_WEEKDAY. Preview never touches the
    database or the network. A failed send is counted and logged; the other digests still go out.
    """
    counts: Counter[str] = Counter()
    for digest in digests:
        if digest.quiet and today.weekday() != config.QUIET_DIGEST_WEEKDAY and preview_dir is None:
            counts["quiet_skipped"] += 1
            continue
        subject, html, text = render(digest, links=links, base_url=base_url)
        if preview_dir is not None:
            preview_dir.mkdir(parents=True, exist_ok=True)
            stem = f"digest-{digest.user_id}-{digest.run_date}"
            (preview_dir / f"{stem}.html").write_text(html, encoding="utf-8")
            (preview_dir / f"{stem}.txt").write_text(f"Subject: {subject}\n\n{text}", encoding="utf-8")
            counts["previewed"] += 1
            continue
        if emailer is None:
            raise ValueError("an emailer is required unless previewing (set RESEND_API_KEY)")
        try:
            emailer.send(digest.email, subject, html, text)
        except EmailError as exc:
            counts["failed"] += 1
            log.error("digest for user %s not sent: %s", digest.user_id, exc)
            continue
        # Only real deals count as "sent": tuning digests (min level none) mustn't hold back later deals.
        deals = [d for d in digest.deals if d.deal_level in REAL_DEALS]
        with session_scope(engine) as s:
            s.add(
                DigestSend(
                    user_id=digest.user_id,
                    items=[
                        {
                            "candidate_id": d.candidate_id,
                            "tracker_id": d.tracker_id,
                            "route_query_id": d.route_query_id,
                            "evening_departure": d.evening_departure,
                            "price": float(d.price),
                        }
                        for d in deals
                    ],
                )
            )
            ids = [d.candidate_id for d in deals]
            if ids:
                s.execute(update(Candidate).where(Candidate.id.in_(ids)).values(state="sent"))
        counts["sent"] += 1
        counts["deals_sent"] += len(deals)
    return counts
```

- [ ] **Step 9: Write `ptopilot/digest/templates/digest.html.j2` (full new contents)**

```jinja
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>ptopilot digest</title>
</head>
{% set serif = "Georgia,'Times New Roman',serif" %}
{% set sans = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif" %}
<body style="margin:0;padding:0;background:#f3efe7;font-family:{{ sans }};color:#1f2937;">
<div style="display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:#f3efe7;">{{ preheader }}</div>
<!--[if mso]><table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3efe7;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#fbf7f0;border-radius:12px;">

  <tr><td style="padding:22px 22px 14px;">
    <div style="font-family:{{ serif }};font-size:22px;font-weight:bold;color:#1f2937;">ptopilot</div>
    <div style="margin-top:4px;font-size:14px;color:#6b7280;">{{ digest.run_date | day }} · {% if digest.quiet %}a quiet week{% else %}{{ digest.deals | length }} trip{{ "s" if digest.deals | length != 1 }} worth a look{% endif %}</div>
  </td></tr>

  {% if digest.quiet %}
  <tr><td style="padding:0 16px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;">
      <tr><td style="padding:18px 20px;">
        <div style="font-family:{{ serif }};font-size:20px;color:#1f2937;">A quiet week for your trips</div>
        <p style="margin:8px 0 0;font-size:15px;line-height:1.5;color:#374151;">
          {% if digest.held_back %}No new deals since your last digest. The ones we sent are still on your dashboard while their prices hold.{% else %}Nothing below typical yet. Your trackers are still watching, and here's where prices stand.{% endif %}
        </p>
      </td></tr>
    </table>
  </td></tr>
  {% else %}
  {% set d = digest.deals[0] %}
  <tr><td style="padding:0 16px 12px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;">
      <tr><td style="background:{{ d.palette.color }};color:#ffffff;padding:14px 20px;border-radius:10px 10px 0 0;">
        <div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;opacity:.85;">{{ levels[d.deal_level] }} · Best this week</div>
        <div style="font-family:{{ serif }};font-size:22px;margin-top:2px;">{{ d.destination }} · {{ d.depart_date | dates(d.return_date) }}</div>
      </td></tr>
      <tr><td style="padding:16px 20px 18px;">
        <div style="font-size:28px;font-weight:bold;color:#111827;">{{ d.price | money(d.currency) }}
          {% if d.pct_below and d.pct_below > 0 %}<span style="font-size:15px;color:{{ d.palette.color }};">{{ d.pct_below }}% below typical</span>{% endif %}
        </div>
        {% if bars.get(d.candidate_id) %}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:10px 0 4px;border-radius:999px;overflow:hidden;"><tr>
          {% for width, kind in bars[d.candidate_id] %}<td width="{{ width }}%" height="8" bgcolor="{{ d.palette.color if kind == 'dot' else (d.palette.tint if kind == 'band' else '#e5e7eb') }}" style="height:8px;font-size:0;line-height:0;">&nbsp;</td>{% endfor %}
        </tr></table>
        {% endif %}
        <div style="font-size:13px;color:#6b7280;">{{ "both flights" if d.open_jaw else "round trip" }}{% if d.typical %} · typically ~{{ d.typical | money(d.currency) }}{% endif %} · Go-now {{ d.go_now }}</div>
        <div style="margin-top:10px;font-size:14px;line-height:1.5;color:#374151;">
          {{ d.depart_date | day }} → {{ d.return_date | day }}{% if d.evening_departure %} · leave after work{% endif %} · {{ d.origin }} → {{ d.dest_airport }}{% if d.open_jaw %}, home from {{ d.return_airport }}{% endif %}<br>
          Uses <b>{{ d.pto_cost }} PTO day{{ "s" if d.pto_cost != 1 }}</b> for {{ d.days_away }} days away{% if d.days_off %} ({{ d.days_off | join(", ") }} gives you a free day){% endif %}
          {% if d.carrier %}<br>{{ d.carrier }} · {{ d.stops | stops }}{% if d.duration_min %} · {{ d.duration_min | duration }} out{% endif %}{% if d.outbound_departure %}, departs {{ d.outbound_departure | clock }}{% endif %}{% if d.flight_numbers %} · {{ d.flight_numbers | join(", ") }}{% endif %} <span style="color:#9ca3af;">(outbound flight)</span>{% endif %}
          {% if d.weather_note %}<br>{{ "Off-season: " if d.season_rating == "avoid" }}{{ d.weather_note }}{% endif %}
        </div>
        <div style="margin-top:8px;font-size:12px;color:#6b7280;">
          {{ "Live price" if d.verified else "Cached price, not yet confirmed live" }}{% if checked[d.candidate_id] %}, {{ checked[d.candidate_id] }}{% endif %}. Fares change fast.{% if d.confidence == "low" %} Typical price is still being learned (low confidence).{% endif %}
        </div>
        {% if d.deep_link %}
        <div style="margin-top:14px;"><a href="{{ d.deep_link }}" style="display:inline-block;padding:10px 18px;border-radius:8px;background:#111827;color:#ffffff;text-decoration:none;font-size:14px;font-weight:bold;">View flights</a></div>
        {% endif %}
        {% if actions[d.candidate_id] %}
        <div style="margin-top:12px;font-size:12px;color:#6b7280;">
          {% for label, url in actions[d.candidate_id] %}<a href="{{ url }}" style="color:#6b7280;">{{ label }}</a>{{ " · " if not loop.last }}{% endfor %}
        </div>
        {% endif %}
      </td></tr>
    </table>
  </td></tr>

  {% if digest.deals | length > 1 %}
  <tr><td style="padding:0 16px 12px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;">
      {% for d in digest.deals[1:] %}
      {% set href = (base_url ~ "/trackers/" ~ d.tracker_id) if base_url else d.deep_link %}
      <tr>
        <td width="4" bgcolor="{{ d.palette.color }}" style="width:4px;font-size:0;line-height:0;{{ 'border-radius:10px 0 0 0;' if loop.first }}{{ 'border-radius:0 0 0 10px;' if loop.last }}">&nbsp;</td>
        <td style="padding:12px 14px;{{ 'border-top:1px solid #f3f4f6;' if not loop.first }}">
          {% if href %}<a href="{{ href }}" style="color:#1f2937;text-decoration:none;">{% endif %}
          <span style="font-family:{{ serif }};font-size:16px;font-weight:bold;">{{ d.destination }}</span><br>
          <span style="font-size:13px;color:#6b7280;">{{ d.depart_date | dates(d.return_date) }} · {{ d.pto_cost }} PTO for {{ d.days_away }} days{% if d.open_jaw %} · open-jaw{% endif %}</span>
          {% if href %}</a>{% endif %}
        </td>
        <td align="right" style="padding:12px 16px;white-space:nowrap;{{ 'border-top:1px solid #f3f4f6;' if not loop.first }}">
          <span style="font-size:16px;font-weight:bold;">{{ d.price | money(d.currency) }}</span><br>
          <span style="font-size:13px;color:{{ d.palette.color }};">{% if d.pct_below and d.pct_below > 0 %}{{ d.pct_below }}% below{% else %}{{ levels[d.deal_level] }}{% endif %}</span>
        </td>
      </tr>
      {% endfor %}
    </table>
  </td></tr>
  {% endif %}
  {% endif %}

  <tr><td style="padding:10px 22px 6px;font-family:{{ serif }};font-size:16px;font-weight:bold;">Your trackers</td></tr>
  <tr><td style="padding:0 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;font-size:13px;">
      <tr style="color:#6b7280;">
        <td width="4" style="width:4px;"></td><td style="padding:10px 12px;">Destination</td><td style="padding:10px 6px;">Best now</td><td style="padding:10px 6px;">Typical</td><td style="padding:10px 6px;">7-day</td><td style="padding:10px 12px;">Next good month</td>
      </tr>
      {% for t in digest.trackers %}
      <tr>
        <td width="4" bgcolor="{{ t.palette.color }}" style="width:4px;font-size:0;line-height:0;">&nbsp;</td>
        <td style="padding:8px 12px;border-top:1px solid #f3f4f6;">{% if base_url %}<a href="{{ base_url }}/trackers/{{ t.tracker_id }}" style="color:#1f2937;text-decoration:none;">{{ t.destination }}</a>{% else %}{{ t.destination }}{% endif %}{% if t.snoozed_until %} <span style="color:#9ca3af;">(snoozed to {{ t.snoozed_until | day }})</span>{% endif %}</td>
        <td style="padding:8px 6px;border-top:1px solid #f3f4f6;">{{ t.best_price | money }}</td>
        <td style="padding:8px 6px;border-top:1px solid #f3f4f6;">{{ t.typical | money }}</td>
        <td style="padding:8px 6px;border-top:1px solid #f3f4f6;">{{ arrows[t.trend] }}</td>
        <td style="padding:8px 12px;border-top:1px solid #f3f4f6;">{{ t.next_good_month or "—" }}</td>
      </tr>
      {% endfor %}
    </table>
  </td></tr>

  <tr><td style="padding:18px 22px 22px;font-size:12px;line-height:1.5;color:#9ca3af;">
    {% if base_url %}<a href="{{ base_url }}/" style="color:#6b7280;">Manage trips</a> · {% endif %}Prices are per person in economy and change constantly; always confirm before booking.<br>
    Why am I getting this? {{ digest.email }} was invited to ptopilot, which emails trip deals on Mondays and Thursdays.
  </td></tr>

</table>
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</body>
</html>
```

- [ ] **Step 10: Write `ptopilot/digest/templates/digest.txt.j2` (full new contents)**

```jinja
ptopilot · {{ digest.run_date | day }}
{% if digest.quiet %}
A quiet week for your trips.
{% if digest.held_back %}
No new deals since your last digest. The ones we sent are still on your dashboard while their prices hold.
{% else %}
Nothing below typical yet. Your trackers are still watching.
{% endif %}
{% else %}
{{ digest.deals | length }} trip{{ "s" if digest.deals | length != 1 }} worth a look
{% set d = digest.deals[0] %}

== Best this week: {{ d.destination }}, {{ levels[d.deal_level] }}, go-now {{ d.go_now }}
{{ d.depart_date | day }} -> {{ d.return_date | day }}{% if d.evening_departure %} (leave after work){% endif %}, {{ d.origin }} -> {{ d.dest_airport }}{% if d.open_jaw %}, home from {{ d.return_airport }}{% endif %}

{{ d.price | money(d.currency) }} {{ "both flights" if d.open_jaw else "round trip" }}{% if d.typical %}, typically ~{{ d.typical | money(d.currency) }}{% if d.pct_below and d.pct_below > 0 %} ({{ d.pct_below }}% below){% endif %}{% endif %}

Uses {{ d.pto_cost }} PTO day{{ "s" if d.pto_cost != 1 }} for {{ d.days_away }} days away{% if d.days_off %} ({{ d.days_off | join(", ") }} gives you a free day){% endif %}

{% if d.carrier %}
{{ d.carrier }}, {{ d.stops | stops }}{% if d.duration_min %}, {{ d.duration_min | duration }} out{% endif %}{% if d.outbound_departure %}, departs {{ d.outbound_departure | clock }}{% endif %}{% if d.flight_numbers %}, {{ d.flight_numbers | join(", ") }}{% endif %} (outbound flight)
{% endif %}
{% if d.weather_note %}
{{ "Off-season: " if d.season_rating == "avoid" }}{{ d.weather_note }}
{% endif %}
{{ "Live price" if d.verified else "Cached price, not yet confirmed live" }}{% if checked[d.candidate_id] %}, {{ checked[d.candidate_id] }}{% endif %}.{% if d.confidence == "low" %} Typical price is still being learned.{% endif %}

{% if d.deep_link %}
View flights: {{ d.deep_link }}
{% endif %}
{% for label, url in actions[d.candidate_id] %}
{{ label }}: {{ url }}
{% endfor %}
{% if digest.deals | length > 1 %}

More trips
{% for d in digest.deals[1:] %}
- {{ d.destination }}: {{ d.price | money(d.currency) }}{% if d.pct_below and d.pct_below > 0 %} ({{ d.pct_below }}% below){% endif %}, {{ d.depart_date | dates(d.return_date) }}, {{ d.pto_cost }} PTO for {{ d.days_away }} days{% if base_url %}: {{ base_url }}/trackers/{{ d.tracker_id }}{% elif d.deep_link %}: {{ d.deep_link }}{% endif %}

{% endfor %}
{% endif %}
{% endif %}

Your trackers
{% for t in digest.trackers %}
- {{ t.destination }}: best {{ t.best_price | money }}, typical {{ t.typical | money }}, 7-day {{ arrows[t.trend] }}, next good month {{ t.next_good_month or "-" }}{% if t.snoozed_until %} (snoozed to {{ t.snoozed_until | day }}){% endif %}

{% endfor %}

{% if base_url %}Manage trips: {{ base_url }}/
{% endif %}
Prices change constantly; always confirm before booking.
Why am I getting this? {{ digest.email }} was invited to ptopilot, which emails trip deals on Mondays and Thursdays.
```

- [ ] **Step 11: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/digest/test_digest_design.py tests/digest/test_render.py`

Expected: PASS. Verified tail: `16 passed in 2.12s`

- [ ] **Step 12: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `432 passed, 1 deselected, 1 warning in 43.71s`; ruff reports nothing.

- [ ] **Step 13: Commit and push**

```bash
git add -A
git commit -m "feat(digest): lead deal card and compact rows in destination colors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 13: Visual QA fixes

Fixes found by screenshotting every page at 1280px and 375px against seeded data: the trend chart was too tall with heavy strokes, the season note repeated on every table row, price and PTO cells wrapped, cards in a row had uneven heights, the footer sat outside the gutter, and window dates stacked on phones.

**Files:**
- Modify: `ptopilot/web/static/app.css`
- Modify: `ptopilot/web/templates/base.html`
- Modify: `ptopilot/web/templates/destination.html`
- Modify: `ptopilot/web/templates/profile.html`
- Modify: `ptopilot/web/viz.py`

**Interfaces:**
- Consumes: Tasks 5, 7, 10, 11 files.
- Produces: No interface changes.

- [ ] **Step 1: Write `ptopilot/web/static/app.css` (full new contents)**

```css
/* ptopilot design system (V2 spec §3). Every page uses these tokens and classes; no page-specific styles. */

:root {
  color-scheme: light;
  --bg: #fbf7f0;
  --surface: #ffffff;
  --ink: #1f2937;
  --muted: #6b7280;
  --line: #f3f4f6;
  --track: #e5e7eb;
  --btn: #111827;
  --danger: #b91c1c;
  --ok: #15803d;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 3px rgba(0, 0, 0, .08);
  --serif: "Fraunces", Georgia, "Times New Roman", serif;
  --sans: "Inter", system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  --gutter: 16px;
  --dest: #374151;       /* set per destination with style="--dest:…;--dest-tint:…" */
  --dest-tint: #cdcfd3;
}
@media (min-width: 768px) { :root { --gutter: 24px; } }

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--sans); }
a { color: inherit; }
img, svg { max-width: 100%; }
h1, h2, h3 { font-family: var(--serif); font-weight: 600; line-height: 1.2; margin: 0; }
h1 { font-size: 30px; letter-spacing: -.01em; }
h2 { font-size: 20px; }
h3 { font-size: 17px; }
p { margin: 0 0 12px; }
.num { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.error { color: var(--danger); }
.ok { color: var(--ok); }
.eyebrow { font: 600 11px/1.4 var(--sans); letter-spacing: .12em; text-transform: uppercase; }

/* Layout */
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 var(--gutter); }
.site-header .wrap { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 18px; padding-bottom: 18px; }
.logo { font: 600 22px/1 var(--serif); text-decoration: none; letter-spacing: -.01em; }
.nav { display: flex; align-items: center; gap: 16px; font-size: 14px; }
.nav a { color: var(--muted); text-decoration: none; }
.nav a:hover, .nav a[aria-current="page"] { color: var(--ink); }
main.wrap { padding-bottom: 56px; }
.page-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 8px 16px; margin: 8px 0 18px; }
.page-head p { margin: 4px 0 0; }
.stack > * + * { margin-top: 14px; }
.site-footer { color: var(--muted); font-size: 13px; padding: 24px 0 40px; }

/* Surfaces */
.panel { background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); padding: 18px; }
.panel > h2:first-child, .panel > h3:first-child { margin-bottom: 10px; }
.panel-narrow { max-width: 460px; margin: 32px auto 0; }
.notice { border-left: 4px solid var(--ok); }
.notice-error { border-left: 4px solid var(--danger); }

/* Buttons and forms */
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 16px; border-radius: var(--radius-sm); border: 1px solid var(--btn); background: var(--btn); color: #fff; font: 600 14px/1.2 var(--sans); text-decoration: none; cursor: pointer; }
.btn:hover { background: #000; }
.btn-ghost { background: transparent; color: var(--ink); border-color: #d6d3d1; }
.btn-ghost:hover { background: var(--surface); }
.btn-sm { padding: 6px 10px; font-size: 13px; }
.link-btn { background: none; border: 0; padding: 0; font: inherit; color: var(--muted); text-decoration: underline; cursor: pointer; }
form.inline { display: inline; }
.field { display: block; margin: 0 0 12px; }
.field > span { display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.field small { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
input, select { width: 100%; padding: 9px 11px; border: 1px solid #d6d3d1; border-radius: var(--radius-sm); background: #fff; color: var(--ink); font: inherit; }
input:focus, select:focus { outline: 2px solid var(--dest, #111827); outline-offset: 1px; border-color: transparent; }
input[type="checkbox"] { width: auto; margin: 0 8px 0 0; }
.check { display: flex; align-items: center; font-size: 14px; margin: 6px 0; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0 14px; }
.fields-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; max-width: 480px; }
.row-fields { display: grid; grid-template-columns: 2fr repeat(4, 1fr); gap: 0 10px; align-items: end; }
@media (max-width: 640px) { .row-fields { grid-template-columns: 1fr 1fr; } .row-fields > :first-child { grid-column: 1 / -1; } }
.form-actions { display: flex; gap: 10px; align-items: center; margin-top: 18px; }

/* "Where this price sits" bar: the typical band (tint) and today's price (dot) */
.pbar { position: relative; height: 8px; border-radius: 999px; background: var(--track); margin: 10px 0 8px; }
.pbar .band { position: absolute; top: 0; height: 8px; border-radius: 999px; background: var(--dest-tint); }
.pbar .dot { position: absolute; top: -3px; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; background: var(--dest); border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0, 0, 0, .06); }
.vs { font-size: 13px; font-weight: 600; color: var(--muted); }
.vs-below { color: var(--dest); }

/* PTO bar */
.pto { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 14px 18px; }
.pto-track { flex: 1 1 200px; display: flex; gap: 3px; height: 10px; }
.pto-track span { border-radius: 999px; }
.pto-used { background: #9ca3af; }
.pto-left { background: var(--track); }

/* Destination cards */
.grid { display: grid; gap: 14px; grid-template-columns: 1fr; }
.grid > div { display: flex; flex-direction: column; }
.grid .dest-card { flex: 1; }
@media (min-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
.dest-card { display: block; background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; text-decoration: none; transition: box-shadow .15s, transform .15s; }
a.dest-card:hover { box-shadow: 0 6px 18px rgba(0, 0, 0, .1); transform: translateY(-1px); }
.dest-head { background: var(--dest); background: linear-gradient(135deg, var(--dest), color-mix(in srgb, var(--dest) 70%, #000)); color: #fff; padding: 14px 18px; }
.dest-head .eyebrow { opacity: .85; }
.dest-head h2, .dest-head h3 { color: #fff; }
.dest-body { padding: 14px 18px 16px; }
.price { font: 700 24px/1.1 var(--sans); font-variant-numeric: tabular-nums; }
.price-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; }
.meta { color: var(--muted); font-size: 13px; }
.dimmed { opacity: .55; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--line); color: var(--muted); font-size: 12px; font-weight: 600; }

/* Destination page */
.hero { border-radius: var(--radius); padding: 22px 22px 24px; margin-bottom: 16px; }
.hero h1 { color: #fff; font-size: 34px; margin-top: 4px; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.hero .btn-ghost { color: #fff; border-color: rgba(255, 255, 255, .5); }
.hero .btn-ghost:hover { background: rgba(255, 255, 255, .12); }
.trips { width: 100%; border-collapse: collapse; font-size: 14px; }
.trips th { text-align: left; font: 600 11px/1.4 var(--sans); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 0 8px 8px; }
.trips td { padding: 10px 8px; border-top: 1px solid var(--line); vertical-align: middle; }
.trips td.bar-cell { width: 26%; min-width: 120px; }
.trips .pbar { margin: 0; }
@media (max-width: 640px) {
  .trips thead { display: none; }
  .trips, .trips tbody, .trips tr, .trips td { display: block; width: 100%; }
  .trips tr { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 12px 0; border-top: 1px solid var(--line); }
  .trips td { border: 0; padding: 0; }
  .trips td.bar-cell { grid-column: 1 / -1; width: auto; padding: 6px 0; }
  .trips td.flights { grid-column: 1 / -1; }
}
.trend-panel .trend { display: block; width: 100%; height: auto; max-height: 220px; margin: 8px 0 4px; }
.nowrap { white-space: nowrap; }
.trend-axis { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }

/* Landing */
.landing-hero { display: grid; gap: 28px; align-items: center; padding: 24px 0 36px; }
@media (min-width: 768px) { .landing-hero { grid-template-columns: 1.1fr 1fr; padding: 48px 0 56px; } }
.landing-hero h1 { font-size: clamp(32px, 5vw, 46px); line-height: 1.08; }
.lede { font-size: 17px; color: #4b5563; margin: 14px 0 22px; max-width: 34em; }
.signin { display: flex; flex-wrap: wrap; gap: 8px; max-width: 440px; }
.signin input { flex: 1 1 220px; }
.samples { display: grid; gap: 12px; }
.sample-label { position: absolute; top: 10px; right: 12px; background: rgba(255, 255, 255, .2); color: #fff; }
.samples .dest-card { position: relative; }
.steps { display: grid; gap: 12px; grid-template-columns: 1fr; counter-reset: step; }
@media (min-width: 768px) { .steps { grid-template-columns: repeat(3, 1fr); } }
.step { counter-increment: step; }
.step::before { content: counter(step); display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: var(--btn); color: #fff; font: 700 13px/1 var(--sans); margin-bottom: 10px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
```

- [ ] **Step 2: Write `ptopilot/web/templates/base.html` (full new contents)**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}ptopilot{% endblock %}</title>
<meta name="description" content="ptopilot watches flight prices for the trips your PTO can actually take, and emails you when one is genuinely cheap.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Inter:wght@400;600;700&display=swap">
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <a class="logo" href="/">ptopilot</a>
    <nav class="nav" aria-label="Main">
      {% if signed_in %}
      <a href="/" {% if active == "dashboard" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/profile" {% if active == "profile" %}aria-current="page"{% endif %}>Profile</a>
      <form class="inline" method="post" action="/logout"><button class="link-btn" type="submit">Sign out</button></form>
      {% else %}
      <a class="btn btn-ghost btn-sm" href="/#sign-in">Sign in</a>
      {% endif %}
    </nav>
  </div>
</header>
<main class="wrap">
{% block content %}{% endblock %}
</main>
<footer class="site-footer"><div class="wrap">ptopilot · flight prices for the PTO you actually have · invite-only for now</div></footer>
</body>
</html>
```

- [ ] **Step 3: Write `ptopilot/web/templates/destination.html` (full new contents)**

```html
{% extends "base.html" %}
{% from "_components.html" import dest_style, price_bar, vs_typical, season %}
{% block title %}{{ dest.name }} · ptopilot{% endblock %}
{% block content %}
<div class="hero dest-head" style="{{ dest_style(palette) }}">
  <div class="eyebrow">{{ stay[0] }}–{{ stay[1] }} days on the ground</div>
  <h1>{{ dest.name }}</h1>
  <div class="hero-actions">
    {% if snoozed_until %}
    <span class="tag">Snoozed until {{ snoozed_until | day }}</span>
    <form class="inline" method="post" action="/trackers/{{ tracker_id }}/unsnooze"><button class="btn btn-ghost btn-sm" type="submit">Unsnooze</button></form>
    {% else %}
    <form class="inline" method="post" action="/trackers/{{ tracker_id }}/snooze"><input type="hidden" name="days" value="30"><button class="btn btn-ghost btn-sm" type="submit">Snooze 30 days</button></form>
    {% endif %}
    <a class="btn btn-ghost btn-sm" href="/">All trips</a>
  </div>
</div>

<div class="stack" style="{{ dest_style(palette) }}">
  <section class="panel">
    <h2>Date options</h2>
    {% if options %}
    <p class="muted small">From the {{ run_date | day }} scan, cheapest first · {{ season(options[0]) }}. Prices are per person, economy, and change fast.</p>
    <table class="trips">
      <thead><tr><th>Dates</th><th>Price</th><th>vs typical</th><th>PTO</th><th>Flights</th></tr></thead>
      <tbody>
      {% for o in options %}
      <tr{% if o.dimmed %} class="dimmed"{% endif %}>
        <td><b>{{ o.depart_date | day }} → {{ o.return_date | day }}</b>
          <div class="meta">{{ o.origin }} → {% if o.open_jaw %}into {{ o.dest_airport }} · home from {{ o.return_airport }}{% else %}{{ o.dest_airport }}{% endif %}{% if o.evening_departure %} · leave after work{% endif %}</div></td>
        <td class="nowrap"><span class="price" style="font-size:18px;">{{ o.price | money(o.currency) }}</span><div>{{ vs_typical(o) }}</div></td>
        <td class="bar-cell">{{ price_bar(o.bar) }}</td>
        <td class="num nowrap"><b>{{ o.pto_cost }}</b> <span class="meta">for {{ o.days_away }} days</span></td>
        <td class="flights">
          {% if o.carrier %}<div class="meta">{{ o.carrier }} · {{ o.stops | stops }}{% if o.overnight %} · overnight{% endif %}</div>{% endif %}
          {% if o.deep_link %}<a class="btn btn-sm" href="{{ o.deep_link }}" rel="noopener" target="_blank">View flights</a>{% endif %}
          {% if o.dimmed %}<span class="tag">{{ o.state }}</span>{% endif %}
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="muted" style="margin:0;">First prices after the next daily scan.</p>
    {% endif %}
  </section>

  <section class="panel trend-panel">
    <h2>Cheapest fare, last 30 days</h2>
    {% if chart %}
    <div class="trend-axis"><span>{{ chart.high | money }}</span>{% if band %}<span>shaded: typical {{ band[0] | money }}–{{ band[1] | money }}</span>{% endif %}</div>
    {{ chart.svg }}
    <div class="trend-axis"><span>{{ chart.first | day }} · low {{ chart.low | money }}</span><span>{{ chart.last | day }}</span></div>
    {% else %}
    <p class="muted" style="margin:0;">Price history fills in after a few daily scans.</p>
    {% endif %}
  </section>
</div>
{% endblock %}
```

- [ ] **Step 4: Write `ptopilot/web/templates/profile.html` (full new contents)**

```html
{% extends "base.html" %}
{% from "_components.html" import field %}
{% block title %}Profile · ptopilot{% endblock %}
{% block content %}
<div class="page-head">
  <div>
    <h1>Your travel profile</h1>
    <p class="muted small">Changes apply from the next morning scan.</p>
  </div>
</div>
{% if errors %}
<div class="panel notice-error" style="margin-bottom:14px;">
  <p class="error" style="margin-bottom:6px;"><b>Please fix {{ errors | length }} thing{{ "s" if errors | length != 1 }}:</b></p>
  <ul class="error" style="margin:0;padding-left:20px;">{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
</div>
{% endif %}
<form method="post" action="/profile" class="stack">
  <section class="panel">
    <h2>Home and calendar</h2>
    <div class="fields">
      {{ field("home_airport", "Home airport", form.home_airport, attrs='placeholder="JFK" required') }}
      {{ field("nearby_airports", "Also fly from", form.nearby_airports, attrs='placeholder="EWR, PHL"') }}
      {{ field("country", "Country", form.country, attrs='maxlength="2"') }}
      {{ field("holiday_calendar", "Holiday calendar", form.holiday_calendar, attrs='placeholder="US or GB-ENG"') }}
    </div>
    {{ field("ignored_holidays", "Holidays your office works", form.ignored_holidays, hint="Comma-separated, e.g. Columbus Day, Veterans Day") }}
    {{ field("extra_days_off", "Company days off", form.extra_days_off, hint="YYYY-MM-DD, comma-separated") }}
  </section>

  <section class="panel">
    <h2>PTO and trip length</h2>
    <div class="fields">
      {{ field("pto_days_total", "PTO days this year", form.pto_days_total, attrs='inputmode="numeric" required') }}
      {{ field("pto_committed", "Already committed", form.pto_committed, attrs='inputmode="numeric"') }}
      {{ field("min_trip_days", "Shortest trip", form.min_trip_days, hint="Days away from home", attrs='inputmode="numeric"') }}
      {{ field("max_trip_days", "Longest trip", form.max_trip_days, hint="Days away from home", attrs='inputmode="numeric" required') }}
      {{ field("ideal_trip_days", "Ideal trip", form.ideal_trip_days, hint="Optional. Trips near it are priced first.", attrs='inputmode="numeric" placeholder="no preference"') }}
    </div>
  </section>

  <section class="panel">
    <h2>Travel windows</h2>
    {% for i in range(windows) %}
    <div class="fields-2">
      {{ field("window_start_%d" % i, "From", form["window_start_%d" % i], type="date") }}
      {{ field("window_end_%d" % i, "To", form["window_end_%d" % i], type="date") }}
    </div>
    {% endfor %}
    <p class="muted small" style="margin:0;">Leave a row blank to remove it.</p>
  </section>

  <section class="panel">
    <h2>Bucket list</h2>
    <p class="muted small">Days on the ground, after travel days. Priority 1 is checked first.</p>
    {% for i in range(trackers) %}
    <div class="row-fields">
      <label class="field"><span>Destination</span>
        <select id="tracker_dest_{{ i }}" name="tracker_dest_{{ i }}">
          <option value=""></option>
          {% for d in destinations %}<option value="{{ d.code }}" {{ "selected" if form['tracker_dest_%d' % i] == d.code }}>{{ d.name }}</option>{% endfor %}
        </select></label>
      {{ field("tracker_min_%d" % i, "Min days", form["tracker_min_%d" % i], attrs='inputmode="numeric"') }}
      {{ field("tracker_max_%d" % i, "Max days", form["tracker_max_%d" % i], attrs='inputmode="numeric"') }}
      {{ field("tracker_priority_%d" % i, "Priority", form["tracker_priority_%d" % i], attrs='inputmode="numeric"') }}
      {{ field("tracker_price_%d" % i, "Max price", form["tracker_price_%d" % i], attrs='inputmode="numeric" placeholder="any"') }}
    </div>
    {% endfor %}
    <p class="muted small" style="margin:0;">Missing a destination? It has to be added to the app's data first.</p>
  </section>

  <section class="panel">
    <h2>Preferences</h2>
    <div class="fields">
      <label class="field"><span>Weather</span>
        <select id="weather_tolerance" name="weather_tolerance">
          {% for value, text in [("strict", "Only the best months"), ("normal", "Skip bad-weather months"), ("relaxed", "Any month")] %}
          <option value="{{ value }}" {{ "selected" if form.weather_tolerance == value }}>{{ text }}</option>
          {% endfor %}
        </select></label>
      {{ field("max_stops_short", "Max stops (short haul)", form.max_stops_short, attrs='inputmode="numeric"') }}
      {{ field("max_stops_long", "Max stops (long haul)", form.max_stops_long, attrs='inputmode="numeric"') }}
      {{ field("friday_evening_min_time", "Leave-after-work time", form.friday_evening_min_time, type="time") }}
    </div>
    <label class="check"><input type="checkbox" name="allow_overnight_layover" {{ "checked" if form.allow_overnight_layover }}> Overnight layovers are OK</label>
    <label class="check"><input type="checkbox" name="friday_evening_departure" {{ "checked" if form.friday_evening_departure }}> I can leave after work on my last workday</label>
  </section>

  <div class="form-actions"><button class="btn" type="submit">Save profile</button><a class="muted small" href="/">Cancel</a></div>
</form>
{% endblock %}
```

- [ ] **Step 5: Write `ptopilot/web/viz.py` (full new contents)**

```python
"""Server-side drawing for the web app and digest: the "where this price sits" bar and the price trend.

No JavaScript: the bar is a set of percentages for CSS (or email table cells), and the trend is a small
inline SVG.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from markupsafe import Markup

from ptopilot import config
from ptopilot.core.geo import Palette

BAR_SIGMAS = 3  # the bar spans median +/- 3 sigma; the typical band is median +/- 1 sigma
BAR_MIN, BAR_MAX = 2.0, 98.0  # keep the dot on the track
CHART_W, CHART_H, CHART_PAD = 800, 160, 10


@dataclass(frozen=True)
class BarGeometry:
    dot: float  # 0-100, left to right
    band_start: float
    band_end: float


@dataclass(frozen=True)
class TrendPoint:
    run_date: date
    price: Decimal


@dataclass(frozen=True)
class TrendChart:
    svg: Markup
    low: Decimal
    high: Decimal
    first: date
    last: date


def bar_geometry(price: Decimal, median: float | None, sigma: float | None) -> BarGeometry | None:
    if median is None:
        return None
    median = float(median)
    sigma = max(float(sigma or 0), config.SIGMA_FLOOR_FRACTION * median, 1.0)
    lo, span = median - BAR_SIGMAS * sigma, 2 * BAR_SIGMAS * sigma

    def pos(x: float) -> float:
        return round(min(max((x - lo) / span * 100, BAR_MIN), BAR_MAX), 1)

    return BarGeometry(pos(float(price)), pos(median - sigma), pos(median + sigma))


def trend_chart(
    points: list[TrendPoint], band: tuple[Decimal, Decimal] | None, palette: Palette
) -> TrendChart | None:
    """A line of the cheapest price per scan day; missing days break the line. None below MIN_TREND_POINTS."""
    if len(points) < config.MIN_TREND_POINTS:
        return None
    points = sorted(points, key=lambda p: p.run_date)
    prices = [p.price for p in points] + (list(band) if band else [])
    low, high = min(prices), max(prices)
    first, last = points[0].run_date, points[-1].run_date
    days = max((last - first).days, 1)
    spread = float(high - low) or 1.0

    def xy(p: TrendPoint) -> tuple[float, float]:
        x = CHART_PAD + (p.run_date - first).days / days * (CHART_W - 2 * CHART_PAD)
        y = CHART_H - CHART_PAD - float(p.price - low) / spread * (CHART_H - 2 * CHART_PAD)
        if high == low:
            y = CHART_H / 2
        return round(x, 1), round(y, 1)

    segments: list[list[TrendPoint]] = [[points[0]]]
    for prev, cur in zip(points, points[1:], strict=False):
        if (cur.run_date - prev.run_date).days > 1:
            segments.append([])
        segments[-1].append(cur)

    parts = [
        f'<svg class="trend" viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
        f'aria-label="Cheapest fare from {first:%b %d} to {last:%b %d}">'
    ]
    if band:
        top = xy(TrendPoint(first, band[1]))[1]
        bottom = xy(TrendPoint(first, band[0]))[1]
        height = round(bottom - top, 1)
        parts.append(f'<rect x="0" y="{top}" width="{CHART_W}" height="{height}" fill="{palette.tint}"/>')
    for seg in segments:
        coords = " ".join(f"{x},{y}" for x, y in map(xy, seg))
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{palette.color}" stroke-width="3" '
            'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        )
    cx, cy = xy(points[-1])
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="{palette.color}" stroke="#fff" stroke-width="2"/>')
    parts.append("</svg>")
    return TrendChart(Markup("".join(parts)), low, high, first, last)
```

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `432 passed, 1 deselected, 1 warning in 48.40s`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "fix(web): visual QA (chart size, table wrapping, card heights, footer, window rows)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 14: Roadmap, your profile, and a live check

Close out V2 "Look and feel": update the roadmap, set your own ideal trip length on Neon, and check the deployed site.

**Files:**
- Modify: `ROADMAP.md`
- Modify (git-ignored, never shown or committed): `profiles/nick.yaml`

- [ ] **Step 1: Update `ROADMAP.md`**

Tick the open-jaw item (built in Plan 4) and the digest polish item, and add the two V2 items this plan delivered. Replace these two lines:

```markdown
- [ ] **Open-jaw and multi-city itineraries.** Fly into one city and out of another (e.g. into BKK, out of DPS). Requires a new shape type and new source queries.
```

```markdown
- [ ] **Digest visual polish.** Iterate on the design once real MVP emails exist.
```

with:

```markdown
- [x] **Open-jaw itineraries.** Fly into one city and home from another (Plan 4: Camino Portugués, Porto → Santiago, priced through SerpApi). Multi-city with more than two legs is still open.
```

```markdown
- [x] **Digest visual polish.** Lead deal card and compact rows in destination colors (Plan 7).
- [x] **Web app look and feel.** Design system, landing page, destination-grid dashboard, destination pages with a 30-day price trend (Plan 7; spec `docs/superpowers/specs/2026-10-17-ptopilot-v2-look-and-feel-design.md`).
- [x] **Preferred trip length.** `ideal_trip_days` steers which trips are priced and adds a go-now bonus (Plan 7).
```

- [ ] **Step 2: Commit and push**

```bash
git add ROADMAP.md
git commit -m "docs: roadmap after V2 look and feel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 3: Set your ideal trip length on Neon**

Add `ideal_trip_days: 10` under `max_trip_days` in `profiles/nick.yaml` (git-ignored; edit it without printing it), then load it against Neon with the pooled URL from `.env.local`, without printing the URL:

```powershell
$line = Select-String -Path .env.local -Pattern '^DATABASE_URL=' | Select-Object -First 1
$env:DATABASE_URL = $line.Line.Split('=', 2)[1].Trim('"')
if (-not $env:DATABASE_URL) { throw "DATABASE_URL not found in .env.local" }
.venv/Scripts/python -m ptopilot.profiles load profiles/nick.yaml --dry-run
.venv/Scripts/python -m ptopilot.profiles load profiles/nick.yaml
Remove-Item Env:DATABASE_URL
```

Expected: `applied profile for …: user=updated, windows=2, trackers_added=0, trackers_updated=4, trackers_deactivated=0`. The address is printed, so don't copy this output anywhere public.

- [ ] **Step 4: Check the live site**

Once Render shows the latest deploy as live:
- `https://ptopilot.onrender.com/` signed out shows the landing page.
- `https://ptopilot.onrender.com/static/app.css` returns the stylesheet.
- Signed in (a sign-in link to your address): the dashboard shows the PTO bar and four destination cards, and each card opens its destination page.
- The next morning's `scan.yml` run is green (it applies migrations, which are already at 0005).

Report anything that differs; don't change code in this step.
