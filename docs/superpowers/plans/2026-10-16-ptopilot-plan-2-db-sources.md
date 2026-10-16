# ptopilot Plan 2: Database and Fare Sources

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Postgres persistence for every spec §5 table (SQLAlchemy models plus an Alembic migration), and three fare-source adapters behind two small interfaces: Travelpayouts (cached month scans), Google Flights via `fast-flights` (live exact-date checks), and SerpApi (fallback plus Google's typical price range). All tested without network access.

**Architecture:**
- `ptopilot/sources/` holds provider adapters. They import only `sources/base.py`, `httpx` and `fast_flights`, never `db/` or `core/`.
- `ptopilot/db/` holds the models, the engine/session helpers and the Alembic migrations.
- `ptopilot/settings.py` reads secrets and the database URL from the environment.
- Plan 3's pipeline will connect sources, core and the database.

**Tech Stack:** SQLAlchemy 2.x, Alembic, psycopg 3, httpx, fast-flights 3.1, pytest with `httpx.MockTransport`, Postgres 17 (local private server on port 5433; a `postgres:17` service container in CI).

**Spec:** [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](../specs/2026-10-16-ptopilot-design.md), §3 (fare sources) and §5 (data model, including the Plan 2 implementation notes), plus the connection settings in §2.

## Global Constraints

- Python `>=3.12`. New runtime dependencies: `sqlalchemy>=2.0`, `alembic>=1.13`, `psycopg[binary]>=3.2`, `httpx>=0.27`, `fast-flights>=3.1,<4`, `typing_extensions>=4.12` (fast-flights 3.1.0 imports it without declaring it).
- `ptopilot/core/` is not modified by this plan.
- `ptopilot/sources/` never imports `db/` or `core/`. `ptopilot/db/` imports only `settings`.
- Secrets come only from environment variables (`DATABASE_URL`, `TRAVELPAYOUTS_TOKEN`, `SERPAPI_KEY`) and are never committed.
- Default `pytest` runs never touch the network. Tests that hit real sources carry `@pytest.mark.live`.
- Database tests skip when the test database is unreachable, unless `PTOPILOT_REQUIRE_DB` is set. CI sets it.
- `ruff check .` and `ruff format --check .` must pass.
- **Work directly on `main`. Every task ends with a commit and a `git push`** (the user's standing preference for this repo). Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- All commands run from `C:\Users\nickd\dev\ptopilot` using `.venv/Scripts/python`.

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **Database unreachable** → fails within about 15 s with an `OperationalError` instead of hanging forever. Without a timeout, psycopg on Windows waits forever on an unreachable server. *Task 6: `test_unreachable_database_fails_fast_instead_of_hanging`.*
2. **A source returns an HTTP error, an HTML page, or a quota-exhausted JSON body** → `SourceUnavailable` with a short snippet, never a raw crash. *Tasks 3 and 5: `test_failures_raise_source_unavailable`; Task 4: `test_any_library_failure_becomes_source_unavailable`.*
3. **A late-evening departure with a timezone offset** → the departure date stays local, not shifted to the next UTC day. *Task 3: `test_departure_date_is_local_not_utc`.*
4. **A Neon-style `postgresql://…?sslmode=require` URL** → rewritten for the psycopg driver with its query string intact. *Task 1: `test_database_url_gets_psycopg_driver`.*
5. **`models.py` edited without a new migration** → a test fails. *Task 6: `test_models_and_migrations_agree`.*

## Notes from verification (2026-10-16)

- A live `fast-flights` query (ORD⇄LIS) returned 7 options. The price is the **round-trip total**, and the details cover the **outbound legs only**, with no flight numbers. The recorded response is the Task 4 fixture.
- The Travelpayouts and SerpApi fixtures are **built from documented field lists**, since no API keys exist yet. Swap in real recordings once keys are available.
- Postgres on this machine: the installed `postgresql-x64-17` service's admin password is unknown. Plan 2 instead uses a **private server in `.pgdata/` on port 5433** with no password, started from the same binaries. It was already created and running during verification. Task 6, Step 1 recreates it if it's missing.

## File structure

```
pyproject.toml                       # + db/http/source dependencies
.gitignore                           # + .pgdata/
README.md                            # dev setup, local database, tests, configuration
.github/workflows/ci.yml             # + postgres:17 service, PTOPILOT_REQUIRE_DB, Node-24 action versions
alembic.ini                          # migrations config; URL comes from env, never this file
ptopilot/
  settings.py                        # Settings.from_env, normalize_database_url, DEV_DATABASE_URL
  sources/
    __init__.py
    base.py                          # FareQuote, ExactQuery, FlightOption, ExactResult, SourceUnavailable, protocols, snippet
    travelpayouts.py                 # TravelpayoutsSource, parse_prices_for_dates
    google_flights.py                # GoogleFlightsSource, parse_flights (fast-flights)
    serpapi.py                       # SerpApiSource, parse_google_flights
  db/
    __init__.py
    models.py                        # Base + 13 tables
    session.py                       # make_engine, session_scope, CONNECT_TIMEOUT_S
    migrations/
      env.py
      script.py.mako                 # Alembic's stock template
      versions/0001_initial_schema.py  # autogenerated
tests/
  test_settings.py
  sources/{__init__,test_base,test_travelpayouts,test_google_flights,test_serpapi}.py
  sources/fixtures/*.json
  db/{__init__,conftest,test_models,test_session,test_migrations}.py
```

---

### Task 1: Dependencies, settings, CI database, README

**Files:**
- Modify: `pyproject.toml` (dependencies), `.gitignore` (+ `.pgdata/`), `.github/workflows/ci.yml`
- Create: `README.md`, `ptopilot/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `DEV_DATABASE_URL = 'postgresql+psycopg://ptopilot@localhost:5433/ptopilot'`; `normalize_database_url(url: str) -> str`; `Settings(database_url: str, travelpayouts_token: str = '', serpapi_key: str = '')` with `Settings.from_env(env: Mapping[str, str] = os.environ) -> Settings`.

The CI change adds a `postgres:17` service on port 5433 (so the tests' default URL works unchanged) and bumps `actions/checkout` to v5 and `actions/setup-python` to v6, fixing the Node 20 deprecation warning from the first CI run.

- [ ] **Step 1: Write the failing test** `tests/test_settings.py`

```python
import pytest

from ptopilot.settings import DEV_DATABASE_URL, Settings, normalize_database_url


def test_defaults_point_at_local_dev_database():
    s = Settings.from_env({})
    assert s.database_url == DEV_DATABASE_URL
    assert (s.travelpayouts_token, s.serpapi_key) == ("", "")


def test_reads_secrets_from_env():
    s = Settings.from_env({"TRAVELPAYOUTS_TOKEN": "t", "SERPAPI_KEY": "k"})
    assert (s.travelpayouts_token, s.serpapi_key) == ("t", "k")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "postgresql://u:p@ep-x.neon.tech/db?sslmode=require",
            "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require",
        ),
        ("postgres://u@h/db", "postgresql+psycopg://u@h/db"),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ],
)
def test_database_url_gets_psycopg_driver(raw, expected):
    assert normalize_database_url(raw) == expected
    assert Settings.from_env({"DATABASE_URL": raw}).database_url == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.settings'`

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
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "httpx>=0.27",
    "fast-flights>=3.1,<4",
    # fast-flights 3.1.0 imports typing_extensions without declaring it
    "typing_extensions>=4.12",
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
extend-exclude = ["docs"]

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
.pgdata/
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
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_USER: ptopilot
          POSTGRES_DB: ptopilot_test
          POSTGRES_HOST_AUTH_METHOD: trust
        ports:
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U ptopilot"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      PTOPILOT_REQUIRE_DB: "1"
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest
```

- [ ] **Step 6: Create** `README.md`

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

## Configuration

Environment variables (never committed): `DATABASE_URL` (defaults to the local dev database), `TRAVELPAYOUTS_TOKEN`, `SERPAPI_KEY`.
````

- [ ] **Step 7: Create** `ptopilot/settings.py`

```python
"""Runtime settings from environment variables. Secrets never live in the repo."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEV_DATABASE_URL = "postgresql+psycopg://ptopilot@localhost:5433/ptopilot"


def normalize_database_url(url: str) -> str:
    """Neon and most hosts give postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    travelpayouts_token: str = ""
    serpapi_key: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            database_url=normalize_database_url(env.get("DATABASE_URL") or DEV_DATABASE_URL),
            travelpayouts_token=env.get("TRAVELPAYOUTS_TOKEN", ""),
            serpapi_key=env.get("SERPAPI_KEY", ""),
        )
