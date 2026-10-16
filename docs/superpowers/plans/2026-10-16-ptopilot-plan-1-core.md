# ptopilot Plan 1: Foundation and Core Logic

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pip-installable `ptopilot` package whose pure `core/` turns a traveler's PTO, holiday calendar, travel windows and bucket list into a ranked, season-filtered list of concrete itineraries, plus the baseline/z-score/go-now math used later to judge prices.

**Architecture:** `ptopilot/core/` is pure Python with no network or database access: calendar → shapes → selection → seasons/geo → planner, plus stats and scoring. Reference data lives in `ptopilot/data/*.yaml`. Every threshold lives in `ptopilot/config.py`. Later plans (DB, sources, pipeline, digest, web) call into `core/` and never the reverse.

**Tech Stack:** Python ≥3.12, `holidays`, `PyYAML`, `pytest`, `ruff`, GitHub Actions CI.

**Spec:** [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](../specs/2026-10-16-ptopilot-design.md), sections 2, 4, 6 and the `baselines`/`score` stages of 7.

## Plan sequence

The spec is split into five plans. Each one ends with working, tested software.

| Plan | Delivers | Spec sections |
|---|---|---|
| **1 (this)** | Package scaffold, CI, and all pure `core/` logic and bundled data | §2, §4 layout, §6, §7 math |
| 2 | Postgres models + Alembic, Neon config, `FareSource` adapters (Travelpayouts, fast-flights, SerpApi) tested against recorded fixtures | §3, §5 |
| 3 | Pipeline stages + runner CLI, circuit breaker, budgets, `scan.yml`, health email | §4, §7, §10 |
| 4 | Digest selection/render/send, snooze tokens, `digest.yml`, `scripts/generate_seasons.py` | §6.5, §8 |
| 5 | Web app (magic-link auth, invite gate, onboarding, dashboard, snooze endpoints), Render deploy, `keepalive.yml` | §9, §10 |

## Global Constraints

- Python `>=3.12` (the dev machine has 3.13; CI pins 3.12).
- Runtime dependencies for this plan: `holidays>=0.60`, `pyyaml>=6.0` only. Dev: `pytest>=8.0`, `ruff>=0.6`.
- `ptopilot/core/` imports nothing from `db/`, `sources/`, `web/`, `pipeline/`, `digest/`, and does no network I/O.
- Every tunable number lives in `ptopilot/config.py`. Logic modules import it and never hard-code thresholds.
- `ruff check .` and `ruff format --check .` must pass. Line length 110, rules `E,F,I,UP,B`.
- Tests never touch the network. The `live` marker is excluded by default.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- All commands run from the repo root `C:\Users\nickd\dev\ptopilot` and use the venv interpreter `.venv/Scripts/python`.

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **Overlapping travel windows** (e.g. "June" and "early June") → no duplicate itineraries. *Task 9: `test_overlapping_windows_do_not_duplicate_itineraries`.*
2. **A window crossing New Year** → holidays from both years count toward PTO savings. *Task 3: `test_window_across_new_year_uses_both_years_holidays`.*
3. **A holiday falling on a weekend** → the observed weekday is free, and ignoring a holiday also ignores its observed day. *Task 2: `test_weekend_holiday_uses_observed_weekday`, `test_ignored_holidays_become_workdays_including_observed`.*
4. **PTO budget used up or negative** → only zero-PTO trips are returned, never an error. *Task 9: `test_zero_pto_left_only_allows_free_trips`, `test_negative_pto_is_treated_as_zero`.*
5. **Bad codes or inverted ranges** (unknown calendar, destination or airport; min stay > max stay; window end before start) → a clear error naming the bad value. *Tasks 2, 3, 6, 9.*

## File structure

```
pyproject.toml                 # package, deps, pytest + ruff config
.gitignore
.github/workflows/ci.yml       # ruff + pytest on every push
ptopilot/
  __init__.py
  config.py                    # all thresholds and weights
  core/
    __init__.py
    calendar.py                # WorkCalendar: workdays, PTO cost, holiday names
    shapes.py                  # TripShape, generate_shapes
    selection.py               # ShapeConstraints, satisfies, select_top
    seasons.py                 # SeasonTable, trip_month, is_allowed
    geo.py                     # Geo, Airport, Destination, TravelRule
    stats.py                   # Baseline, compute_baseline, z_score, deal_level, length_bucket
    scoring.py                 # go_now and its components
    planner.py                 # TravelerProfile, TrackerSpec, Window, plan_itineraries
  data/
    __init__.py                # load_geo(), load_seasons()
    geo.yaml                   # seed airports, destinations, travel rules
    seasons.yaml               # seed season ratings (TH, LIS, TYO)
tests/
  __init__.py
  test_smoke.py
  core/__init__.py
  core/test_*.py               # one test module per core module
```

---

### Task 1: Project scaffold, config, and CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml`
- Create: `ptopilot/__init__.py`, `ptopilot/core/__init__.py`, `ptopilot/config.py`
- Create: `tests/__init__.py` (empty), `tests/core/__init__.py` (empty)
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: `ptopilot.config` constants used by every later task: `TOP_SHAPES_PER_WINDOW`, `MAX_SHAPES_PER_LENGTH`, `WINDOW_SLACK_DAYS`, `COLD_START_N`, `MAD_TO_SIGMA`, `SIGMA_FLOOR_FRACTION`, `GOOD_DEAL_Z`, `GREAT_DEAL_Z`, `GO_NOW_WEIGHTS`, `DEAL_Z_FOR_FULL_SCORE`, `WEATHER_SCORES`, `SWEET_SPOT_DAYS`, `OFF_SWEET_SPOT_TIMING`.

The repo already exists with the spec and `ROADMAP.md` committed. Create a venv and the package skeleton.

- [ ] **Step 0: Create the virtualenv**

