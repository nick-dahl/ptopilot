# ptopilot Plan 3: Daily Scan Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily, unattended scan: `expand → broad_scan → shortlist → live_verify → baselines → score`. It records every stage in `pipeline_runs`, emails the admin a health report, runs on GitHub Actions cron, and can re-run any day or stage on demand.

**Architecture:**
- Each stage is a module in `ptopilot/pipeline/` with `run(ctx: RunContext) -> dict[str, int]` (counts). Stages read their inputs from Postgres and write their outputs back.
- A stage raises `StageSkipped` (nothing to do) or `StageFailed` (couldn't do its job).
- `runner.py` records each stage and applies the failure rules from spec §10.
- `RunContext` carries the engine, geo and season data, the sources, the emailer, an injectable `sleep` and `rng`, and `stamp()`, a run-date-consistent `observed_at`.
- Sources are the Plan 2 adapters. Tests use in-memory fakes.

**Tech Stack:** Plans 1–2's stack, plus Resend (HTTP API, via httpx) for email and GitHub Actions cron.

**Spec:** [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](../specs/2026-10-16-ptopilot-design.md), §7 (pipeline, including "Implementation notes (Plan 3)") and §10 (operations).

## Global Constraints

- Python `>=3.12`. **No new dependencies**: email uses `httpx` against Resend's HTTP API.
- `ptopilot/core/` and `ptopilot/sources/` are not modified.
- Every tunable number lives in `ptopilot/config.py`.
- Stages are idempotent per `run_date`: they delete or replace what they wrote for that date, except that `price_observations` is append-only and a same-day `live_verify` re-run skips routes already checked.
- Default `pytest` never touches the network. Pipeline tests use fakes, never real sources.
- Database tests skip when the database is unreachable unless `PTOPILOT_REQUIRE_DB=1` (CI sets it). All `pytest` commands below set it.
- Logging: the CLI sets the `httpx` and `primp` loggers to WARNING, because SerpApi's `api_key` would otherwise appear in request-URL logs and the repo is public.
- `ruff check .` and `ruff format --check .` must pass.
- **Work directly on `main`; every task ends with a commit and a `git push`.** Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Commands run from `C:\Users\nickd\dev\ptopilot` using `.venv/Scripts/python`. The local Postgres must be running (`pg_isready -h localhost -p 5433`; see the README).

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **A re-run of the same day** (cron retry or manual dispatch) → no duplicate links, shortlist entries or candidates, and no repeated paid live checks. *Tasks 3, 5, 6, 8: the `test_rerun_*` tests.*
2. **Travelpayouts token missing**, the day-one state → `broad_scan` is *skipped*, and exploration still drives live checks so history builds. *Task 9: `test_live_verify_failure_lets_scoring_continue` (broad_scan skipped); Task 5: `test_without_history_everything_is_exploration`.*
3. **Google blocking every request** → the breaker trips after 3 failures, SerpApi takes over within its per-run and monthly budget, and the run still scores. *Task 6: breaker and budget tests; Task 9: `test_live_verify_failure_lets_scoring_continue`.*
4. **A user whose window is in progress or already over** → no departures on or before the run date, and past windows are ignored. *Task 3: `test_never_plans_departures_on_or_before_the_run_date`, `test_users_whose_windows_are_all_past_are_counted`.*
5. **A month's cheapest fare used as the price of specific dates** → never. It only steers the shortlist. *Task 8: `test_month_level_fares_never_become_a_candidate_price`; Task 5: `test_exact_date_fare_outranks_month_level_estimates`.*

## Verified before writing (2026-10-16)

- All 220 tests pass in a scratch copy, and lint is clean.
- **A real dry run** against a throwaway database, with live Google Flights calls, for an ORD user with a Lisbon June-2027 tracker:
  - `expand` built 6 trips; `broad_scan` was skipped (no token).
  - `shortlist` picked all 6 as exploration; `live_verify` ran 6 live checks and stored 38 options.
  - `baselines` wrote 2 rows; `score` produced 6 verified candidates from $1,221 to $1,552.
  - The exit code was 0.
- The verified files are in the scratchpad at `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p3`.

## File structure

```
ptopilot/
  config.py                     # + pipeline thresholds (replace whole file)
  settings.py                   # + RESEND_API_KEY, ADMIN_EMAIL, EMAIL_FROM (replace whole file)
  notify/__init__.py, email.py  # ResendEmailer, Emailer protocol, EmailError
  db/models.py                  # + ShortlistEntry, PriceObservation.typical_low/high (replace whole file)
  db/migrations/versions/0002_shortlist_and_typical_range.py   # autogenerated
  pipeline/
    __init__.py
    context.py                  # RunContext, build_context, StageSkipped, StageFailed
    queries.py                  # shared lookups: today's route queries, cached prices, baselines
    expand.py  broad_scan.py  shortlist.py  live_verify.py  baselines.py  score.py
    runner.py                   # STAGES, run_stage, run_pipeline, StageResult
    health.py                   # build_report, send_report
    __main__.py                 # CLI
alembic.ini                     # + post-write hooks: ruff format + ruff check --fix on new migrations
.github/workflows/scan.yml      # daily 06:00 UTC + manual dispatch (date, stage)
.github/workflows/keepalive.yml # monthly commit so the schedule isn't disabled
README.md                       # + Daily scan, configuration table
tests/
  conftest.py                   # moved from tests/db/conftest.py, + clean_engine fixture
  test_settings.py              # + email settings test
  notify/{__init__,test_email}.py
  db/test_pipeline_tables.py
  pipeline/{__init__,conftest,test_expand,test_broad_scan,test_shortlist,test_live_verify,test_baselines,test_score,test_runner}.py
```

---

### Task 1: Pipeline config, email settings, Resend client

**Files:**
- Modify (replace whole file): `ptopilot/config.py`, `ptopilot/settings.py`, `tests/test_settings.py`
- Create: `ptopilot/notify/__init__.py` (empty), `ptopilot/notify/email.py`
- Create: `tests/notify/__init__.py` (empty)
- Test: `tests/notify/test_email.py`, `tests/test_settings.py`

**Interfaces:**
- Produces: new `config` constants `DEFAULT_CURRENCY, CACHE_LOOKBACK_DAYS, BASELINE_WINDOW_DAYS, SHORTLIST_Z, LIVE_CHECK_CAP, EXPLORATION_QUOTA, PRIORITY_WEIGHTS, MONTH_ESTIMATE_WEIGHT, URGENCY, BREAKER_THRESHOLD, LIVE_DELAY_S, SOURCE_BUDGETS, SHORT_HAUL_MAX_MIN, MAX_DURATION_RATIO`; `Settings.resend_api_key/admin_email/email_from`, `DEFAULT_EMAIL_FROM`; `Emailer` protocol `send(to, subject, html, text) -> str`; `ResendEmailer(api_key, sender, client=None)`; `EmailError`.

Resend API: `POST https://api.resend.com/emails` with `Authorization: Bearer <key>` and JSON `{from, to: [..], subject, html, text}`. It returns `{id}`.

- [ ] **Step 1: Create the empty file** `tests/notify/__init__.py`

- [ ] **Step 2: Write the failing test** `tests/test_settings.py`

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


def test_email_settings_default_to_resend_shared_sender():
    s = Settings.from_env({"RESEND_API_KEY": "re", "ADMIN_EMAIL": "me@example.com"})
    assert (s.resend_api_key, s.admin_email) == ("re", "me@example.com")
    assert s.email_from == "ptopilot <onboarding@resend.dev>"
    assert Settings.from_env({"EMAIL_FROM": "deals@example.com"}).email_from == "deals@example.com"
```

- [ ] **Step 3: Write the failing test** `tests/notify/test_email.py`

```python
import json

import httpx
import pytest

from ptopilot.notify.email import API_URL, EmailError, ResendEmailer


def emailer(status=200, body=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {"id": "msg_1"})

    return ResendEmailer(
        "re_key", "ptopilot <onboarding@resend.dev>", httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_send_posts_message_and_returns_id():
    seen = []
    assert emailer(seen=seen).send("me@example.com", "Hi", "<p>Hi</p>", "Hi") == "msg_1"
    req = seen[0]
    assert str(req.url) == API_URL
    assert req.headers["Authorization"] == "Bearer re_key"
    sent = json.loads(req.content)
    assert sent == {
        "from": "ptopilot <onboarding@resend.dev>",
        "to": ["me@example.com"],
        "subject": "Hi",
        "html": "<p>Hi</p>",
        "text": "Hi",
    }


def test_http_error_raises_email_error():
    with pytest.raises(EmailError, match="HTTP 403"):
        emailer(status=403, body={"message": "domain not verified"}).send("x@example.com", "s", "h", "t")


def test_empty_key_is_rejected():
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        ResendEmailer("", "x@example.com")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/test_settings.py tests/notify -q`
Expected: `tests/notify/test_email.py` errors with `ModuleNotFoundError: No module named 'ptopilot.notify'`, and `test_email_settings_default_to_resend_shared_sender` FAILS with `AttributeError` (`resend_api_key`).

- [ ] **Step 5: Write** `ptopilot/config.py`

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
SOURCE_BUDGETS = {"serpapi": {"per_run": 8, "per_month": 250}}
SHORT_HAUL_MAX_MIN = 600  # fastest option under 10 h -> short-haul stop limit applies
MAX_DURATION_RATIO = 1.5
```

- [ ] **Step 6: Write** `ptopilot/settings.py`

```python
"""Runtime settings from environment variables. Secrets never live in the repo."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEV_DATABASE_URL = "postgresql+psycopg://ptopilot@localhost:5433/ptopilot"
# Resend's shared sender; without a verified domain it can only deliver to the Resend account's own address.
DEFAULT_EMAIL_FROM = "ptopilot <onboarding@resend.dev>"


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
    resend_api_key: str = ""
    admin_email: str = ""
    email_from: str = DEFAULT_EMAIL_FROM

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            database_url=normalize_database_url(env.get("DATABASE_URL") or DEV_DATABASE_URL),
            travelpayouts_token=env.get("TRAVELPAYOUTS_TOKEN", ""),
            serpapi_key=env.get("SERPAPI_KEY", ""),
            resend_api_key=env.get("RESEND_API_KEY", ""),
            admin_email=env.get("ADMIN_EMAIL", ""),
            email_from=env.get("EMAIL_FROM") or DEFAULT_EMAIL_FROM,
        )
```

- [ ] **Step 7: Write** `ptopilot/notify/email.py`

```python
"""Outbound email through Resend's HTTP API."""

from __future__ import annotations

from typing import Protocol

import httpx

from ptopilot.sources.base import snippet

API_URL = "https://api.resend.com/emails"
TIMEOUT_S = 20


class EmailError(Exception):
    pass


class Emailer(Protocol):
    def send(self, to: str, subject: str, html: str, text: str) -> str: ...


class ResendEmailer:
    def __init__(self, api_key: str, sender: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("Resend API key is empty; set RESEND_API_KEY")
        self._key = api_key
        self._sender = sender
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def send(self, to: str, subject: str, html: str, text: str) -> str:
        """Send one email; returns Resend's message id."""
        body = {"from": self._sender, "to": [to], "subject": subject, "html": html, "text": text}
        try:
            resp = self._client.post(API_URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise EmailError(f"resend: {type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 300:
            raise EmailError(f"resend: HTTP {resp.status_code}: {snippet(resp.text)}")
        return str(resp.json().get("id", ""))
```

- [ ] **Step 8: Supporting files**

Also create the empty `ptopilot/notify/__init__.py`.

- [ ] **Step 9: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/test_settings.py tests/notify -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 10: Commit and push**

```bash
git add ptopilot/config.py ptopilot/settings.py ptopilot/notify tests/test_settings.py tests/notify
git commit -m "feat: pipeline config, email settings, Resend client" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Pipeline tables, migration 0002, shared DB fixtures

**Files:**
- Modify (replace whole file): `ptopilot/db/models.py`, `alembic.ini`
- Move: `tests/db/conftest.py` → `tests/conftest.py` (then replace its content)
- Create: `ptopilot/db/migrations/versions/0002_shortlist_and_typical_range.py` (autogenerated)
- Test: `tests/db/test_pipeline_tables.py`

**Interfaces:**
- Produces: `ShortlistEntry(id, run_date, route_query_id, rank, reason in {'deal','explore'}, est_price)` unique on (run_date, route_query_id); `PriceObservation.typical_low`, `.typical_high` (Numeric, nullable); fixtures `engine`, `session` (unchanged) and new `clean_engine` (all tables truncated) available to every test directory.

Moving the database fixtures to `tests/conftest.py` makes them available to `tests/pipeline/`. Pipeline stages commit their own transactions, so pipeline tests use `clean_engine` (TRUNCATE before each test) instead of the rollback-only `session`. The new `alembic.ini` hooks run `ruff format` and then `ruff check --fix` on each generated migration, which fixes Plan 2's manual lint step for every future migration.

- [ ] **Step 1: Move the shared fixtures**

Run: `git mv tests/db/conftest.py tests/conftest.py`

- [ ] **Step 2: Write the failing test** `tests/db/test_pipeline_tables.py`

```python
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from ptopilot.db.models import PriceObservation, RouteQuery, ShortlistEntry


def route(session):
    rq = RouteQuery(
        origin="ORD", dest_airport="LIS", depart_date=date(2027, 6, 12), return_date=date(2027, 6, 20)
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

- [ ] **Step 3: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/db -q`
Expected: collection ERROR, `ImportError: cannot import name 'ShortlistEntry' from 'ptopilot.db.models'`

- [ ] **Step 4: Write** `tests/conftest.py`

```python
"""Database fixtures. Uses PTOPILOT_TEST_DATABASE_URL, defaulting to the local dev server on port 5433.

Tests skip when the database is unreachable, unless PTOPILOT_REQUIRE_DB is set (CI sets it).
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ptopilot.db.models import Base
from ptopilot.db.session import make_engine
from ptopilot.settings import normalize_database_url

TEST_URL = normalize_database_url(
    os.environ.get("PTOPILOT_TEST_DATABASE_URL", "postgresql://ptopilot@localhost:5433/ptopilot_test")
)
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


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


@pytest.fixture
def clean_engine(engine):
    """The migrated engine with every table emptied first. For code that commits its own transactions."""
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return engine
```

- [ ] **Step 5: Write** `ptopilot/db/models.py`

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

- [ ] **Step 6: Write** `alembic.ini`

```ini
# Alembic config. The database URL comes from DATABASE_URL (see ptopilot/settings.py), never from this file.
[alembic]
script_location = %(here)s/ptopilot/db/migrations
file_template = %%(rev)s_%%(slug)s
prepend_sys_path = .
path_separator = os

# Format and lint-fix every newly generated migration (Alembic's template uses old-style typing imports).
[post_write_hooks]
hooks = ruff_format, ruff_fix
ruff_format.type = module
ruff_format.module = ruff
ruff_format.options = format REVISION_SCRIPT_FILENAME
ruff_fix.type = module
ruff_fix.module = ruff
ruff_fix.options = check --fix REVISION_SCRIPT_FILENAME

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

- [ ] **Step 7: Autogenerate migration 0002 against the test database (which is at 0001)**

Run (Git Bash): `DATABASE_URL=postgresql://ptopilot@localhost:5433/ptopilot_test .venv/Scripts/python -m alembic revision --autogenerate --rev-id 0002 -m "shortlist and typical range"`
Expected: `Detected added table 'shortlist_entries'`, `Detected added column 'price_observations.typical_low'` and `…typical_high`, then `Running post write hook 'ruff_format'` and `'ruff_fix'`. The file's `upgrade()` creates `shortlist_entries` with its index, check, foreign key and unique constraints, and adds the two columns; `downgrade()` reverses them.

If the test database is not at 0001 (`alembic current` with the same `DATABASE_URL`), recreate it first: `DROP DATABASE ptopilot_test; CREATE DATABASE ptopilot_test;` then `DATABASE_URL=… .venv/Scripts/python -m alembic upgrade 0001`.

- [ ] **Step 8: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/db -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 9: Apply to the dev database**

Run: `.venv/Scripts/python -m alembic upgrade head`
Expected: `Running upgrade 0001 -> 0002`.

- [ ] **Step 10: Commit and push**

```bash
git add ptopilot/db/models.py alembic.ini ptopilot/db/migrations/versions tests/conftest.py tests/db
git commit -m "feat(db): shortlist table, typical-range columns, migration lint hooks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Run context, shared queries, and the `expand` stage

**Files:**
- Create: `ptopilot/pipeline/__init__.py` (empty), `ptopilot/pipeline/context.py`, `ptopilot/pipeline/queries.py`, `ptopilot/pipeline/expand.py`
- Create: `tests/pipeline/__init__.py` (empty), `tests/pipeline/conftest.py`
- Test: `tests/pipeline/test_expand.py`

**Interfaces:**
- Consumes: `core.planner` (Plan 1), `core.calendar.WorkCalendar`, `data.load_geo/load_seasons`, all source adapters (Plan 2), `ResendEmailer` (Task 1), models (Task 2).
- Produces: `StageSkipped`, `StageFailed`; `RunContext(run_date, engine, geo, seasons, month_source=None, live_sources=(), emailer=None, admin_email='', dry_run=False, sleep=time.sleep, rng=Random())` with `.stamp() -> datetime`; `build_context(settings, run_date, dry_run=False)`; `queries.month_of, start_of, date_key, baseline_key, todays_route_queries, cached_prices, estimate, load_baselines, CachedPrice`; `expand.profile_for(user) -> TravelerProfile`, `expand.run(ctx)`. Test helpers in `tests/pipeline/conftest.py`: `RUN`, `FakeMonthSource`, `FakeLiveSource`, `option`, `answering`, `failing`, `quote`, `add_user`, `add_tracker`, `add_observation`, fixture `make_ctx`.

The seeded user (ORD, US calendar, 15 PTO days, June 2027 window) with a Lisbon tracker (5–9 days on the ground) gives exactly 6 trips, verified by a probe. They include Sat Jun 12 → Sun Jun 20 (4 PTO days, with Juneteenth observed on Fri Jun 18).

- [ ] **Step 1: Create the empty file** `tests/pipeline/__init__.py`

- [ ] **Step 2: Create** `tests/pipeline/conftest.py`

```python
"""Fakes and seed data for pipeline tests. Run date is 2027-03-01; the seeded user travels in June 2027."""

import random
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import PriceObservation, Tracker, TravelWindow, User
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
    def __init__(self, name: str, respond: Callable[[ExactQuery], ExactResult]):
        self.name = name
        self.respond = respond
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
    engine, depart, ret, price, observed: date, verified=False, origin="ORD", dest="LIS", **fields
):
    with session_scope(engine) as s:
        s.add(
            PriceObservation(
                origin=origin,
                dest_airport=dest,
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

- [ ] **Step 3: Write the failing test** `tests/pipeline/test_expand.py`

```python
from datetime import date

from sqlalchemy import func, select

from ptopilot.db.models import RouteQuery, TrackerExclusion, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand
from tests.pipeline.conftest import RUN, add_tracker, add_user

JUNETEENTH_TRIP = (date(2027, 6, 12), date(2027, 6, 20))


def links(engine, tracker_id=None):
    with session_scope(engine) as s:
        q = select(TrackerRouteLink, RouteQuery).join(RouteQuery)
        if tracker_id is not None:
            q = q.where(TrackerRouteLink.tracker_id == tracker_id)
        return [
            (rq.origin, rq.dest_airport, rq.depart_date, rq.return_date, link)
            for link, rq in s.execute(q).all()
        ]


def count(engine, model):
    with session_scope(engine) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_builds_links_and_route_queries_for_an_active_tracker(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine))
    counts = expand.run(ctx)
    assert counts == {"trackers": 1, "links": 6, "route_queries": 6}
    rows = links(ctx.engine, tid)
    assert {(o, d) for o, d, *_ in rows} == {("ORD", "LIS")}
    assert (*JUNETEENTH_TRIP,) in {(dep, ret) for _, _, dep, ret, _ in rows}
    link = next(lk for _, _, dep, ret, lk in rows if (dep, ret) == JUNETEENTH_TRIP)
    assert (link.pto_cost, link.days_away, link.season_rating) == (4, 9, "good")
    assert link.days_off == ["Juneteenth National Independence Day (observed)"]


def test_rerun_is_idempotent(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    expand.run(ctx)
    assert count(ctx.engine, TrackerRouteLink) == 6
    assert count(ctx.engine, RouteQuery) == 6


def test_two_users_share_route_queries(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine, "a@example.com"))
    add_tracker(ctx.engine, add_user(ctx.engine, "b@example.com"))
    counts = expand.run(ctx)
    assert (counts["links"], counts["route_queries"]) == (12, 6)
    assert count(ctx.engine, RouteQuery) == 6


def test_snoozed_and_inactive_trackers_are_skipped(make_ctx):
    ctx = make_ctx()
    uid = add_user(ctx.engine)
    add_tracker(ctx.engine, uid, snoozed_until=RUN)
    add_tracker(ctx.engine, uid, active=False)
    expired = add_tracker(ctx.engine, uid, snoozed_until=date(2027, 2, 28))
    assert expand.run(ctx)["trackers"] == 1
    assert {lk.tracker_id for *_, lk in links(ctx.engine)} == {expired}


def test_excluded_trip_is_not_linked(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine))
    with session_scope(ctx.engine) as s:
        s.add(
            TrackerExclusion(tracker_id=tid, depart_date=JUNETEENTH_TRIP[0], return_date=JUNETEENTH_TRIP[1])
        )
    counts = expand.run(ctx)
    assert counts["excluded"] == 1
    assert JUNETEENTH_TRIP not in {(dep, ret) for _, _, dep, ret, _ in links(ctx.engine)}


def test_never_plans_departures_on_or_before_the_run_date(make_ctx):
    ctx = make_ctx(run_date=date(2027, 6, 10))
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    assert all(dep > date(2027, 6, 10) for _, _, dep, _, _ in links(ctx.engine))


def test_users_whose_windows_are_all_past_are_counted(make_ctx):
    ctx = make_ctx(run_date=date(2027, 7, 1))
    add_tracker(ctx.engine, add_user(ctx.engine))
    assert expand.run(ctx) == {"trackers": 1, "trackers_without_windows": 1, "route_queries": 0}


def test_a_bad_tracker_does_not_stop_the_others(make_ctx):
    ctx = make_ctx()
    uid = add_user(ctx.engine)
    add_tracker(ctx.engine, uid, code="ZZZ")
    good = add_tracker(ctx.engine, uid)
    counts = expand.run(ctx)
    assert counts["tracker_errors"] == 1
    assert {lk.tracker_id for *_, lk in links(ctx.engine)} == {good}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_expand.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.pipeline'`

- [ ] **Step 5: Write** `ptopilot/pipeline/context.py`

```python
"""Everything a pipeline run needs, built once and passed to every stage."""

from __future__ import annotations

import random
import time as time_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from sqlalchemy import Engine

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.session import make_engine
from ptopilot.notify.email import Emailer, ResendEmailer
from ptopilot.settings import Settings
from ptopilot.sources.base import ExactSearchSource, MonthScanSource
from ptopilot.sources.google_flights import GoogleFlightsSource
from ptopilot.sources.serpapi import SerpApiSource
from ptopilot.sources.travelpayouts import TravelpayoutsSource


class StageSkipped(Exception):
    """The stage has nothing it can do (e.g. a source isn't configured). Not a failure."""


class StageFailed(Exception):
    """The stage could not do its job."""


@dataclass
class RunContext:
    run_date: date
    engine: Engine
    geo: Geo
    seasons: SeasonTable
    month_source: MonthScanSource | None = None
    live_sources: Sequence[ExactSearchSource] = ()  # tried in order: primary first, then fallbacks
    emailer: Emailer | None = None
    admin_email: str = ""
    dry_run: bool = False
    sleep: Callable[[float], None] = time_module.sleep
    rng: random.Random = field(default_factory=random.Random)

    def stamp(self) -> datetime:
        """observed_at for rows this run writes: now, or noon UTC on run_date when re-running a past day."""
        now = datetime.now(UTC)
        return now if now.date() == self.run_date else datetime.combine(self.run_date, time(12), UTC)


def build_context(settings: Settings, run_date: date, dry_run: bool = False) -> RunContext:
    live: list[ExactSearchSource] = [GoogleFlightsSource()]
    if settings.serpapi_key:
        live.append(SerpApiSource(settings.serpapi_key))
    return RunContext(
        run_date=run_date,
        engine=make_engine(settings.database_url),
        geo=load_geo(),
        seasons=load_seasons(),
        month_source=TravelpayoutsSource(settings.travelpayouts_token)
        if settings.travelpayouts_token
        else None,
        live_sources=live,
        emailer=ResendEmailer(settings.resend_api_key, settings.email_from)
        if settings.resend_api_key
        else None,
        admin_email=settings.admin_email,
        dry_run=dry_run,
    )
```

- [ ] **Step 6: Write** `ptopilot/pipeline/queries.py`

```python
"""Queries shared by several stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.stats import Baseline, length_bucket
from ptopilot.db.models import PriceObservation, RouteBaseline, RouteQuery, TrackerRouteLink

DateKey = tuple[str, str, date, date]  # origin, dest_airport, depart, return
BaselineKey = tuple[str, str, date, str]  # origin, dest_airport, month, length_bucket


def month_of(d: date) -> date:
    return d.replace(day=1)


def start_of(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def date_key(rq: RouteQuery) -> DateKey:
    return (rq.origin, rq.dest_airport, rq.depart_date, rq.return_date)


def baseline_key(origin: str, dest: str, depart: date, ret: date) -> BaselineKey:
    return (origin, dest, month_of(depart), length_bucket((ret - depart).days + 1))


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
) -> tuple[dict[DateKey, CachedPrice], dict[tuple[str, str, date], CachedPrice]]:
    """Cheapest recent unverified fare per exact date pair, and per (origin, dest, month)."""
    since = start_of(run_date - timedelta(days=config.CACHE_LOOKBACK_DAYS))
    routes = {(rq.origin, rq.dest_airport) for rq in rqs}
    exact: dict[DateKey, CachedPrice] = {}
    monthly: dict[tuple[str, str, date], CachedPrice] = {}
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
        if (o.origin, o.dest_airport) not in routes:
            continue
        cp = CachedPrice(o.id, o.price)
        mkey = (o.origin, o.dest_airport, o.month)
        if mkey not in monthly or cp.price < monthly[mkey].price:
            monthly[mkey] = cp
        if o.depart_date and o.return_date:
            dkey = (o.origin, o.dest_airport, o.depart_date, o.return_date)
            if dkey not in exact or cp.price < exact[dkey].price:
                exact[dkey] = cp
    return exact, monthly


def estimate(rq: RouteQuery, exact: dict, monthly: dict) -> CachedPrice | None:
    return exact.get(date_key(rq)) or monthly.get((rq.origin, rq.dest_airport, month_of(rq.depart_date)))


def load_baselines(s: Session) -> dict[BaselineKey, Baseline]:
    return {
        (b.origin, b.dest_airport, b.month, b.length_bucket): Baseline(
            float(b.median), float(b.sigma), b.n, b.confidence
        )
        for b in s.scalars(select(RouteBaseline))
    }
```

- [ ] **Step 7: Write** `ptopilot/pipeline/expand.py`

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
    key = (it.origin, it.dest_airport, it.shape.depart_date, it.shape.return_date)
    if key not in cache:
        values = dict(zip(("origin", "dest_airport", "depart_date", "return_date"), key, strict=True))
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

- [ ] **Step 8: Supporting files**

Also create the empty `ptopilot/pipeline/__init__.py`.

- [ ] **Step 9: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_expand.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 10: Commit and push**

```bash
git add ptopilot/pipeline tests/pipeline
git commit -m "feat(pipeline): run context, shared queries, expand stage" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 4: `broad_scan` stage

**Files:**
- Create: `ptopilot/pipeline/broad_scan.py`
- Test: `tests/pipeline/test_broad_scan.py`

**Interfaces:**
- Consumes: `RunContext`, `StageSkipped`, `StageFailed`, `queries.month_of/todays_route_queries`, `MonthScanSource`.
- Produces: `broad_scan.run(ctx)`.

- [ ] **Step 1: Write the failing test** `tests/pipeline/test_broad_scan.py`

```python
from datetime import date

import pytest
from sqlalchemy import select

from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline import broad_scan, expand
from ptopilot.pipeline.context import StageFailed, StageSkipped
from ptopilot.sources.base import SourceUnavailable
from tests.pipeline.conftest import RUN, FakeMonthSource, add_tracker, add_user, quote

JUNE = date(2027, 6, 1)


def observations(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(PriceObservation).order_by(PriceObservation.id)))


def test_skipped_without_a_month_source(make_ctx):
    with pytest.raises(StageSkipped, match="TRAVELPAYOUTS_TOKEN"):
        broad_scan.run(make_ctx())


def test_one_scan_per_route_month_and_unverified_rows(make_ctx):
    source = FakeMonthSource(
        {
            ("ORD", "LIS", JUNE): [
                quote("ORD", "LIS", date(2027, 6, 12), date(2027, 6, 20), 640),
                quote("ORD", "LIS", date(2027, 6, 14), None, 300),  # one-way: ignored
            ]
        }
    )
    ctx = make_ctx(month_source=source)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    counts = broad_scan.run(ctx)
    assert source.calls == [("ORD", "LIS", JUNE, "US", "USD")]
    assert counts == {"scans_ok": 1, "quotes": 1}
    [obs] = observations(ctx.engine)
    assert (obs.depart_date, obs.return_date, obs.price, obs.verified) == (
        date(2027, 6, 12),
        date(2027, 6, 20),
        640,
        False,
    )
    assert obs.month == JUNE
    assert obs.observed_at.date() == RUN  # stamped on the run date, not the wall clock


def test_partial_failure_is_counted_not_fatal(make_ctx):
    source = FakeMonthSource(
        {
            ("ORD", "LIS", JUNE): SourceUnavailable("HTTP 500"),
            ("MDW", "LIS", JUNE): [quote("MDW", "LIS", date(2027, 6, 12), date(2027, 6, 20), 700)],
        }
    )
    ctx = make_ctx(month_source=source)
    add_tracker(ctx.engine, add_user(ctx.engine, nearby_airports=["MDW"]))
    expand.run(ctx)
    assert broad_scan.run(ctx) == {"scans_failed": 1, "scans_ok": 1, "quotes": 1}


def test_all_scans_failing_fails_the_stage(make_ctx):
    source = FakeMonthSource({("ORD", "LIS", JUNE): SourceUnavailable("HTTP 401: Unauthorized")})
    ctx = make_ctx(month_source=source)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    with pytest.raises(StageFailed, match="401"):
        broad_scan.run(ctx)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_broad_scan.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'broad_scan' from 'ptopilot.pipeline'`

- [ ] **Step 3: Write** `ptopilot/pipeline/broad_scan.py`

```python
"""Stage `broad_scan`: one cached month scan per (origin, airport, month) needed today (spec §7)."""

from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal

from ptopilot import config
from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import month_of, todays_route_queries
from ptopilot.sources.base import SourceUnavailable

log = logging.getLogger(__name__)


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.month_source is None:
        raise StageSkipped("no month-scan source configured (set TRAVELPAYOUTS_TOKEN)")
    counts: Counter[str] = Counter()
    with session_scope(ctx.engine) as s:
        keys = sorted(
            {
                (rq.origin, rq.dest_airport, month_of(rq.depart_date))
                for rq in todays_route_queries(s, ctx.run_date)
            }
        )
    last_error = ""
    for origin, dest, month in keys:
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
        with session_scope(ctx.engine) as s:
            for q in quotes:
                if q.return_date is None:
                    continue
                s.add(
                    PriceObservation(
                        origin=q.origin,
                        dest_airport=q.dest_airport,
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
                )
                counts["quotes"] += 1
    if keys and not counts["scans_ok"]:
        raise StageFailed(f"all {len(keys)} month scans failed; last error: {last_error}")
    return dict(counts)
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_broad_scan.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit and push**

```bash
git add ptopilot/pipeline/broad_scan.py tests/pipeline/test_broad_scan.py
git commit -m "feat(pipeline): broad_scan stage" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 5: `shortlist` stage

**Files:**
- Create: `ptopilot/pipeline/shortlist.py`
- Test: `tests/pipeline/test_shortlist.py`

**Interfaces:**
- Consumes: `queries.*`, `core.stats.z_score`, `ShortlistEntry`.
- Produces: `shortlist.urgency(days_until) -> float`, `shortlist.run(ctx)`; writes `shortlist_entries` with deals first (rank 1…), then exploration.

- [ ] **Step 1: Write the failing test** `tests/pipeline/test_shortlist.py`

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import RouteBaseline, RouteQuery, ShortlistEntry
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, shortlist
from tests.pipeline.conftest import RUN, add_observation, add_tracker, add_user

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
    add_observation(ctx.engine, *DEAL, 900, observed=date(2027, 2, 1), verified=True)
    shortlist.run(ctx)
    assert entries(ctx.engine)[-1][2] == DEAL


def test_caps_reserve_exploration_slots(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_CHECK_CAP", 3)
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 2)
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)
    assert (counts["explore"], counts["explore_overflow"]) == (2, 4)
    assert len(entries(ctx.engine)) == 2


def test_rerun_replaces_the_days_shortlist(make_ctx):
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    shortlist.run(ctx)
    assert [rank for rank, *_ in entries(ctx.engine)] == [1, 2, 3, 4, 5, 6]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_shortlist.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'shortlist' from 'ptopilot.pipeline'`

- [ ] **Step 3: Write** `ptopilot/pipeline/shortlist.py`

```python
"""Stage `shortlist`: choose which route queries get a live check today (spec §7).

Two kinds of entry, deals first in check order:
- deal: the cached price is at or below ~p35 of a confident baseline, ranked by
  deal strength × urgency × tracker priority.
- explore: routes with too little history (n < COLD_START_N) or no cached price at all, oldest
  live check first. EXPLORATION_QUOTA slots are reserved for these so history keeps building even
  on days full of deals.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from ptopilot import config
from ptopilot.core.stats import z_score
from ptopilot.db.models import PriceObservation, ShortlistEntry, Tracker, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import (
    baseline_key,
    cached_prices,
    date_key,
    estimate,
    load_baselines,
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
        last_live = {
            (o, d, dep, ret): when.replace(tzinfo=None)
            for o, d, dep, ret, when in s.execute(
                select(
                    PriceObservation.origin,
                    PriceObservation.dest_airport,
                    PriceObservation.depart_date,
                    PriceObservation.return_date,
                    func.max(PriceObservation.observed_at),
                )
                .where(PriceObservation.verified.is_(True))
                .group_by(
                    PriceObservation.origin,
                    PriceObservation.dest_airport,
                    PriceObservation.depart_date,
                    PriceObservation.return_date,
                )
            ).all()
        }

        deals: list[tuple[float, int, Decimal]] = []
        explore: list[tuple[datetime, date, int, Decimal | None]] = []
        for rq in rqs:
            est = estimate(rq, exact, monthly)
            b = baselines.get(baseline_key(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date))
            if est is None or b is None or b.n < config.COLD_START_N:
                seen = last_live.get(date_key(rq), NEVER)
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
        picked_explore = explore[: config.EXPLORATION_QUOTA]
        deals.sort(key=lambda d: (-d[0], d[1]))
        picked_deals = deals[: config.LIVE_CHECK_CAP - len(picked_explore)]

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

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_shortlist.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Prove `test_exact_date_fare_outranks_month_level_estimates` guards the month-estimate weighting**

Temporarily change `if date_key(rq) not in exact:` to `if False and date_key(rq) not in exact:` in `shortlist.py` and run `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_shortlist.py -q`.
Expected: exactly that test FAILS. Revert the change and confirm all 7 pass.

- [ ] **Step 6: Commit and push**

```bash
git add ptopilot/pipeline/shortlist.py tests/pipeline/test_shortlist.py
git commit -m "feat(pipeline): shortlist stage with reserved exploration slots" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 6: `live_verify` stage (circuit breaker + budgets)

**Files:**
- Create: `ptopilot/pipeline/live_verify.py`
- Test: `tests/pipeline/test_live_verify.py`

**Interfaces:**
- Consumes: `ExactSearchSource`, `ExactQuery`, `SourceUnavailable`, `ShortlistEntry`, `SourceBudget`, `config.SOURCE_BUDGETS/BREAKER_THRESHOLD/LIVE_DELAY_S`.
- Produces: `live_verify.Budget(ctx)` with `.allows(source)`, `.charge(source)`, `.used_this_month(source)`; `live_verify.run(ctx)`.

- [ ] **Step 1: Write the failing test** `tests/pipeline/test_live_verify.py`

```python
from datetime import date

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import PriceObservation, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, live_verify, shortlist
from ptopilot.pipeline.context import StageFailed, StageSkipped
from tests.pipeline.conftest import RUN, FakeLiveSource, add_tracker, add_user, answering, failing, option


def verified(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(PriceObservation).where(PriceObservation.verified.is_(True))))


def budget_used(engine, source):
    with session_scope(engine) as s:
        return s.scalar(select(SourceBudget.calls_used).filter_by(source=source, period=date(2027, 3, 1)))


def shortlisted(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)  # no history -> 6 exploration entries
    return ctx


def test_skipped_without_live_sources(make_ctx):
    with pytest.raises(StageSkipped):
        live_verify.run(make_ctx())


def test_stores_every_option_as_verified_with_typical_range(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700), option(650, stops=0), typical=(600, 900)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    counts = live_verify.run(ctx)
    assert counts["google_flights_ok"] == 6 and counts["options_stored"] == 12
    rows = verified(ctx.engine)
    assert len(rows) == 12
    assert {(r.typical_low, r.typical_high) for r in rows} == {(600, 900)}
    assert all(r.observed_at.date() == RUN and r.deep_link for r in rows)


def test_breaker_trips_after_three_failures_and_fallback_takes_over(make_ctx):
    primary = FakeLiveSource("google_flights", failing("429"))
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[primary, fallback])
    counts = live_verify.run(ctx)
    assert len(primary.calls) == 3
    assert counts["google_flights_breaker_tripped"] == 1
    assert counts["serpapi_ok"] == 6


def test_fallback_budget_caps_calls_per_run_and_is_persisted(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_run": 2, "per_month": 250})
    primary = FakeLiveSource("google_flights", failing())
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[primary, fallback])
    counts = live_verify.run(ctx)
    assert len(fallback.calls) == 2
    assert counts["serpapi_budget_exhausted"] == 1
    assert counts["unchecked"] > 0
    assert budget_used(ctx.engine, "serpapi") == 2


def test_monthly_budget_already_spent_blocks_the_source(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_run": 8, "per_month": 250})
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    ctx = shortlisted(make_ctx, live_sources=[fallback])
    with session_scope(ctx.engine) as s:
        s.add(SourceBudget(source="serpapi", period=date(2027, 3, 1), calls_used=250))
    with pytest.raises(StageFailed):
        live_verify.run(ctx)
    assert fallback.calls == []


def test_every_source_failing_fails_the_stage(make_ctx):
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", failing())])
    with pytest.raises(StageFailed, match="no live check succeeded"):
        live_verify.run(ctx)


def test_no_flights_counts_as_a_successful_check(make_ctx):
    ctx = shortlisted(make_ctx, live_sources=[FakeLiveSource("google_flights", answering())])
    counts = live_verify.run(ctx)
    assert (counts["google_flights_ok"], counts["no_flights"], counts["options_stored"]) == (6, 6, 0)


def test_rerun_skips_routes_already_checked_today(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src])
    live_verify.run(ctx)
    counts = live_verify.run(ctx)
    assert counts == {"already_checked": 6}
    assert len(src.calls) == 6


def test_pauses_between_checks(make_ctx):
    pauses = []
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = shortlisted(make_ctx, live_sources=[src], sleep=pauses.append)
    live_verify.run(ctx)
    assert len(pauses) == 5
    assert all(config.LIVE_DELAY_S[0] <= p <= config.LIVE_DELAY_S[1] for p in pauses)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_live_verify.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'live_verify' from 'ptopilot.pipeline'`

- [ ] **Step 3: Write** `ptopilot/pipeline/live_verify.py`

```python
"""Stage `live_verify`: live exact-date checks for the shortlist, with circuit breaker and budgets (§7).

Sources are tried in order (Google Flights first, SerpApi as fallback). A source that fails
BREAKER_THRESHOLD times in a row is skipped for the rest of the run. Budgeted sources (SerpApi) are
capped per run and per calendar month via `source_budget`; every attempted call counts.
Every option a source returns is stored as a verified observation; per-user filtering happens in `score`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ptopilot import config
from ptopilot.db.models import PriceObservation, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.pipeline.queries import month_of, start_of
from ptopilot.sources.base import ExactQuery, ExactResult, ExactSearchSource, SourceUnavailable

log = logging.getLogger(__name__)


class Budget:
    """Per-run and per-month call caps for budgeted sources, persisted in source_budget."""

    def __init__(self, ctx: RunContext):
        self._ctx = ctx
        self._period = month_of(ctx.run_date)
        self._run_calls: Counter[str] = Counter()

    def allows(self, source: str) -> bool:
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return True
        if self._run_calls[source] >= caps["per_run"]:
            return False
        return self.used_this_month(source) < caps["per_month"]

    def used_this_month(self, source: str) -> int:
        with session_scope(self._ctx.engine) as s:
            return (
                s.scalar(select(SourceBudget.calls_used).filter_by(source=source, period=self._period)) or 0
            )

    def charge(self, source: str) -> None:
        self._run_calls[source] += 1
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
        # A re-run of the same day skips routes already checked for this run date.
        checked = set(
            s.execute(
                select(
                    PriceObservation.origin,
                    PriceObservation.dest_airport,
                    PriceObservation.depart_date,
                    PriceObservation.return_date,
                ).where(
                    PriceObservation.verified.is_(True),
                    PriceObservation.observed_at >= start_of(ctx.run_date),
                    PriceObservation.observed_at < start_of(ctx.run_date + timedelta(days=1)),
                )
            ).all()
        )

    budget = Budget(ctx)
    consecutive_failures: Counter[str] = Counter()
    disabled: set[str] = set()
    for i, rq in enumerate(entries):
        if (rq.origin, rq.dest_airport, rq.depart_date, rq.return_date) in checked:
            counts["already_checked"] += 1
            continue
        usable: list[ExactSearchSource] = [src for src in ctx.live_sources if src.name not in disabled]
        if not usable:
            counts["unchecked"] += len(entries) - i
            break
        query = ExactQuery(
            rq.origin, rq.dest_airport, rq.depart_date, rq.return_date, config.DEFAULT_CURRENCY
        )
        for src in usable:
            if not budget.allows(src.name):
                disabled.add(src.name)
                counts[f"{src.name}_budget_exhausted"] += 1
                continue
            budget.charge(src.name)
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
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
            if not result.options:
                counts["no_flights"] += 1
            break
        else:
            counts["all_sources_failed"] += 1
        if i < len(entries) - 1:
            ctx.sleep(ctx.rng.uniform(*config.LIVE_DELAY_S))

    successes = sum(v for k, v in counts.items() if k.endswith("_ok"))
    pending = len(entries) - counts["already_checked"]
    if pending and not successes:
        raise StageFailed(f"no live check succeeded for {pending} shortlisted routes: {dict(counts)}")
    return dict(counts)
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_live_verify.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit and push**

```bash
git add ptopilot/pipeline/live_verify.py tests/pipeline/test_live_verify.py
git commit -m "feat(pipeline): live_verify stage with circuit breaker and budgets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 7: `baselines` stage

**Files:**
- Create: `ptopilot/pipeline/baselines.py`
- Test: `tests/pipeline/test_baselines.py`

**Interfaces:**
- Consumes: `core.stats.compute_baseline`, `queries.baseline_key/start_of/todays_route_queries`, `RouteBaseline`.
- Produces: `baselines.run(ctx)`; upserts `route_baselines`.

- [ ] **Step 1: Write the failing test** `tests/pipeline/test_baselines.py`

```python
from datetime import date

import pytest
from sqlalchemy import select

from ptopilot.db.models import RouteBaseline
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, expand
from tests.pipeline.conftest import RUN, add_observation, add_tracker, add_user

JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 12), date(2027, 6, 20))  # "week" bucket


def stored(engine):
    with session_scope(engine) as s:
        return {
            (b.month, b.length_bucket): b
            for b in s.scalars(select(RouteBaseline).where(RouteBaseline.dest_airport == "LIS"))
        }


@pytest.fixture
def ctx(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    return ctx


def test_uses_cheapest_price_per_day_and_trailing_window(ctx):
    for price in (950, 900, 920):  # same trip, same day: only 900 counts
        add_observation(ctx.engine, *TRIP, price, observed=date(2027, 2, 20))
    add_observation(ctx.engine, *TRIP, 1000, observed=date(2027, 2, 25), verified=True)
    add_observation(ctx.engine, *TRIP, 50, observed=date(2026, 12, 1))  # older than 60 days: ignored
    baselines.run(ctx)
    b = stored(ctx.engine)[(JUNE, "week")]
    assert (b.median, b.n, b.confidence) == (950, 2, "low")


def test_blends_with_latest_google_typical_range(ctx):
    add_observation(
        ctx.engine, *TRIP, 700, observed=date(2027, 2, 1), verified=True, typical_low=100, typical_high=200
    )
    add_observation(
        ctx.engine, *TRIP, 700, observed=date(2027, 2, 20), verified=True, typical_low=600, typical_high=1000
    )
    baselines.run(ctx)
    b = stored(ctx.engine)[(JUNE, "week")]
    # n=2 -> weight 2/15 on own data (700), 13/15 on Google's midpoint (800)
    assert float(b.median) == pytest.approx(786.67, abs=0.01)
    assert (b.google_typical_low, b.google_typical_high) == (600, 1000)


def test_keys_without_data_are_skipped_and_rerun_updates_in_place(ctx):
    add_observation(ctx.engine, *TRIP, 800, observed=date(2027, 2, 20))
    counts = baselines.run(ctx)
    assert counts["confidence_low"] == 1 and counts["no_data"] >= 1
    add_observation(ctx.engine, *TRIP, 600, observed=date(2027, 2, 21))
    baselines.run(ctx)
    rows = stored(ctx.engine)
    assert len(rows) == 1
    assert rows[(JUNE, "week")].median == 700
    assert rows[(JUNE, "week")].computed_at.date() == RUN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_baselines.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'baselines' from 'ptopilot.pipeline'`

- [ ] **Step 3: Write** `ptopilot/pipeline/baselines.py`

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
from ptopilot.pipeline.queries import BaselineKey, baseline_key, start_of, todays_route_queries


def run(ctx: RunContext) -> dict[str, int]:
    counts: Counter[str] = Counter()
    since = start_of(ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS))
    until = start_of(ctx.run_date + timedelta(days=1))
    with session_scope(ctx.engine) as s:
        rqs = todays_route_queries(s, ctx.run_date)
        wanted = {baseline_key(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date) for rq in rqs}
        routes = {(k[0], k[1]) for k in wanted}
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
            if (o.origin, o.dest_airport) not in routes:
                continue
            key = baseline_key(o.origin, o.dest_airport, o.depart_date, o.return_date)
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
            origin, dest, month, bucket = key
            stmt = insert(RouteBaseline).values(
                origin=origin, dest_airport=dest, month=month, length_bucket=bucket, **values
            )
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["origin", "dest_airport", "month", "length_bucket"], set_=values
                )
            )
            counts[f"confidence_{b.confidence}"] += 1
    return dict(counts)
```

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_baselines.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit and push**

```bash
git add ptopilot/pipeline/baselines.py tests/pipeline/test_baselines.py
git commit -m "feat(pipeline): baselines stage" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 8: `score` stage

**Files:**
- Create: `ptopilot/pipeline/score.py`
- Test: `tests/pipeline/test_score.py`

**Interfaces:**
- Consumes: `core.scoring.go_now`, `core.stats.deal_level/z_score`, `queries.*`, `Candidate`.
- Produces: `score.pick_option(options, user, evening_departure) -> PriceObservation | None`, `score.run(ctx)`; writes `candidates` for the run date (Plan 4's digest reads these).

- [ ] **Step 1: Write the failing test** `tests/pipeline/test_score.py`

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_score.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'score' from 'ptopilot.pipeline'`

- [ ] **Step 3: Write** `ptopilot/pipeline/score.py`

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
    baseline_key,
    cached_prices,
    date_key,
    load_baselines,
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
            key = (o.origin, o.dest_airport, o.depart_date, o.return_date)
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
            chosen = pick_option(verified[date_key(rq)], user, link.evening_departure)
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
            b = baselines.get(baseline_key(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date))
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

- [ ] **Step 4: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_score.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 5: Commit and push**

```bash
git add ptopilot/pipeline/score.py tests/pipeline/test_score.py
git commit -m "feat(pipeline): score stage with per-user option filters" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 9: Runner, health email, CLI, scheduled workflows

**Files:**
- Create: `ptopilot/pipeline/runner.py`, `ptopilot/pipeline/health.py`, `ptopilot/pipeline/__main__.py`
- Create: `.github/workflows/scan.yml`, `.github/workflows/keepalive.yml`
- Modify (replace whole file): `README.md`
- Test: `tests/pipeline/test_runner.py`

**Interfaces:**
- Consumes: every stage module (Tasks 3–8), `build_context`, `Settings`, `EmailError`.
- Produces: `runner.STAGES` (ordered dict name→run), `CONTINUE_ON_FAILURE = {'live_verify'}`, `StageResult(stage, status, counts, error)`, `run_stage(ctx, name)`, `run_pipeline(ctx, stages=None)`; `health.build_report(ctx, results) -> (subject, text)`, `health.send_report(ctx, results) -> text`; CLI `python -m ptopilot.pipeline run [--stage S]… [--date D] [--dry-run]`, exit 1 on any failed stage.

- [ ] **Step 1: Write the failing test** `tests/pipeline/test_runner.py`

```python
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from ptopilot.db.models import Candidate, PipelineRun, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import __main__ as cli
from ptopilot.pipeline import runner
from ptopilot.pipeline.context import StageFailed
from ptopilot.pipeline.health import build_report, send_report
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    FakeMonthSource,
    add_observation,
    add_tracker,
    add_user,
    answering,
    failing,
    option,
    quote,
)

DEAL = (date(2027, 6, 12), date(2027, 6, 20))


class FakeEmailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, html, text):
        self.sent.append((to, subject, text))
        return "msg_1"


def runs(engine):
    with session_scope(engine) as s:
        return {r.stage: r for r in s.scalars(select(PipelineRun))}


def test_end_to_end_finds_a_great_deal(make_ctx):
    """History: June ORD-LIS week trips cost ~$1000. Today's live price for the Juneteenth trip is $590."""
    ctx = make_ctx(
        month_source=FakeMonthSource({("ORD", "LIS", date(2027, 6, 1)): [quote("ORD", "LIS", *DEAL, 610)]}),
        live_sources=[FakeLiveSource("google_flights", answering(option(590), option(640, stops=0)))],
    )
    add_tracker(ctx.engine, add_user(ctx.engine))
    for i, price in enumerate([950, 1000, 1050, 980, 1020] * 4):  # 20 days of history
        add_observation(ctx.engine, *DEAL, price, observed=RUN - timedelta(days=40 - i))

    results = runner.run_pipeline(ctx)

    assert [(r.stage, r.status) for r in results] == [
        ("expand", "ok"),
        ("broad_scan", "ok"),
        ("shortlist", "ok"),
        ("live_verify", "ok"),
        ("baselines", "ok"),
        ("score", "ok"),
    ]
    with session_scope(ctx.engine) as s:
        rows = s.execute(select(Candidate, RouteQuery).join(RouteQuery)).all()
        deal = next(c for c, rq in rows if (rq.depart_date, rq.return_date) == DEAL)
        assert (deal.price, deal.verified, deal.deal_level, deal.confidence) == (590, True, "great", "normal")
    assert set(runs(ctx.engine)) == set(runner.STAGES)


def test_failed_core_stage_stops_the_rest(make_ctx, monkeypatch):
    def broken(ctx):
        raise StageFailed("all month scans failed")

    monkeypatch.setitem(runner.STAGES, "broad_scan", broken)
    results = runner.run_pipeline(make_ctx())
    assert [r.status for r in results] == ["ok", "failed", "not_run", "not_run", "not_run", "not_run"]
    assert runs(make_ctx().engine)["broad_scan"].error == "all month scans failed"


def test_live_verify_failure_lets_scoring_continue(make_ctx):
    ctx = make_ctx(live_sources=[FakeLiveSource("google_flights", failing())])
    add_tracker(ctx.engine, add_user(ctx.engine))
    statuses = {r.stage: r.status for r in runner.run_pipeline(ctx)}
    assert statuses == {
        "expand": "ok",
        "broad_scan": "skipped",
        "shortlist": "ok",
        "live_verify": "failed",
        "baselines": "ok",
        "score": "ok",
    }


def test_unexpected_crash_is_recorded(make_ctx, monkeypatch):
    monkeypatch.setitem(runner.STAGES, "expand", lambda ctx: 1 / 0)
    result = runner.run_stage(make_ctx(), "expand")
    assert result.status == "failed"
    assert "ZeroDivisionError" in result.error


def test_unknown_stage_is_rejected(make_ctx):
    with pytest.raises(ValueError, match="nope"):
        runner.run_pipeline(make_ctx(), ["nope"])


def test_health_report_summarises_stages_and_budget(make_ctx):
    ctx = make_ctx()
    results = [
        runner.StageResult("expand", "ok", {"links": 6}),
        runner.StageResult("live_verify", "failed", {"google_flights_failed": 3}, "no live check succeeded"),
    ]
    subject, text = build_report(ctx, results)
    assert subject == "ptopilot scan 2027-03-01: FAILED (live_verify)"
    assert "links=6" in text and "no live check succeeded" in text
    assert "serpapi: 0/250 this month (250 left)" in text


def test_health_report_labels_skip_reasons_as_reasons(make_ctx):
    _, text = build_report(make_ctx(), [runner.StageResult("broad_scan", "skipped", error="no token")])
    assert "reason: no token" in text and "error:" not in text


def test_report_is_emailed_unless_dry_run(make_ctx):
    emailer = FakeEmailer()
    results = [runner.StageResult("expand", "ok")]
    send_report(make_ctx(emailer=emailer, admin_email="me@example.com", dry_run=True), results)
    assert emailer.sent == []
    send_report(make_ctx(emailer=emailer, admin_email="me@example.com"), results)
    assert emailer.sent[0][:2] == ("me@example.com", "ptopilot scan 2027-03-01: OK")


def test_cli_runs_selected_stages_and_exit_code_reflects_failures(make_ctx, monkeypatch, capsys):
    ctx = make_ctx()
    monkeypatch.setattr(cli, "build_context", lambda settings, run_date, dry_run: ctx)
    assert cli.main(["run", "--stage", "expand", "--date", "2027-03-01", "--dry-run"]) == 0
    assert "expand" in capsys.readouterr().out

    monkeypatch.setitem(runner.STAGES, "expand", lambda c: 1 / 0)
    assert cli.main(["run", "--stage", "expand"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_runner.py -q`
Expected: collection ERROR, `ImportError: cannot import name '__main__' from 'ptopilot.pipeline'`

- [ ] **Step 3: Write** `ptopilot/pipeline/runner.py`

```python
"""Runs stages in order, records each in pipeline_runs, and applies the failure rules (spec §10)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ptopilot.db.models import PipelineRun
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, broad_scan, expand, live_verify, score, shortlist
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.sources.base import snippet

log = logging.getLogger(__name__)

STAGES: dict[str, Callable[[RunContext], dict[str, int]]] = {
    "expand": expand.run,
    "broad_scan": broad_scan.run,
    "shortlist": shortlist.run,
    "live_verify": live_verify.run,
    "baselines": baselines.run,
    "score": score.run,
}
# A failure here still lets later stages run on whatever data exists (cached or unverified prices).
CONTINUE_ON_FAILURE = frozenset({"live_verify"})


@dataclass
class StageResult:
    stage: str
    status: str  # ok | skipped | failed | not_run
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def run_stage(ctx: RunContext, name: str) -> StageResult:
    with session_scope(ctx.engine) as s:
        row = PipelineRun(run_date=ctx.run_date, stage=name, status="running")
        s.add(row)
        s.flush()
        run_id = row.id
    try:
        result = StageResult(name, "ok", STAGES[name](ctx))
    except StageSkipped as exc:
        result = StageResult(name, "skipped", error=str(exc))
    except StageFailed as exc:
        result = StageResult(name, "failed", error=snippet(str(exc), 1000))
    except Exception as exc:
        log.exception("stage %s crashed", name)
        result = StageResult(name, "failed", error=snippet(f"{type(exc).__name__}: {exc}", 1000))
    with session_scope(ctx.engine) as s:
        row = s.get(PipelineRun, run_id)
        row.status, row.counts, row.error = result.status, result.counts, result.error
        row.finished_at = datetime.now(UTC)
    log.info("stage %s: %s %s %s", name, result.status, result.counts, result.error or "")
    return result


def run_pipeline(ctx: RunContext, stages: Sequence[str] | None = None) -> list[StageResult]:
    names = list(stages or STAGES)
    unknown = [n for n in names if n not in STAGES]
    if unknown:
        raise ValueError(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    results: list[StageResult] = []
    for i, name in enumerate(names):
        result = run_stage(ctx, name)
        results.append(result)
        if result.status == "failed" and name not in CONTINUE_ON_FAILURE:
            results.extend(StageResult(n, "not_run") for n in names[i + 1 :])
            break
    return results
```

- [ ] **Step 4: Write** `ptopilot/pipeline/health.py`

```python
"""The admin health email sent after every scan (spec §10)."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Sequence

from sqlalchemy import func, select

from ptopilot import config
from ptopilot.db.models import Candidate, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import month_of
from ptopilot.pipeline.runner import StageResult


def build_report(ctx: RunContext, results: Sequence[StageResult]) -> tuple[str, str]:
    """(subject, plain-text body)."""
    failed = [r.stage for r in results if r.status == "failed"]
    subject = f"ptopilot scan {ctx.run_date}: " + (f"FAILED ({', '.join(failed)})" if failed else "OK")
    lines = [subject, "", "Stages:"]
    for r in results:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(r.counts.items()))
        lines.append(f"  {r.stage:<12} {r.status:<8} {detail}")
        if r.error:
            label = "reason" if r.status == "skipped" else "error"
            lines.append(f"  {'':<12} {label}: {r.error}")

    with session_scope(ctx.engine) as s:
        deals = Counter(
            dict(
                s.execute(
                    select(Candidate.deal_level, func.count())
                    .where(Candidate.run_date == ctx.run_date)
                    .group_by(Candidate.deal_level)
                ).all()
            )
        )
        lines += [
            "",
            f"Candidates: great={deals['great']} good={deals['good']} none={deals['none']}",
            "",
            "Budgets:",
        ]
        for source, caps in sorted(config.SOURCE_BUDGETS.items()):
            used = (
                s.scalar(
                    select(SourceBudget.calls_used).filter_by(source=source, period=month_of(ctx.run_date))
                )
                or 0
            )
            lines.append(
                f"  {source}: {used}/{caps['per_month']} this month ({caps['per_month'] - used} left)"
            )
    return subject, "\n".join(lines)


def send_report(ctx: RunContext, results: Sequence[StageResult]) -> str:
    """Email the report when configured and not a dry run; always return the text."""
    subject, text = build_report(ctx, results)
    if ctx.emailer and ctx.admin_email and not ctx.dry_run:
        ctx.emailer.send(ctx.admin_email, subject, f"<pre>{html.escape(text)}</pre>", text)
    return text
```

- [ ] **Step 5: Write** `ptopilot/pipeline/__main__.py`

```python
"""CLI: python -m ptopilot.pipeline run [--stage NAME ...] [--date YYYY-MM-DD] [--dry-run]

Exits 1 if any stage failed, so the GitHub Actions run shows red.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime

from ptopilot.notify.email import EmailError
from ptopilot.pipeline.context import build_context
from ptopilot.pipeline.health import send_report
from ptopilot.pipeline.runner import STAGES, run_pipeline
from ptopilot.settings import Settings

log = logging.getLogger("ptopilot.pipeline")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO, and SerpApi's api_key is a query parameter.
    # primp (fast-flights' HTTP client) logs every Google URL at INFO, which is just noise.
    for noisy in ("httpx", "primp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the daily scan")
    run.add_argument(
        "--stage", action="append", choices=list(STAGES), help="run only this stage (repeatable)"
    )
    run.add_argument("--date", type=date.fromisoformat, default=None, help="run date (default: today, UTC)")
    run.add_argument("--dry-run", action="store_true", help="do everything except send the health email")
    args = parser.parse_args(argv)

    configure_logging()
    ctx = build_context(Settings.from_env(), args.date or datetime.now(UTC).date(), dry_run=args.dry_run)
    results = run_pipeline(ctx, args.stage)
    try:
        print(send_report(ctx, results))
    except EmailError as exc:
        log.error("health email not sent: %s", exc)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Write** `.github/workflows/scan.yml`

```yaml
name: scan
on:
  schedule:
    - cron: "0 6 * * *"  # daily, 06:00 UTC
  workflow_dispatch:
    inputs:
      date:
        description: "Run date YYYY-MM-DD (blank = today, UTC)"
        required: false
      stage:
        description: "Run only this stage (blank = all)"
        required: false
        type: choice
        options: ["", expand, broad_scan, shortlist, live_verify, baselines, score]
concurrency:
  group: scan
  cancel-in-progress: false
jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      TRAVELPAYOUTS_TOKEN: ${{ secrets.TRAVELPAYOUTS_TOKEN }}
      SERPAPI_KEY: ${{ secrets.SERPAPI_KEY }}
      RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
      ADMIN_EMAIL: ${{ secrets.ADMIN_EMAIL }}
      EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install -e .
      - run: python -m alembic upgrade head
      - name: Run pipeline
        run: |
          args=(run)
          if [ -n "${{ inputs.date }}" ]; then args+=(--date "${{ inputs.date }}"); fi
          if [ -n "${{ inputs.stage }}" ]; then args+=(--stage "${{ inputs.stage }}"); fi
          python -m ptopilot.pipeline "${args[@]}"
```

- [ ] **Step 7: Write** `.github/workflows/keepalive.yml`

```yaml
name: keepalive
# GitHub disables scheduled workflows after 60 days without repository activity.
on:
  schedule:
    - cron: "0 12 1 * *"  # monthly
  workflow_dispatch:
permissions:
  contents: write
jobs:
  keepalive:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: |
          date -u +%Y-%m-%dT%H:%M:%SZ > .keepalive
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add .keepalive
          git commit -m "chore: keepalive" && git push
```

- [ ] **Step 8: Write** `README.md`

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

## Daily scan

```powershell
.venv/Scripts/python -m ptopilot.pipeline run --dry-run            # whole pipeline, no health email
.venv/Scripts/python -m ptopilot.pipeline run --stage expand       # one stage (repeatable)
.venv/Scripts/python -m ptopilot.pipeline run --date 2026-10-20    # re-run a past day
```

Stages: `expand → broad_scan → shortlist → live_verify → baselines → score`. Each run is recorded in `pipeline_runs`. A failed `expand` or `broad_scan` stops the rest; a failed `live_verify` does not. In production, `.github/workflows/scan.yml` runs it daily at 06:00 UTC (and on demand from the Actions tab, with optional date/stage inputs); `keepalive.yml` stops GitHub from disabling the schedule.

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

- [ ] **Step 9: Run tests and lint to verify they pass**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/pipeline/test_runner.py -q && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: all PASS with none skipped, `All checks passed!`, and no files needing reformatting.

- [ ] **Step 10: Real dry run against the dev database (optional, uses live Google; about 1 minute)**

With no users in the dev database, `.venv/Scripts/python -m ptopilot.pipeline run --dry-run` should print a report that starts `ptopilot scan <today>: OK`, with `expand ok route_queries=0`, `broad_scan skipped` and `live_verify skipped` or `ok`, and exit 0. Don't seed real-looking users into the dev database here; Plan 5's onboarding does that.

- [ ] **Step 11: Commit and push**

```bash
git add ptopilot/pipeline/runner.py ptopilot/pipeline/health.py ptopilot/pipeline/__main__.py .github/workflows/scan.yml .github/workflows/keepalive.yml README.md tests/pipeline/test_runner.py
git commit -m "feat(pipeline): runner, health email, CLI, scheduled scan workflow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Then: `& "C:\Program Files\GitHub CLI\gh.exe" run watch --exit-status` → CI green. **Don't trigger `scan.yml` yet.** It needs the `DATABASE_URL` (Neon) secret, which is part of the deployment step.

---

### Final check

- [ ] `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q` → **220 passed, 1 deselected**.
- [ ] `git status` is clean, `git log origin/main..main` is empty, and the latest `ci` run is green.

## Before the first real scheduled scan (deployment, needs the user)

1. Create a Neon project and copy its connection string.
2. Add GitHub Actions secrets with `& "C:\Program Files\GitHub CLI\gh.exe" secret set NAME`: `DATABASE_URL`, plus whichever of `TRAVELPAYOUTS_TOKEN`, `SERPAPI_KEY`, `RESEND_API_KEY`, `ADMIN_EMAIL` exist.
3. Trigger `scan.yml` once by hand: `& "C:\Program Files\GitHub CLI\gh.exe" workflow run scan.yml`. Watch it, and read the health email or the log.

## What Plan 4 builds on this

The digest reads `candidates` with `deal_level in (good, great)`, links them to `price_observations` for flight details and to `tracker_route_links` for PTO facts and season, and records `digest_sends`.