```

- [ ] **Step 8: Install the new dependencies**

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: ends with `Successfully installed …` and lists sqlalchemy, alembic, psycopg, httpx, fast-flights and typing_extensions (retry if pip prints `ConnectionResetError` retries and then fails).

- [ ] **Step 9: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 10: Commit and push**

```bash
git add pyproject.toml .gitignore .github/workflows/ci.yml README.md ptopilot/settings.py tests/test_settings.py
git commit -m "build: add db and fare-source dependencies, settings, CI postgres" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Then check CI: `& "C:\Program Files\GitHub CLI\gh.exe" run watch --exit-status` (PowerShell). Expected: the `ci` run passes with no Node 20 deprecation annotation.

---

### Task 2: Fare-source types

**Files:**
- Create: `ptopilot/sources/__init__.py` (empty), `ptopilot/sources/base.py`
- Create: `tests/sources/__init__.py` (empty)
- Test: `tests/sources/test_base.py`

**Interfaces:**
- Produces (used by Tasks 3–5 and Plan 3): `SourceUnavailable(Exception)`; `FareQuote(source, origin, dest_airport, depart_date, return_date: date | None, price: float, currency, airline=None, flight_number=None, stops=None, return_stops=None, duration_min=None, deep_link=None)`; `ExactQuery(origin, dest_airport, depart_date, return_date, currency='USD')`; `FlightOption(price, carrier, stops, duration_min, outbound_departure: datetime, flight_numbers: tuple[str, ...] = (), overnight_layover=False)`; `ExactResult(source, query, currency, options: tuple[FlightOption, ...], deep_link, typical_range: tuple[float, float] | None = None)` with `.cheapest() -> FlightOption | None`; protocols `MonthScanSource.month_scan(origin, dest_airport, month, market, currency) -> list[FareQuote]` and `ExactSearchSource.exact_search(query) -> ExactResult`; `snippet(text, limit=300) -> str`.