Run: `python -m venv .venv && .venv/Scripts/python -m pip install pytest ruff`
Expected: a `.venv/` folder appears and pip reports pytest and ruff installed.

- [ ] **Step 1: Write the failing test** `tests/test_smoke.py`

```python
from ptopilot import config


def test_package_imports_and_thresholds_are_ordered():
    assert config.GREAT_DEAL_Z < config.GOOD_DEAL_Z < 0
    assert abs(sum(config.GO_NOW_WEIGHTS.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_smoke.py -v`
Expected: ERROR: ModuleNotFoundError: No module named 'ptopilot'

- [ ] **Step 3: Create** `pyproject.toml`

```toml
[project]
name = "ptopilot"
version = "0.1.0"
description = "PTO-aware flight deal tracker"
requires-python = ">=3.12"
dependencies = [
    "holidays>=0.60",
    "pyyaml>=6.0",
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

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits real external APIs; run manually with -m live"]
addopts = "-m 'not live'"

[tool.ruff]
line-length = 110
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 4: Create** `.gitignore`

```
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
.ruff_cache/
.env
*.local.*
```

- [ ] **Step 5: Create** `.github/workflows/ci.yml`

```yaml
name: ci
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest
```

- [ ] **Step 6: Create** `ptopilot/__init__.py`

```python
"""ptopilot: PTO-aware flight deal tracker."""
```

- [ ] **Step 7: Create** `ptopilot/core/__init__.py`

```python
"""Pure domain logic. Must not import db, sources, web, or do any I/O beyond reading bundled data."""
```

- [ ] **Step 8: Create** `ptopilot/config.py`

```python
"""Tunable thresholds and weights. Change behavior here, not in the logic modules."""

# Itinerary pruning
TOP_SHAPES_PER_WINDOW = 6
MAX_SHAPES_PER_LENGTH = 2
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
```

- [ ] **Step 9: Install the package in editable mode with dev tools**

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: ends with `Successfully installed ... ptopilot-0.1.0 ...`

Also create the empty files `tests/__init__.py` and `tests/core/__init__.py`.

- [ ] **Step 10: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_smoke.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .gitignore .github/workflows/ci.yml ptopilot/__init__.py ptopilot/core/__init__.py ptopilot/config.py tests/__init__.py tests/core/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold ptopilot package, config, and CI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Work calendar

**Files:**
- Create: `ptopilot/core/calendar.py`
- Test: `tests/core/test_calendar.py`

**Interfaces:**
- Consumes: the `holidays` package (`holidays.country_holidays(country, subdiv=..., years=...)`).
- Produces: `ONE_DAY: timedelta`; `WorkCalendar(country, subdiv=None, extra_days_off=frozenset(), ignored_holidays=frozenset())` (frozen, hashable) with `WorkCalendar.from_code(code: str, extra_days_off=(), ignored_holidays=()) -> WorkCalendar` (raises `ValueError` naming the code if unknown), `.holiday_name(d) -> str | None`, `.is_workday(d) -> bool`, `.pto_cost(start, end) -> int` (inclusive), `.weekday_days_off(start, end) -> tuple[str, ...]`.

Holiday names come from `holidays` 0.106 and were checked against real output. For example, US 2027 includes `Columbus Day` and `Veterans Day` (often worked, hence `ignored_holidays`), and `Independence Day (observed)` on Mon Jul 5 2027. Scotland has no Easter Monday, and its summer bank holiday is Aug 2, not Aug 30.

- [ ] **Step 1: Write the failing test** `tests/core/test_calendar.py`

```python
from datetime import date

import pytest

from ptopilot.core.calendar import WorkCalendar

US = WorkCalendar.from_code("US")


def test_weekends_are_not_workdays():
    assert US.is_workday(date(2027, 8, 4))  # Wed
    assert not US.is_workday(date(2027, 8, 7))  # Sat
    assert not US.is_workday(date(2027, 8, 8))  # Sun


def test_thanksgiving_is_off_but_day_after_is_not_by_default():
    assert not US.is_workday(date(2027, 11, 25))
    assert US.is_workday(date(2027, 11, 26))


def test_extra_company_days_off():
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 11, 26)])
    assert not cal.is_workday(date(2027, 11, 26))


def test_weekend_holiday_uses_observed_weekday():
    # July 4 2027 is a Sunday; Monday July 5 is the observed holiday.
    assert not US.is_workday(date(2027, 7, 5))
    assert US.holiday_name(date(2027, 7, 5)) == "Independence Day (observed)"


def test_ignored_holidays_become_workdays_including_observed():
    cal = WorkCalendar.from_code(
        "US", ignored_holidays=["Columbus Day", "Juneteenth National Independence Day"]
    )
    assert cal.is_workday(date(2027, 10, 11))  # Columbus Day
    assert cal.is_workday(date(2027, 6, 18))  # Juneteenth (observed)
    assert not cal.is_workday(date(2027, 5, 31))  # Memorial Day still off


def test_pto_cost_counts_only_workdays():
    # Sat May 29 -> Sun Jun 6 2027 spans Memorial Day: Tue-Fri are the only workdays.
    assert US.pto_cost(date(2027, 5, 29), date(2027, 6, 6)) == 4


def test_uk_easter_differs_between_england_and_scotland():
    eng = WorkCalendar.from_code("GB-ENG")
    sct = WorkCalendar.from_code("GB-SCT")
    assert eng.pto_cost(date(2027, 3, 26), date(2027, 3, 29)) == 0  # Good Fri -> Easter Mon
    assert sct.pto_cost(date(2027, 3, 26), date(2027, 3, 29)) == 1  # no Easter Monday in Scotland


def test_uk_summer_bank_holiday_differs_between_england_and_scotland():
    eng = WorkCalendar.from_code("gb-eng")
    sct = WorkCalendar.from_code("GB-SCT")
    assert not eng.is_workday(date(2027, 8, 30)) and eng.is_workday(date(2027, 8, 2))
    assert not sct.is_workday(date(2027, 8, 2)) and sct.is_workday(date(2027, 8, 30))


def test_weekday_days_off_lists_names_in_order():
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 11, 26)])
    assert cal.weekday_days_off(date(2027, 11, 20), date(2027, 11, 28)) == (
        "Thanksgiving Day",
        "Company day off",
    )


def test_weekday_days_off_skips_weekend_holidays():
    # Juneteenth itself is Sat Jun 19 2027; only the observed Friday saves PTO.
    assert US.weekday_days_off(date(2027, 6, 18), date(2027, 6, 20)) == (
        "Juneteenth National Independence Day (observed)",
    )


def test_unknown_calendar_code_is_a_clear_error():
    with pytest.raises(ValueError, match="XX"):
        WorkCalendar.from_code("XX")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_calendar.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.calendar'`

- [ ] **Step 3: Create** `ptopilot/core/calendar.py`

```python
"""Work calendar: decides which days cost PTO."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import holidays

ONE_DAY = timedelta(days=1)
OBSERVED_SUFFIX = " (observed)"


@lru_cache(maxsize=512)
def _holiday_names(country: str, subdiv: str | None, year: int) -> dict[date, str]:
    return dict(holidays.country_holidays(country, subdiv=subdiv, years=year))


def _base_name(name: str) -> str:
    return name.removesuffix(OBSERVED_SUFFIX)


@dataclass(frozen=True)
class WorkCalendar:
    country: str
    subdiv: str | None = None
    extra_days_off: frozenset[date] = frozenset()
    ignored_holidays: frozenset[str] = frozenset()

    @classmethod
    def from_code(
        cls,
        code: str,
        extra_days_off: Iterable[date] = (),
        ignored_holidays: Iterable[str] = (),
    ) -> WorkCalendar:
        """Build from a code like "US" or "GB-ENG" (country-subdivision)."""
        country, _, subdiv = code.strip().upper().partition("-")
        try:
            holidays.country_holidays(country, subdiv=subdiv or None)
        except NotImplementedError as exc:
            raise ValueError(f"Unknown holiday calendar: {code!r}") from exc
        return cls(
            country=country,
            subdiv=subdiv or None,
            extra_days_off=frozenset(extra_days_off),
            ignored_holidays=frozenset(ignored_holidays),
        )

    def holiday_name(self, d: date) -> str | None:
        """Public-holiday name for d, or None. Ignored holidays (and their observed days) are skipped."""
        raw = _holiday_names(self.country, self.subdiv, d.year).get(d)
        if raw is None:
            return None
        kept = [n for n in raw.split("; ") if _base_name(n) not in self.ignored_holidays]
        return "; ".join(kept) or None

    def is_workday(self, d: date) -> bool:
        if d.weekday() >= 5 or d in self.extra_days_off:
            return False
        return self.holiday_name(d) is None

    def pto_cost(self, start: date, end: date) -> int:
        """Workdays in the inclusive range [start, end]."""
        return sum(1 for i in range((end - start).days + 1) if self.is_workday(start + i * ONE_DAY))

    def weekday_days_off(self, start: date, end: date) -> tuple[str, ...]:
        """Names of the weekday holidays / company days off in [start, end], in date order, de-duplicated."""
        names: list[str] = []
        for i in range((end - start).days + 1):
            d = start + i * ONE_DAY
            if d.weekday() >= 5:
                continue
            if d in self.extra_days_off:
                name = "Company day off"
            else:
                name = self.holiday_name(d)
            if name and name not in names:
                names.append(name)
        return tuple(names)
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_calendar.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/calendar.py tests/core/test_calendar.py
git commit -m "feat(core): work calendar with holidays, company days off, ignored holidays" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Trip shapes

**Files:**
- Create: `ptopilot/core/shapes.py`
- Test: `tests/core/test_shapes.py`

**Interfaces:**
- Consumes: `WorkCalendar`, `ONE_DAY` from `ptopilot.core.calendar`.
- Produces: `TripShape(depart_date: date, return_date: date, pto_cost: int, evening_departure: bool = False, days_off: tuple[str, ...] = ())` (frozen, hashable) with properties `days_away: int` (inclusive) and `efficiency: float` (= days_away / max(pto_cost, 0.5)); `is_departure_day(cal, d) -> bool`; `is_return_day(cal, d) -> bool`; `generate_shapes(cal, window_start, window_end, max_days_away, friday_evening=False, slack_days=2) -> list[TripShape]` (raises `ValueError` on a reversed window).

Rule (spec §6.2): you **depart** on the first day of an off-block (Sat) or the last workday before one (Fri, or the Wed before Thanksgiving), and **return** on the last day of an off-block (Sun) or the first workday after one (Mon). That excludes Wed→Thu shapes by construction.

- [ ] **Step 1: Write the failing test** `tests/core/test_shapes.py`

```python
from datetime import date

import pytest

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.shapes import TripShape, generate_shapes

US = WorkCalendar.from_code("US")
FRI, SAT, SUN, MON = 4, 5, 6, 0


def find(shapes, depart, ret, evening=False):
    matches = [
        s
        for s in shapes
        if s.depart_date == depart and s.return_date == ret and s.evening_departure == evening
    ]
    assert len(matches) == 1, f"expected exactly one {depart}->{ret} evening={evening}"
    return matches[0]


def test_days_away_and_efficiency():
    s = TripShape(date(2027, 8, 7), date(2027, 8, 15), pto_cost=5)
    assert s.days_away == 9
    assert s.efficiency == pytest.approx(1.8)
    assert TripShape(date(2027, 8, 7), date(2027, 8, 8), pto_cost=0).efficiency == 4.0