- [ ] **Step 1: Create the empty `tests/sources/__init__.py` first.**

- [ ] **Step 2: Write the failing test** `tests/sources/test_base.py`

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/sources/test_base.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.sources'`

- [ ] **Step 4: Create** `ptopilot/sources/base.py`

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
    dest_airport: str
    depart_date: date
    return_date: date
    currency: str = "USD"


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

    def exact_search(self, query: ExactQuery) -> ExactResult: ...


def snippet(text: str, limit: int = 300) -> str:
    """Single-line, truncated excerpt of a payload for error messages."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
```

- [ ] **Step 5: Supporting files**

Also create the empty `ptopilot/sources/__init__.py`.

- [ ] **Step 6: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/sources/test_base.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 7: Commit and push**

```bash
git add ptopilot/sources/__init__.py ptopilot/sources/base.py tests/sources/__init__.py tests/sources/test_base.py
git commit -m "feat(sources): shared fare-source types and interfaces" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Travelpayouts adapter (broad month scan)

**Files:**
- Create: `ptopilot/sources/travelpayouts.py`
- Create: `tests/sources/fixtures/travelpayouts_ORD_LIS_2027-06.json`
- Test: `tests/sources/test_travelpayouts.py`

**Interfaces:**
- Consumes: `FareQuote`, `SourceUnavailable`, `snippet` (Task 2).
- Produces: `API_URL`, `SITE`, `parse_prices_for_dates(payload: dict, origin: str, dest_airport: str) -> list[FareQuote]`, `TravelpayoutsSource(token: str, client: httpx.Client | None = None)` implementing `MonthScanSource` with `name = 'travelpayouts'`.

Endpoint `GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates` with header `X-Access-Token`. Fields per row: origin, destination, origin_airport, destination_airport, price, airline, flight_number, departure_at, return_at, transfers, return_transfers, duration, duration_to, duration_back, link (a path on aviasales.com). Without a token, the API returns HTTP 401 `Unauthorized`.

- [ ] **Step 1: Create fixture** `tests/sources/fixtures/travelpayouts_ORD_LIS_2027-06.json`

```json
{
  "success": true,
  "currency": "usd",
  "data": [
    {
      "origin": "CHI",
      "destination": "LIS",
      "origin_airport": "ORD",
      "destination_airport": "LIS",
      "price": 612,
      "airline": "TP",
      "flight_number": "246",
      "departure_at": "2027-06-11T18:15:00-05:00",
      "return_at": "2027-06-20T11:05:00+01:00",
      "transfers": 1,
      "return_transfers": 1,
      "duration": 1490,
      "duration_to": 760,
      "duration_back": 730,
      "link": "/search/CHI1106LIS20061?t=TP18153150001815321000000760ORDLIS"
    },
    {
      "origin": "CHI",
      "destination": "LIS",
      "origin_airport": "ORD",
      "destination_airport": "LIS",
      "price": 688,
      "airline": "UA",
      "flight_number": "960",
      "departure_at": "2027-06-04T16:40:00-05:00",
      "return_at": "2027-06-13T10:30:00+01:00",
      "transfers": 1,
      "return_transfers": 2,
      "duration": 1630,
      "duration_to": 805,
      "duration_back": 825,
      "link": "/search/CHI0406LIS13061?t=UA16409200001640929000000805ORDLIS"
    },
    {
      "origin": "CHI",
      "destination": "LIS",
      "origin_airport": "ORD",
      "destination_airport": "LIS",
      "price": 0,
      "airline": "XX",
      "flight_number": "1",
      "departure_at": "2027-06-05T10:00:00-05:00",
      "return_at": "2027-06-12T10:00:00+01:00",
      "transfers": 0,
      "return_transfers": 0,
      "duration": 900,
      "duration_to": 450,
      "duration_back": 450,
      "link": "/search/broken"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test** `tests/sources/test_travelpayouts.py`

```python
"""Fixture follows the documented prices_for_dates fields; swap for a real recording once a token exists."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from ptopilot.sources.base import SourceUnavailable
from ptopilot.sources.travelpayouts import API_URL, TravelpayoutsSource, parse_prices_for_dates

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "travelpayouts_ORD_LIS_2027-06.json").read_text())