def test_ordinary_weeks_only_leave_fri_sat_and_return_sun_mon():
    # August 2027 has no US holidays.
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert shapes
    assert {s.depart_date.weekday() for s in shapes} <= {FRI, SAT}
    assert {s.return_date.weekday() for s in shapes} <= {SUN, MON}


def test_wed_to_thu_shapes_never_appear():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert not any(s.depart_date == date(2027, 8, 4) for s in shapes)  # Wed
    assert not any(s.return_date == date(2027, 8, 12) for s in shapes)  # Thu


def test_memorial_day_stretch():
    shapes = generate_shapes(US, date(2027, 5, 24), date(2027, 6, 11), max_days_away=14)
    s = find(shapes, date(2027, 5, 29), date(2027, 6, 6))
    assert s.pto_cost == 4
    assert s.days_away == 9
    assert s.days_off == ("Memorial Day",)


def test_wednesday_departure_allowed_before_thanksgiving():
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 11, 26)])
    shapes = generate_shapes(cal, date(2027, 11, 20), date(2027, 11, 30), max_days_away=10)
    s = find(shapes, date(2027, 11, 24), date(2027, 11, 28))
    assert s.pto_cost == 1


def test_zero_pto_weekend_is_a_shape():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert find(shapes, date(2027, 8, 7), date(2027, 8, 8)).pto_cost == 0


def test_friday_evening_variant_saves_one_pto_day():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16, friday_evening=True)
    regular = find(shapes, date(2027, 8, 6), date(2027, 8, 15))
    evening = find(shapes, date(2027, 8, 6), date(2027, 8, 15), evening=True)
    assert regular.pto_cost == 6
    assert evening.pto_cost == 5


def test_no_evening_variants_unless_enabled():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert not any(s.evening_departure for s in shapes)


def test_max_days_away_is_respected():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=9)
    assert max(s.days_away for s in shapes) <= 9


def test_dates_stay_within_window_plus_slack():
    start, end = date(2027, 8, 4), date(2027, 8, 25)
    shapes = generate_shapes(US, start, end, max_days_away=16, slack_days=2)
    assert min(s.depart_date for s in shapes) >= date(2027, 8, 2)
    assert max(s.return_date for s in shapes) <= date(2027, 8, 27)


def test_window_across_new_year_uses_both_years_holidays():
    shapes = generate_shapes(US, date(2027, 12, 18), date(2028, 1, 9), max_days_away=16)
    # Christmas (observed Fri Dec 24 2027) + New Year (observed Fri Dec 31 2027):
    # Sat Dec 18 -> Sun Jan 2 is 16 days for 8 PTO days.
    s = find(shapes, date(2027, 12, 18), date(2028, 1, 2))
    assert s.pto_cost == 8
    assert s.days_off == ("Christmas Day (observed)", "New Year's Day (observed)")


def test_reversed_window_is_rejected():
    with pytest.raises(ValueError):
        generate_shapes(US, date(2027, 8, 27), date(2027, 8, 2), max_days_away=16)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_shapes.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.shapes'`

- [ ] **Step 3: Create** `ptopilot/core/shapes.py`

```python
"""Trip shapes: realistic (depart, return) date pairs anchored on weekends and holidays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ptopilot.core.calendar import ONE_DAY, WorkCalendar


@dataclass(frozen=True)
class TripShape:
    depart_date: date
    return_date: date
    pto_cost: int
    evening_departure: bool = False
    days_off: tuple[str, ...] = ()

    @property
    def days_away(self) -> int:
        return (self.return_date - self.depart_date).days + 1

    @property
    def efficiency(self) -> float:
        return self.days_away / max(self.pto_cost, 0.5)


def is_departure_day(cal: WorkCalendar, d: date) -> bool:
    """First day of an off-block (e.g. Saturday), or the last workday before one (e.g. Friday)."""
    if cal.is_workday(d):
        return not cal.is_workday(d + ONE_DAY)
    return cal.is_workday(d - ONE_DAY)


def is_return_day(cal: WorkCalendar, d: date) -> bool:
    """Last day of an off-block (e.g. Sunday), or the first workday after one (e.g. Monday)."""
    if cal.is_workday(d):
        return not cal.is_workday(d - ONE_DAY)
    return cal.is_workday(d + ONE_DAY)


def generate_shapes(
    cal: WorkCalendar,
    window_start: date,
    window_end: date,
    max_days_away: int,
    friday_evening: bool = False,
    slack_days: int = 2,
) -> list[TripShape]:
    """All natural trip shapes whose depart and return fall in the window (± slack_days).

    With friday_evening, every shape departing on a workday also gets a variant that
    leaves after work that day: one less PTO day, evening_departure=True.
    """
    if window_end < window_start:
        raise ValueError(f"Window ends before it starts: {window_start} > {window_end}")
    first = window_start - slack_days * ONE_DAY
    last = window_end + slack_days * ONE_DAY
    days = [first + i * ONE_DAY for i in range((last - first).days + 1)]
    departs = [d for d in days if is_departure_day(cal, d)]
    returns = [d for d in days if is_return_day(cal, d)]

    shapes: list[TripShape] = []
    for dep in departs:
        for ret in returns:
            if ret <= dep:
                continue
            if (ret - dep).days + 1 > max_days_away:
                break
            pto = cal.pto_cost(dep, ret)
            days_off = cal.weekday_days_off(dep, ret)
            shapes.append(TripShape(dep, ret, pto, False, days_off))
            if friday_evening and cal.is_workday(dep):
                shapes.append(TripShape(dep, ret, pto - 1, True, days_off))
    return shapes
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_shapes.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/shapes.py tests/core/test_shapes.py
git commit -m "feat(core): generate natural trip shapes anchored on weekends and holidays" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Shape constraints and top-N selection

**Files:**
- Create: `ptopilot/core/selection.py`
- Test: `tests/core/test_selection.py`

**Interfaces:**
- Consumes: `TripShape` from `ptopilot.core.shapes`.
- Produces: `ShapeConstraints(min_days_away: int, max_days_away: int, min_ground_days: int, max_ground_days: int, travel_overhead_days: float, pto_available: int)`; `ground_days(shape, travel_overhead_days) -> float`; `satisfies(shape, c) -> bool`; `select_top(shapes: Iterable[TripShape], n=6, max_per_length=2) -> list[TripShape]`.

- [ ] **Step 1: Write the failing test** `tests/core/test_selection.py`

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_selection.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.selection'`

- [ ] **Step 3: Create** `ptopilot/core/selection.py`

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


def select_top(shapes: Iterable[TripShape], n: int = 6, max_per_length: int = 2) -> list[TripShape]:
    """Best n shapes by PTO efficiency, at most max_per_length per trip length, and at most
    one per (depart, return) pair so an evening variant never duplicates its regular twin.

    Ties: fewer PTO days, then earlier departure, then the non-evening variant.
    """
    ranked = sorted(
        shapes,
        key=lambda s: (-s.efficiency, s.pto_cost, s.depart_date, s.evening_departure),
    )
    picked: list[TripShape] = []
    per_length: Counter[int] = Counter()
    seen_dates: set[tuple[date, date]] = set()
    for s in ranked:
        dates = (s.depart_date, s.return_date)
        if per_length[s.days_away] >= max_per_length or dates in seen_dates:
            continue
        picked.append(s)
        per_length[s.days_away] += 1
        seen_dates.add(dates)
        if len(picked) == n:
            break
    return picked
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_selection.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/selection.py tests/core/test_selection.py
git commit -m "feat(core): trip constraints and diverse top-N shape selection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Season table

**Files:**
- Create: `ptopilot/core/seasons.py`
- Test: `tests/core/test_seasons.py`

**Interfaces:**
- Consumes: `ONE_DAY` from `ptopilot.core.calendar`; `yaml`.
- Produces: type aliases `Rating = Literal['good','shoulder','avoid']`, `Tolerance = Literal['strict','normal','relaxed']`; `is_allowed(rating, tolerance) -> bool`; `trip_month(depart, return_) -> int`; `SeasonTable(ratings: dict[str, list[Rating]], notes: dict[str, dict[int, str]])` with `from_dict(data)`, `from_yaml(path)`, `rating(codes: Sequence[str], month) -> Rating` (first matching code wins, unknown → `'good'`), `note(codes, month) -> str | None`.

- [ ] **Step 1: Write the failing test** `tests/core/test_seasons.py`

```python
from datetime import date

import pytest

from ptopilot.core.seasons import SeasonTable, is_allowed, trip_month

TABLE = SeasonTable.from_dict(
    {
        "TH": {
            "months": [
                "good",
                "good",
                "shoulder",
                "shoulder",
                "shoulder",
                "shoulder",
                "shoulder",
                "shoulder",
                "avoid",
                "avoid",
                "good",
                "good",
            ],
            "notes": {9: "Wettest month"},
        }
    }
)


def test_rating_by_code_and_month():
    assert TABLE.rating(["TH"], 1) == "good"
    assert TABLE.rating(["TH"], 6) == "shoulder"
    assert TABLE.rating(["TH"], 9) == "avoid"


def test_rating_falls_back_through_codes():
    assert TABLE.rating(["BKK", "TH"], 9) == "avoid"


def test_unknown_destination_counts_as_good():
    assert TABLE.rating(["ZZZ"], 9) == "good"


def test_note_lookup():
    assert TABLE.note(["TH"], 9) == "Wettest month"
    assert TABLE.note(["TH"], 1) is None
    assert TABLE.note(["ZZZ"], 1) is None


def test_bad_season_entry_is_rejected():
    with pytest.raises(ValueError, match="XX"):
        SeasonTable.from_dict({"XX": {"months": ["good"] * 11}})
    with pytest.raises(ValueError):
        SeasonTable.from_dict({"XX": {"months": ["good"] * 11 + ["rainy"]}})


@pytest.mark.parametrize(
    "rating, tolerance, expected",
    [
        ("good", "strict", True),
        ("shoulder", "strict", False),
        ("shoulder", "normal", True),
        ("avoid", "normal", False),
        ("avoid", "relaxed", True),
    ],
)
def test_tolerance(rating, tolerance, expected):
    assert is_allowed(rating, tolerance) is expected


def test_trip_month_uses_majority_of_days():
    # Jun 26 - Jul 10: 5 days in June, 10 in July
    assert trip_month(date(2027, 6, 26), date(2027, 7, 10)) == 7


def test_trip_month_tie_goes_to_earlier_month():
    # Jun 27 - Jul 4: 4 days each
    assert trip_month(date(2027, 6, 27), date(2027, 7, 4)) == 6


def test_trip_month_across_new_year():
    # Dec 26 - Jan 9: 6 days in Dec, 9 in Jan
    assert trip_month(date(2027, 12, 26), date(2028, 1, 9)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_seasons.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.seasons'`

- [ ] **Step 3: Create** `ptopilot/core/seasons.py`