def source_returning(status=200, body=None, text=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    return TravelpayoutsSource("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_maps_fields_and_skips_zero_prices():
    quotes = parse_prices_for_dates(FIXTURE, "ORD", "LIS")
    assert len(quotes) == 2
    q = quotes[0]
    assert (q.origin, q.dest_airport) == ("ORD", "LIS")
    assert (q.depart_date, q.return_date) == (date(2027, 6, 11), date(2027, 6, 20))
    assert (q.price, q.currency) == (612.0, "USD")
    assert (q.airline, q.flight_number, q.stops, q.return_stops) == ("TP", "TP 246", 1, 1)
    assert q.duration_min == 760
    assert q.deep_link.startswith("https://www.aviasales.com/search/CHI1106LIS20061")
    assert q.source == "travelpayouts"


def test_departure_date_is_local_not_utc():
    # 18:15 at -05:00 is 23:15 UTC same day; a late flight must not shift to the next day.
    late = {
        "success": True,
        "currency": "usd",
        "data": [{**FIXTURE["data"][0], "departure_at": "2027-06-11T23:30:00-05:00"}],
    }
    assert parse_prices_for_dates(late, "ORD", "LIS")[0].depart_date == date(2027, 6, 11)


def test_month_scan_sends_expected_request():
    seen = []
    src = source_returning(body=FIXTURE, seen=seen)
    quotes = src.month_scan("ORD", "LIS", date(2027, 6, 1), market="US", currency="USD")
    assert len(quotes) == 2
    req = seen[0]
    assert str(req.url).startswith(API_URL)
    assert req.headers["X-Access-Token"] == "tok"
    params = dict(req.url.params)
    assert params["departure_at"] == "2027-06"
    assert (params["origin"], params["destination"], params["market"], params["currency"]) == (
        "ORD",
        "LIS",
        "us",
        "usd",
    )
    assert params["one_way"] == "false"


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"status": 401, "text": "Unauthorized"}, "HTTP 401"),
        ({"status": 200, "text": "<html>oops</html>"}, "invalid JSON"),
        ({"status": 200, "body": {"success": False, "error": "quota"}}, "success=false"),
    ],
)
def test_failures_raise_source_unavailable(kwargs, match):
    with pytest.raises(SourceUnavailable, match=match):
        source_returning(**kwargs).month_scan("ORD", "LIS", date(2027, 6, 1), "us", "usd")


def test_network_error_raises_source_unavailable():
    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    src = TravelpayoutsSource("tok", client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(SourceUnavailable, match="ConnectTimeout"):
        src.month_scan("ORD", "LIS", date(2027, 6, 1), "us", "usd")


def test_empty_token_is_rejected():
    with pytest.raises(ValueError, match="TRAVELPAYOUTS_TOKEN"):
        TravelpayoutsSource("")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/sources/test_travelpayouts.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.sources.travelpayouts'`

- [ ] **Step 4: Create** `ptopilot/sources/travelpayouts.py`

```python
"""Travelpayouts / Aviasales Data API: free cached fares, used for the broad month scan."""

from __future__ import annotations

from datetime import date, datetime

import httpx

from ptopilot.sources.base import FareQuote, SourceUnavailable, snippet

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"
TIMEOUT_S = 20


def parse_prices_for_dates(payload: dict, origin: str, dest_airport: str) -> list[FareQuote]:
    """prices_for_dates response -> FareQuotes. Rows with a missing or non-positive price are skipped."""
    if not payload.get("success", False):
        raise SourceUnavailable(f"travelpayouts: success=false: {snippet(str(payload))}")
    currency = str(payload.get("currency", "")).upper()
    quotes: list[FareQuote] = []
    for row in payload.get("data") or []:
        price = row.get("price")
        if not isinstance(price, int | float) or price <= 0:
            continue
        try:
            depart = datetime.fromisoformat(row["departure_at"]).date()
            ret = datetime.fromisoformat(row["return_at"]).date() if row.get("return_at") else None
        except (KeyError, ValueError) as exc:
            raise SourceUnavailable(f"travelpayouts: bad date in row: {snippet(str(row))}") from exc
        airline = row.get("airline") or None
        number = row.get("flight_number")
        link = row.get("link") or None
        quotes.append(
            FareQuote(
                source="travelpayouts",
                origin=row.get("origin_airport") or origin,
                dest_airport=row.get("destination_airport") or dest_airport,
                depart_date=depart,
                return_date=ret,
                price=float(price),
                currency=currency,
                airline=airline,
                flight_number=f"{airline} {number}" if airline and number else None,
                stops=row.get("transfers"),
                return_stops=row.get("return_transfers"),
                duration_min=row.get("duration_to"),
                deep_link=(link if link.startswith("http") else SITE + link) if link else None,
            )
        )
    return quotes


class TravelpayoutsSource:
    name = "travelpayouts"

    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise ValueError("Travelpayouts token is empty; set TRAVELPAYOUTS_TOKEN")
        self._token = token
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def month_scan(
        self, origin: str, dest_airport: str, month: date, market: str, currency: str
    ) -> list[FareQuote]:
        params = {
            "origin": origin,
            "destination": dest_airport,
            "departure_at": month.strftime("%Y-%m"),
            "one_way": "false",
            "direct": "false",
            "sorting": "price",
            "unique": "false",
            "market": market.lower(),
            "currency": currency.lower(),
            "limit": 1000,
        }
        try:
            resp = self._client.get(API_URL, params=params, headers={"X-Access-Token": self._token})
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"travelpayouts: {type(exc).__name__}: {exc}") from exc
        if resp.status_code != 200:
            raise SourceUnavailable(f"travelpayouts: HTTP {resp.status_code}: {snippet(resp.text)}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SourceUnavailable(f"travelpayouts: invalid JSON: {snippet(resp.text)}") from exc
        return parse_prices_for_dates(payload, origin, dest_airport)
```

- [ ] **Step 5: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/sources/test_travelpayouts.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 6: Commit and push**

```bash
git add ptopilot/sources/travelpayouts.py tests/sources/fixtures/travelpayouts_ORD_LIS_2027-06.json tests/sources/test_travelpayouts.py
git commit -m "feat(sources): Travelpayouts cached month-scan adapter" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 4: Google Flights adapter via fast-flights (live check)

**Files:**
- Create: `ptopilot/sources/google_flights.py`
- Create: `tests/sources/fixtures/google_flights_ORD_LIS_2027-06-11_2027-06-20.json` (real recording)
- Test: `tests/sources/test_google_flights.py`

**Interfaces:**
- Consumes: `ExactQuery`, `ExactResult`, `FlightOption`, `SourceUnavailable` (Task 2).
- Produces: `parse_flights(results: Sequence[Any]) -> tuple[FlightOption, ...]`; `GoogleFlightsSource(search: Callable[[ExactQuery], tuple[Sequence[Any], str]] = _default_search)` implementing `ExactSearchSource` with `name = 'google_flights'`.

fast-flights 3.1 API (checked by inspection): `create_query(flights=[FlightQuery(date, from_airport, to_airport), …], trip='round-trip', seat='economy', passengers=Passengers(adults=1), language, currency)` returns a `Query` with `.url()`. `get_flights(query)` returns a list of `Flights(type, price, airlines, flights=[SingleFlight(from_airport, to_airport, departure=SimpleDatetime(date=(y, m, d), time=(h, m)), arrival, duration, plane_type)], carbon)`, and raises `FlightsNotFound` when there are no results. Layover minutes are computed between consecutive segments; both times are local to the same airport, so the subtraction is exact. The fixture is the real response, saved with `dataclasses.asdict`.

**Fixture:** copy `google_flights_ORD_LIS_2027-06-11_2027-06-20.json` from the verification scratchpad (`C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p2\tests\sources\fixtures\`). If that is gone, re-record it with:

```bash
.venv/Scripts/python -c "import json, dataclasses; from fast_flights import FlightQuery, Passengers, create_query, get_flights; q = create_query(flights=[FlightQuery(date='2027-06-11', from_airport='ORD', to_airport='LIS'), FlightQuery(date='2027-06-20', from_airport='LIS', to_airport='ORD')], trip='round-trip', seat='economy', passengers=Passengers(adults=1), language='en-US', currency='USD'); json.dump([dataclasses.asdict(f) for f in get_flights(q)], open('tests/sources/fixtures/google_flights_ORD_LIS_2027-06-11_2027-06-20.json', 'w'), indent=1)"
```

A re-recording will have different prices. Update the numbers in `test_parse_real_response` and `test_multi_airline_carrier_is_joined` to match the new file, keeping the same assertions.

- [ ] **Step 1: Write the failing test** `tests/sources/test_google_flights.py`

```python
"""Fixture is a real fast-flights 3.1.0 response recorded 2026-10-16 for ORD<->LIS, Jun 11-20 2027."""

import json
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/sources/test_google_flights.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.sources.google_flights'`

- [ ] **Step 3: Create** `ptopilot/sources/google_flights.py`

```python
"""Live Google Flights prices via the unofficial `fast-flights` library. Free but fragile."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable


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

    def __init__(self, search: Callable[[ExactQuery], tuple[Sequence[Any], str]] = _default_search):
        self._search = search

    def exact_search(self, query: ExactQuery) -> ExactResult:
        try:
            results, url = self._search(query)
            options = parse_flights(results)
        except Exception as exc:  # the library scrapes HTML; any failure means "unavailable"
            raise SourceUnavailable(f"google_flights: {type(exc).__name__}: {exc}") from exc
        return ExactResult(
            source=self.name, query=query, currency=query.currency, options=options, deep_link=url
        )
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/sources/test_google_flights.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Run the live smoke test once by hand**

Run: `.venv/Scripts/python -m pytest tests/sources/test_google_flights.py -m live -v`
Expected: `test_live_google_flights_smoke PASSED`. If Google blocks or throttles the request, note it in the ledger. That's the Review Focus risk, not a code defect.

- [ ] **Step 6: Commit and push**

```bash
git add ptopilot/sources/google_flights.py tests/sources/fixtures/google_flights_ORD_LIS_2027-06-11_2027-06-20.json tests/sources/test_google_flights.py
git commit -m "feat(sources): live Google Flights adapter via fast-flights" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 5: SerpApi adapter (fallback + typical price range)

**Files:**
- Create: `ptopilot/sources/serpapi.py`
- Create: `tests/sources/fixtures/serpapi_ORD_LIS_2027-06-11_2027-06-20.json`
- Test: `tests/sources/test_serpapi.py`

**Interfaces:**
- Consumes: `ExactQuery`, `ExactResult`, `FlightOption`, `SourceUnavailable`, `snippet` (Task 2).
- Produces: `API_URL`, `parse_google_flights(payload: dict, query: ExactQuery) -> ExactResult`, `SerpApiSource(api_key: str, client: httpx.Client | None = None)` implementing `ExactSearchSource` with `name = 'serpapi'`.

Request: `GET https://serpapi.com/search.json?engine=google_flights&departure_id&arrival_id&outbound_date&return_date&type=1&currency&hl=en&api_key`. Options come from `best_flights + other_flights`. Each has `flights[]` (departure_airport.time `YYYY-MM-DD HH:MM`, airline, flight_number, duration), `layovers[]` (`overnight` flag), `total_duration` and `price`. `price_insights.typical_price_range` is `[low, high]`. The booking link is `search_metadata.google_flights_url`. Error responses carry an `error` key.

- [ ] **Step 1: Create fixture** `tests/sources/fixtures/serpapi_ORD_LIS_2027-06-11_2027-06-20.json`

```json
{
  "search_metadata": {
    "status": "Success",
    "google_flights_url": "https://www.google.com/travel/flights?hl=en&gl=us&curr=USD&tfs=CBwQAhoeEgoyMDI3LTA2LTEx"
  },
  "best_flights": [
    {
      "flights": [
        {
          "departure_airport": {"name": "Chicago O'Hare International Airport", "id": "ORD", "time": "2027-06-11 18:15"},
          "arrival_airport": {"name": "Newark Liberty International Airport", "id": "EWR", "time": "2027-06-11 21:30"},
          "duration": 135,
          "airline": "United",
          "flight_number": "UA 1234",
          "travel_class": "Economy"
        },
        {
          "departure_airport": {"name": "Newark Liberty International Airport", "id": "EWR", "time": "2027-06-11 23:00"},
          "arrival_airport": {"name": "Humberto Delgado Airport", "id": "LIS", "time": "2027-06-12 10:45"},
          "duration": 405,
          "airline": "TAP Air Portugal",
          "flight_number": "TP 202",
          "travel_class": "Economy"
        }
      ],
      "layovers": [{"duration": 90, "name": "Newark Liberty International Airport", "id": "EWR"}],
      "total_duration": 630,
      "price": 905,
      "type": "Round trip",
      "departure_token": "WyJDalJJ"
    }
  ],
  "other_flights": [
    {
      "flights": [
        {
          "departure_airport": {"name": "Chicago O'Hare International Airport", "id": "ORD", "time": "2027-06-11 16:00"},
          "arrival_airport": {"name": "Toronto Pearson International Airport", "id": "YYZ", "time": "2027-06-11 18:40"},
          "duration": 100,
          "airline": "Air Canada",
          "flight_number": "AC 512",
          "travel_class": "Economy"
        },
        {
          "departure_airport": {"name": "Toronto Pearson International Airport", "id": "YYZ", "time": "2027-06-12 07:30"},
          "arrival_airport": {"name": "Humberto Delgado Airport", "id": "LIS", "time": "2027-06-12 19:10"},
          "duration": 460,
          "airline": "Air Canada",
          "flight_number": "AC 830",
          "travel_class": "Economy"
        }
      ],
      "layovers": [{"duration": 770, "name": "Toronto Pearson International Airport", "id": "YYZ", "overnight": true}],
      "total_duration": 1330,
      "price": 840,
      "type": "Round trip",
      "departure_token": "WyJDalJK"
    }
  ],
  "price_insights": {
    "lowest_price": 840,
    "price_level": "typical",
    "typical_price_range": [780, 1150],
    "price_history": [[1792800000, 980], [1792886400, 960]]
  }
}
```

- [ ] **Step 2: Write the failing test** `tests/sources/test_serpapi.py`

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/sources/test_serpapi.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.sources.serpapi'`

- [ ] **Step 4: Create** `ptopilot/sources/serpapi.py`

```python
"""SerpApi Google Flights: quota-limited fallback that also returns Google's typical price range."""

from __future__ import annotations

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


def parse_google_flights(payload: dict, query: ExactQuery) -> ExactResult:
    if "error" in payload:
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

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("SerpApi key is empty; set SERPAPI_KEY")
        self._key = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def exact_search(self, query: ExactQuery) -> ExactResult:
        params = {
            "engine": "google_flights",
            "departure_id": query.origin,
            "arrival_id": query.dest_airport,
            "outbound_date": query.depart_date.isoformat(),
            "return_date": query.return_date.isoformat(),
            "type": 1,
            "currency": query.currency,
            "hl": "en",
            "api_key": self._key,
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

- [ ] **Step 5: Run tests and lint to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/sources/test_serpapi.py -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 6: Commit and push**

```bash
git add ptopilot/sources/serpapi.py tests/sources/fixtures/serpapi_ORD_LIS_2027-06-11_2027-06-20.json tests/sources/test_serpapi.py
git commit -m "feat(sources): SerpApi Google Flights fallback adapter" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 6: Database models, sessions, and initial migration

**Files:**
- Create: `alembic.ini`, `ptopilot/db/__init__.py` (empty), `ptopilot/db/models.py`, `ptopilot/db/session.py`
- Create: `ptopilot/db/migrations/env.py`, `ptopilot/db/migrations/script.py.mako`, `ptopilot/db/migrations/versions/0001_initial_schema.py` (autogenerated)
- Create: `tests/db/__init__.py` (empty), `tests/db/conftest.py`
- Test: `tests/db/test_models.py`, `tests/db/test_session.py`, `tests/db/test_migrations.py`

**Interfaces:**
- Consumes: `normalize_database_url`, `Settings` (Task 1).
- Produces (used by Plan 3 onward): `Base` and models `User, Invite, TravelWindow, Tracker, TrackerExclusion, RouteQuery, TrackerRouteLink, PriceObservation, RouteBaseline, Candidate, DigestSend, PipelineRun, SourceBudget` (columns exactly as in `models.py` below); `make_engine(database_url) -> Engine` (pre-ping, `connect_timeout=CONNECT_TIMEOUT_S`); `session_scope(engine)` context manager; test fixtures `engine` (session-scoped, migrated to head) and `session` (rolled back per test).

- [ ] **Step 1: Make sure the local database server is running**

Run (PowerShell): `& "C:\Program Files\PostgreSQL\17\bin\pg_isready.exe" -h localhost -p 5433`
Expected: `localhost:5433 - accepting connections`.

If it reports `no response` and `.pgdata/` exists, start it: `& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D .pgdata -o "-p 5433" -l .pgdata/server.log start`. If `.pgdata/` doesn't exist, run the three one-time commands from the README's *Local database* section. Note: from Git Bash, `pg_ctl start` keeps the shell attached; run it from PowerShell or in the background.

- [ ] **Step 2: Create the empty `tests/db/__init__.py` first.**

- [ ] **Step 3: Write the failing test** `tests/db/conftest.py`

```python
"""Database fixtures. Uses PTOPILOT_TEST_DATABASE_URL, defaulting to the local dev server on port 5433.

Tests skip when the database is unreachable, unless PTOPILOT_REQUIRE_DB is set (CI sets it).
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ptopilot.db.session import make_engine
from ptopilot.settings import normalize_database_url

TEST_URL = normalize_database_url(
    os.environ.get("PTOPILOT_TEST_DATABASE_URL", "postgresql://ptopilot@localhost:5433/ptopilot_test")
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def engine():
    eng = make_engine(TEST_URL)
    try:
        with eng.connect():
            pass
    except OperationalError as exc:
        if os.environ.get("PTOPILOT_REQUIRE_DB"):
            raise
        pytest.skip(
            f"test database unavailable ({type(exc).__name__}); start it or set PTOPILOT_TEST_DATABASE_URL"
        )
    cfg = alembic_config(TEST_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """A session whose work is rolled back after the test, even if the test commits."""
    with engine.connect() as conn:
        outer = conn.begin()
        s = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            s.close()
            outer.rollback()
```

- [ ] **Step 4: Write the failing test** `tests/db/test_models.py`

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
            origin="ORD", dest_airport="LIS", depart_date=date(2027, 6, 11), return_date=date(2027, 6, 20)
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

- [ ] **Step 5: Write the failing test** `tests/db/test_session.py`

```python
import time

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from ptopilot.db import session as session_module
from ptopilot.db.models import Invite
from ptopilot.db.session import make_engine, session_scope


def test_unreachable_database_fails_fast_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(session_module, "CONNECT_TIMEOUT_S", 2)
    start = time.monotonic()
    with pytest.raises(OperationalError):
        make_engine("postgresql+psycopg://ptopilot@127.0.0.1:5999/nope").connect()
    assert time.monotonic() - start < 10


def emails(engine):
    with session_scope(engine) as s:
        return set(s.scalars(select(Invite.email)))


def test_session_scope_commits_on_success(engine):
    try:
        with session_scope(engine) as s:
            s.add(Invite(email="commit@example.com"))
        assert "commit@example.com" in emails(engine)
    finally:
        with session_scope(engine) as s:
            s.execute(delete(Invite).where(Invite.email == "commit@example.com"))


def test_session_scope_rolls_back_on_error(engine):
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        s.add(Invite(email="rollback@example.com"))
        s.flush()
        raise RuntimeError("boom")
    assert "rollback@example.com" not in emails(engine)
```

- [ ] **Step 6: Write the failing test** `tests/db/test_migrations.py`

```python
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from ptopilot.db.models import Base


def test_upgrade_creates_every_model_table(engine):
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_models_and_migrations_agree(engine):
    """Fails if someone edits models.py without generating a migration."""
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/db -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.db'`

- [ ] **Step 8: Create** `ptopilot/db/models.py`

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
    destination_code: Mapped[str] = mapped_column(String(8))
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
    __table_args__ = (UniqueConstraint("origin", "dest_airport", "depart_date", "return_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    dest_airport: Mapped[str] = mapped_column(String(3))
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    dest_airport: Mapped[str] = mapped_column(String(3))
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
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RouteBaseline(Base):
    __tablename__ = "route_baselines"
    __table_args__ = (CheckConstraint("length_bucket IN ('short', 'week', 'long')", name="length_bucket"),)

    origin: Mapped[str] = mapped_column(String(3), primary_key=True)
    dest_airport: Mapped[str] = mapped_column(String(3), primary_key=True)
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

- [ ] **Step 9: Create** `ptopilot/db/session.py`

```python
"""Engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_S = 15


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping: Neon's free tier suspends idle compute, which drops pooled connections.
    # connect_timeout: without it, psycopg on Windows waits forever on an unreachable server.
    return create_engine(
        database_url, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on any exception."""
    session = sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 10: Create** `alembic.ini`

```ini
# Alembic config. The database URL comes from DATABASE_URL (see ptopilot/settings.py), never from this file.
[alembic]
script_location = %(here)s/ptopilot/db/migrations
file_template = %%(rev)s_%%(slug)s
prepend_sys_path = .
path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 11: Create** `ptopilot/db/migrations/env.py`

```python
"""Alembic environment: runs migrations against DATABASE_URL, or a URL set on the config by tests."""

from logging.config import fileConfig

from alembic import context

from ptopilot.db.models import Base
from ptopilot.db.session import make_engine
from ptopilot.settings import Settings

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

url = config.get_main_option("sqlalchemy.url") or Settings.from_env().database_url

with make_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
```

- [ ] **Step 12: Create** `ptopilot/db/migrations/script.py.mako`

```
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 13: Supporting files**

Also create the empty `ptopilot/db/__init__.py`.

- [ ] **Step 14: Autogenerate the initial migration against the empty test database**

Run (Git Bash): `DATABASE_URL=postgresql://ptopilot@localhost:5433/ptopilot_test .venv/Scripts/python -m alembic revision --autogenerate --rev-id 0001 -m "initial schema"`, then `.venv/Scripts/python -m ruff format ptopilot/db/migrations`.
Expected: 13 `Detected added table` lines and `Generating …/versions/0001_initial_schema.py … done`. Open the file and check it has 13 `op.create_table` calls and a matching `downgrade()`.

- [ ] **Step 15: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/db -v && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all tests PASS, none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 16: Apply the migration to the dev database**

Run: `.venv/Scripts/python -m alembic upgrade head` then `.venv/Scripts/python -m alembic current`
Expected: `Running upgrade  -> 0001, initial schema`, then `0001 (head)`.

- [ ] **Step 17: Commit and push**

```bash
git add alembic.ini ptopilot/db tests/db
git commit -m "feat(db): models for all spec tables, sessions, initial migration" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Then check CI: `& "C:\Program Files\GitHub CLI\gh.exe" run watch --exit-status`. Expected: passes, with the database tests running (not skipped) against the CI Postgres service.

---

### Final check

- [ ] Full suite with the database required: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`. Expected: **157 passed, 1 deselected** (the live test).
- [ ] `git status` is clean, and `git log origin/main..main` is empty (everything pushed).
- [ ] The latest CI run on `main` is green.

## What Plan 3 builds on this

The `expand → season_filter → broad_scan → shortlist → live_verify → baselines → score` stages. They read and write these tables, call `TravelpayoutsSource.month_scan` and `GoogleFlightsSource`/`SerpApiSource.exact_search` behind a circuit breaker and `source_budget`, and use `core.planner`, `core.stats` and `core.scoring` from Plan 1.