```python
"""Seasonal suitability per destination and month."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import yaml

from ptopilot.core.calendar import ONE_DAY

Rating = Literal["good", "shoulder", "avoid"]
Tolerance = Literal["strict", "normal", "relaxed"]

RATINGS: tuple[Rating, ...] = ("good", "shoulder", "avoid")
ALLOWED: dict[Tolerance, frozenset[Rating]] = {
    "strict": frozenset({"good"}),
    "normal": frozenset({"good", "shoulder"}),
    "relaxed": frozenset({"good", "shoulder", "avoid"}),
}


def is_allowed(rating: Rating, tolerance: Tolerance) -> bool:
    return rating in ALLOWED[tolerance]


def trip_month(depart: date, return_: date) -> int:
    """Calendar month holding most of the trip's days; ties go to the earlier month."""
    counts: Counter[tuple[int, int]] = Counter()
    for i in range((return_ - depart).days + 1):
        d = depart + i * ONE_DAY
        counts[(d.year, d.month)] += 1
    best = max(counts.values())
    return min(ym for ym, n in counts.items() if n == best)[1]


@dataclass
class SeasonTable:
    """ratings[code] is a 12-item list (Jan..Dec); notes[code] maps month -> short note."""

    ratings: dict[str, list[Rating]]
    notes: dict[str, dict[int, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> SeasonTable:
        ratings: dict[str, list[Rating]] = {}
        notes: dict[str, dict[int, str]] = {}
        for code, entry in data.items():
            months = list(entry["months"])
            if len(months) != 12 or any(m not in RATINGS for m in months):
                raise ValueError(f"Season entry {code!r} needs 12 ratings from {RATINGS}")
            ratings[code] = months
            notes[code] = {int(k): str(v) for k, v in (entry.get("notes") or {}).items()}
        return cls(ratings, notes)

    @classmethod
    def from_yaml(cls, path: Path) -> SeasonTable:
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def rating(self, codes: Sequence[str], month: int) -> Rating:
        """Rating from the first code that has an entry (e.g. city, then country). Unknown -> "good"."""
        for code in codes:
            if code in self.ratings:
                return self.ratings[code][month - 1]
        return "good"

    def note(self, codes: Sequence[str], month: int) -> str | None:
        for code in codes:
            if code in self.ratings:
                return self.notes.get(code, {}).get(month)
        return None
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_seasons.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/seasons.py tests/core/test_seasons.py
git commit -m "feat(core): season ratings, tolerance filter, majority trip month" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Geography and bundled data files

**Files:**
- Create: `ptopilot/core/geo.py`
- Create: `ptopilot/data/__init__.py`, `ptopilot/data/geo.yaml`, `ptopilot/data/seasons.yaml`
- Test: `tests/core/test_geo.py`

**Interfaces:**
- Consumes: `SeasonTable` from Task 5 (for `load_seasons`).
- Produces: `UnknownCodeError(KeyError)`; `Airport(code, country, zone)`; `Destination(code, name, kind, airports: tuple[str, ...], country, zone)`; `TravelRule(overhead_days: float, min_trip_days: int)`; `Geo.from_dict(data)`, `Geo.from_yaml(path)`, `.airport(code) -> Airport`, `.destination(code) -> Destination`, `.travel_rule(origin_airport: str, dest: Destination) -> TravelRule`, `.is_international(origin_airport, dest) -> bool`; `ptopilot.data.load_geo() -> Geo`, `ptopilot.data.load_seasons() -> SeasonTable`.

The season ratings below are a hand-written starting point (Thailand's Sep/Oct monsoon is `avoid`). Plan 4 adds a generator script to draft more. Check them against your own travel knowledge before relying on them.

- [ ] **Step 1: Write the failing test** `tests/core/test_geo.py`

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_geo.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.geo'`

- [ ] **Step 3: Create** `ptopilot/core/geo.py`

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
    kind: str  # "city" or "region"
    airports: tuple[str, ...]
    country: str
    zone: str


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
            missing = [c for c in codes if c not in airports]
            if missing:
                raise ValueError(f"Destination {code!r} uses unknown airports {missing}")
            first = airports[codes[0]]
            destinations[code] = Destination(code, d["name"], d["kind"], codes, first.country, first.zone)
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

- [ ] **Step 4: Create** `ptopilot/data/__init__.py`

```python
"""Bundled reference data (geography, seasons)."""

from pathlib import Path

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable

DATA_DIR = Path(__file__).resolve().parent


def load_geo() -> Geo:
    return Geo.from_yaml(DATA_DIR / "geo.yaml")


def load_seasons() -> SeasonTable:
    return SeasonTable.from_yaml(DATA_DIR / "seasons.yaml")
```

- [ ] **Step 5: Create** `ptopilot/data/geo.yaml`

```yaml
# Seed geography. Extend as friends add destinations.
# zone: coarse region used for travel-time rules; country: ISO 3166 alpha-2.
airports:
  ORD: {country: US, zone: NA}
  MDW: {country: US, zone: NA}
  JFK: {country: US, zone: NA}
  EWR: {country: US, zone: NA}
  LGA: {country: US, zone: NA}
  SFO: {country: US, zone: NA}
  LAX: {country: US, zone: NA}
  LHR: {country: GB, zone: EUROPE}
  LGW: {country: GB, zone: EUROPE}
  LIS: {country: PT, zone: EUROPE}
  BKK: {country: TH, zone: SE_ASIA}
  HKT: {country: TH, zone: SE_ASIA}
  CNX: {country: TH, zone: SE_ASIA}
  HND: {country: JP, zone: E_ASIA}
  NRT: {country: JP, zone: E_ASIA}

destinations:
  TH: {name: Thailand, kind: region, airports: [BKK, HKT, CNX]}
  LIS: {name: Lisbon, kind: city, airports: [LIS]}
  TYO: {name: Tokyo, kind: city, airports: [HND, NRT]}

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
```

- [ ] **Step 6: Create** `ptopilot/data/seasons.yaml`

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
```

- [ ] **Step 7: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_geo.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 8: Commit**

```bash
git add ptopilot/core/geo.py ptopilot/data tests/core/test_geo.py
git commit -m "feat(core): geography model with seed airports, destinations, seasons" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Price baselines and deal levels

**Files:**
- Create: `ptopilot/core/stats.py`
- Test: `tests/core/test_stats.py`

**Interfaces:**
- Consumes: `ptopilot.config` (`COLD_START_N`, `MAD_TO_SIGMA`, `SIGMA_FLOOR_FRACTION`, `GOOD_DEAL_Z`, `GREAT_DEAL_Z`).
- Produces: `Baseline(median: float, sigma: float, n: int, confidence: Literal['normal','low'])`; `compute_baseline(prices: Sequence[float], google_range: tuple[float, float] | None = None) -> Baseline | None`; `z_score(price, baseline) -> float`; `deal_level(z) -> Literal['none','good','great']`; `length_bucket(days_away) -> Literal['short','week','long']`.

Spec §7 `baselines`: median plus MAD-based sigma (1.4826 × median absolute deviation), floored at 3% of the median. With under 15 prices, blend toward Google's typical range with weight n/15 and mark confidence `low`. The *Google range ignored once history is enough* test pins the hand-off.

- [ ] **Step 1: Write the failing test** `tests/core/test_stats.py`

```python
import pytest

from ptopilot.core.stats import Baseline, compute_baseline, deal_level, length_bucket, z_score


def test_no_data_means_no_baseline():
    assert compute_baseline([]) is None


def test_robust_median_and_mad_sigma():
    b = compute_baseline([100, 110, 90, 105, 95] * 4)
    assert b.median == 100
    assert b.sigma == pytest.approx(1.4826 * 5)
    assert (b.n, b.confidence) == (20, "normal")


def test_one_outlier_barely_moves_the_baseline():
    b = compute_baseline([100, 110, 90, 105, 95] * 4 + [5000])
    assert b.median == 100
    assert b.sigma == pytest.approx(1.4826 * 5)


def test_sigma_floor_when_prices_never_move():
    b = compute_baseline([500] * 20)
    assert b.sigma == pytest.approx(15)  # 3% of 500


def test_cold_start_without_google_uses_own_data_with_low_confidence():
    b = compute_baseline([400, 420, 380])
    assert b.median == 400
    assert b.confidence == "low"


def test_cold_start_blends_toward_google_typical_range():
    b = compute_baseline([400] * 5, google_range=(300, 600))
    # weight = 5/15: median = 1/3*400 + 2/3*450; sigma = 1/3*0 + 2/3*150
    assert b.median == pytest.approx(433.333, abs=0.01)
    assert b.sigma == pytest.approx(100)
    assert b.confidence == "low"


def test_google_range_alone_is_a_baseline():
    b = compute_baseline([], google_range=(300, 500))
    assert (b.median, b.sigma, b.n, b.confidence) == (400, 100, 0, "low")


def test_google_range_ignored_once_history_is_enough():
    b = compute_baseline([100, 110, 90, 105, 95] * 3, google_range=(1000, 2000))
    assert b.median == 100
    assert b.confidence == "normal"


def test_z_score():
    assert z_score(80, Baseline(100, 10, 20, "normal")) == -2.0


@pytest.mark.parametrize(
    "z, level",
    [(-0.99, "none"), (-1.0, "good"), (-1.49, "good"), (-1.5, "great"), (-3, "great"), (0.5, "none")],
)
def test_deal_level_thresholds(z, level):
    assert deal_level(z) == level


@pytest.mark.parametrize(
    "days, bucket", [(2, "short"), (5, "short"), (6, "week"), (10, "week"), (11, "long")]
)
def test_length_bucket(days, bucket):
    assert length_bucket(days) == bucket
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_stats.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.stats'`

- [ ] **Step 3: Create** `ptopilot/core/stats.py`

```python
"""Price baselines (robust median / MAD) and deal classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import Literal

from ptopilot import config

Confidence = Literal["normal", "low"]
DealLevel = Literal["none", "good", "great"]
LengthBucket = Literal["short", "week", "long"]


@dataclass(frozen=True)
class Baseline:
    median: float
    sigma: float
    n: int
    confidence: Confidence


def compute_baseline(
    prices: Sequence[float],
    google_range: tuple[float, float] | None = None,
) -> Baseline | None:
    """Typical price and spread for a route.

    With fewer than COLD_START_N prices, blends toward Google's typical range (if given)
    with weight n / COLD_START_N, and marks confidence "low". Returns None with no data at all.
    """
    n = len(prices)
    if n == 0 and google_range is None:
        return None

    if n:
        m = median(prices)
        s = config.MAD_TO_SIGMA * median(abs(p - m) for p in prices)
    else:
        m = s = 0.0

    if n < config.COLD_START_N and google_range is not None:
        low, high = google_range
        w = n / config.COLD_START_N
        m = w * m + (1 - w) * (low + high) / 2
        s = w * s + (1 - w) * (high - low) / 2

    s = max(s, config.SIGMA_FLOOR_FRACTION * m)
    confidence: Confidence = "normal" if n >= config.COLD_START_N else "low"
    return Baseline(median=m, sigma=s, n=n, confidence=confidence)


def z_score(price: float, baseline: Baseline) -> float:
    return (price - baseline.median) / baseline.sigma


def deal_level(z: float) -> DealLevel:
    if z <= config.GREAT_DEAL_Z:
        return "great"
    if z <= config.GOOD_DEAL_Z:
        return "good"
    return "none"


def length_bucket(days_away: int) -> LengthBucket:
    if days_away <= 5:
        return "short"
    if days_away <= 10:
        return "week"
    return "long"
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_stats.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/stats.py tests/core/test_stats.py
git commit -m "feat(core): robust price baselines, cold-start blending, deal levels" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Go-now score

**Files:**
- Create: `ptopilot/core/scoring.py`
- Test: `tests/core/test_scoring.py`

**Interfaces:**
- Consumes: `ptopilot.config` (`GO_NOW_WEIGHTS`, `DEAL_Z_FOR_FULL_SCORE`, `WEATHER_SCORES`, `SWEET_SPOT_DAYS`, `OFF_SWEET_SPOT_TIMING`); `Rating` from `ptopilot.core.seasons`.
- Produces: `deal_component(z: float | None) -> float`; `efficiency_component(efficiency) -> float`; `timing_component(days_until_departure: int, international: bool) -> float`; `go_now(z, rating, efficiency, days_until_departure, international) -> int` (0–100).

- [ ] **Step 1: Write the failing test** `tests/core/test_scoring.py`

```python
import pytest

from ptopilot.core.scoring import deal_component, efficiency_component, go_now, timing_component


def test_perfect_trip_scores_100():
    assert go_now(z=-2.5, rating="good", efficiency=3.0, days_until_departure=60, international=True) == 100


def test_poor_trip_scores_low():
    # 0.5*0 + 0.2*0.2 + 0.2*0 + 0.1*0.5 = 0.09
    assert go_now(z=0.0, rating="avoid", efficiency=1.0, days_until_departure=10, international=True) == 9


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

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_scoring.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.scoring'`

- [ ] **Step 3: Create** `ptopilot/core/scoring.py`

```python
"""The 0-100 "go now" score combining deal strength, weather, PTO efficiency, and timing."""

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


def timing_component(days_until_departure: int, international: bool) -> float:
    lo, hi = config.SWEET_SPOT_DAYS["international" if international else "domestic"]
    return 1.0 if lo <= days_until_departure <= hi else config.OFF_SWEET_SPOT_TIMING


def go_now(
    z: float | None,
    rating: Rating,
    efficiency: float,
    days_until_departure: int,
    international: bool,
) -> int:
    w = config.GO_NOW_WEIGHTS
    total = (
        w["deal"] * deal_component(z)
        + w["weather"] * config.WEATHER_SCORES[rating]
        + w["efficiency"] * efficiency_component(efficiency)
        + w["timing"] * timing_component(days_until_departure, international)
    )
    return round(100 * total)
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_scoring.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/scoring.py tests/core/test_scoring.py
git commit -m "feat(core): go-now score from deal, weather, PTO efficiency, timing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Itinerary planner

**Files:**
- Create: `ptopilot/core/planner.py`
- Test: `tests/core/test_planner.py`

**Interfaces:**
- Consumes: `WorkCalendar` (Task 2), `generate_shapes`/`TripShape` (Task 3), `ShapeConstraints`/`satisfies`/`select_top` (Task 4), `SeasonTable`/`trip_month`/`is_allowed` (Task 5), `Geo` and `load_geo`/`load_seasons` (Task 6), `ptopilot.config`.
- Produces (used by Plan 3's `expand` stage): `Window(start, end)`; `TravelerProfile(home_airports: tuple[str, ...], calendar: WorkCalendar, pto_available: int, min_trip_days: int, max_trip_days: int, weather_tolerance: Tolerance = 'normal', friday_evening_departure: bool = False)`; `TrackerSpec(destination_code, min_stay_days, max_stay_days)`; `PlannedItinerary(origin, dest_airport, destination_code, shape: TripShape, month: int, season_rating: Rating)`; `plan_itineraries(profile, tracker, windows, geo, seasons, top_n=6) -> list[PlannedItinerary]`.

Order matters (spec §6.4): constraints → season filter → top-N → fan out across the destination's airports, deduplicating across overlapping windows. Running the season filter *before* top-N keeps the six slots from being spent on monsoon dates.

- [ ] **Step 1: Write the failing test** `tests/core/test_planner.py`

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/core/test_planner.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.core.planner'`

- [ ] **Step 3: Create** `ptopilot/core/planner.py`

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
    dest_airport: str
    destination_code: str
    shape: TripShape
    month: int
    season_rating: Rating


def plan_itineraries(
    profile: TravelerProfile,
    tracker: TrackerSpec,
    windows: Sequence[Window],
    geo: Geo,
    seasons: SeasonTable,
    top_n: int = config.TOP_SHAPES_PER_WINDOW,
) -> list[PlannedItinerary]:
    """For each window and home airport: generate shapes, apply limits and season filter,
    keep the top_n, then fan out across the destination's airports. Duplicates from
    overlapping windows are dropped."""
    dest = geo.destination(tracker.destination_code)
    season_codes = (dest.code, dest.country)
    pto_available = max(profile.pto_available, 0)
    out: list[PlannedItinerary] = []
    seen: set[tuple[str, str, TripShape]] = set()

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

            for s in select_top(season_of, n=top_n, max_per_length=config.MAX_SHAPES_PER_LENGTH):
                month, rating = season_of[s]
                for airport in dest.airports:
                    key = (origin, airport, s)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(PlannedItinerary(origin, airport, dest.code, s, month, rating))
    return out
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_planner.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit**

```bash
git add ptopilot/core/planner.py tests/core/test_planner.py
git commit -m "feat(core): plan itineraries from profile, tracker, and windows" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Final check

- [ ] Run the whole suite: `.venv/Scripts/python -m pytest -q`. Expected: **105 passed**.
- [ ] Push to GitHub (if a remote is set up) and confirm the `ci` workflow is green.
- [ ] Sanity-print the Thailand example to see what Plan 3 will price:

```bash
.venv/Scripts/python -c "from datetime import date; from ptopilot.core.calendar import WorkCalendar; from ptopilot.core.planner import *; from ptopilot.data import load_geo, load_seasons; p=TravelerProfile(('ORD',), WorkCalendar.from_code('US'), 10, 3, 16, 'normal', True); [print(s.depart_date, s.return_date, s.days_away, s.pto_cost, s.evening_departure, s.days_off) for s in sorted({i.shape for i in plan_itineraries(p, TrackerSpec('TH', 7, 12), [Window(date(2027,6,1), date(2027,6,30)), Window(date(2027,9,1), date(2027,9,30))], load_geo(), load_seasons())}, key=lambda s: s.depart_date)]"
```

Expected: about five June trips (several using the Juneteenth long weekend, most as Friday-evening departures) and **no September trips**, because of the monsoon rating.
