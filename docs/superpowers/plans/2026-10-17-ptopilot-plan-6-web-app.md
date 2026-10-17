# ptopilot Plan 6: The Web App (sign-in, profile, dashboard, snooze links) and Deployment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A small web app on Render's free tier that covers the human side of ptopilot:
- sign in by emailed link (invite-only)
- create or edit your travel profile in a form instead of YAML
- a dashboard of trackers and current best prices, with snooze controls
- the confirmation pages behind the digest's new snooze buttons ("Not this trip", "Snooze 30 days", "Not this year", "Only if under $X")

**Architecture:**
- `ptopilot/links.py`: signed tokens (itsdangerous), shared by the digest job and the web app through one `SECRET_KEY`.
- `ptopilot/trackers.py`: the tracker actions.
- `ptopilot/web/`: a FastAPI app factory (`create_app`) with server-rendered Jinja pages, plain HTML forms (POST, then 303 redirect) and a signed SameSite=Lax session cookie.
- The profile page converts the form to the YAML-shaped dict and reuses `profiles.parse_profile`/`apply_profile`.
- The digest adds snooze buttons when `APP_BASE_URL` and `SECRET_KEY` are both set.
- `render.yaml` deploys the app as a Render Blueprint.

**Tech Stack:** adds FastAPI, Uvicorn, itsdangerous and python-multipart (forms). No JavaScript.

**Spec:** [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](../specs/2026-10-16-ptopilot-design.md) §9, including "Implementation notes (Plan 6)".

## Global Constraints

- New runtime dependencies (exactly these): `fastapi>=0.115`, `uvicorn>=0.30`, `itsdangerous>=2.2`, `python-multipart>=0.0.9`.
- **Snooze links never act on GET.** `GET /s/{token}` only shows a confirmation; `POST` acts. Mail scanners pre-fetch links.
- **`POST /login` answers identically** whether or not the address is invited.
- **`SECRET_KEY` is required** to start the web app, and must be the same value for Render and the GitHub `digest` workflow. Never print it, commit it, or put it in a plan or log.
- Profile validation goes **only** through `profiles.parse_profile`, so form and YAML rules can't drift apart.
- Default `pytest` never touches the network. Run database tests with `PTOPILOT_REQUIRE_DB=1`, as below.
- `ruff check .` and `ruff format --check .` must pass.
- **Work directly on `main`; every task ends with a commit and a `git push`, and the full suite is green after each task.** Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Commands run from `C:\Users\nickd\dev\ptopilot` with `.venv/Scripts/python`. The local Postgres must be running (port 5433).

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **An email security scanner opens every link in the digest** → nothing changes until someone presses Confirm. *Task 3: `test_opening_a_link_only_shows_a_confirmation`.*
2. **A forged, tampered, or stale link**, or one for a tracker that was deleted → a 400 page with a plain explanation, nothing changed. *Task 1: `test_expired_and_tampered_tokens_are_rejected`, `test_unknown_action_kind_is_rejected`; Task 3: `test_tampered_or_stale_links_are_refused`, `test_bad_and_expired_links_are_refused`.*
3. **Someone submits another traveler's tracker id** → 404, and nothing changes. *Task 3: `test_cannot_touch_someone_elses_tracker`.*
4. **A profile form with several mistakes, or untouched blank rows** → every problem listed, the submitted values kept, nothing saved, and blank rows (which still carry a default priority) ignored. *Task 3: `test_invalid_profile_lists_every_problem_and_saves_nothing`, `test_form_to_profile_maps_fields_and_skips_blank_rows`.*
5. **The web app isn't deployed or configured yet** → the digest has no snooze buttons, rather than dead links. *Task 2: `test_no_snooze_buttons_without_the_web_app`.*

## Verified before writing (2026-10-17)

- **A real local server** (uvicorn, dev database, example profile): signed in through the logged link, then checked the dashboard (PTO bar, 4 trackers, empty-state message) and the pre-filled profile form in Chromium at 400px wide. The bucket-list rows were reworked for phones after the first screenshot.
- **All three code tasks replayed in order** on a fresh copy of `main` (`sim_plan6.sh`). Each task's tests failed for the expected reason, then passed, with the full suite green after every task: 298 → 302 → 321. The final tree matched the verified copy exactly.
- Verified files: `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p6`.

## File structure

```
pyproject.toml                       # + fastapi, uvicorn, itsdangerous, python-multipart; web template package data
ptopilot/settings.py                 # + SECRET_KEY, APP_BASE_URL
ptopilot/core/geo.py                 # + Geo.destinations()
ptopilot/links.py                    # login/action tokens, Action, ACTION_LABELS, action_links
ptopilot/trackers.py                 # snooze, unsnooze, exclude_trip, apply_action
ptopilot/profiles.py                 # + `invite EMAIL` command
ptopilot/digest/select.py            # build_digests(..., user_id=None)
ptopilot/digest/render.py, send.py, __main__.py, templates/*.j2   # snooze buttons when configured
ptopilot/web/__init__.py, app.py, main.py, forms.py
ptopilot/web/templates/{base,login,login_sent,message,action_confirm,dashboard,profile}.html
.github/workflows/digest.yml         # + SECRET_KEY secret, APP_BASE_URL variable
render.yaml                          # Render Blueprint
README.md                            # + Web app, Deploying, config rows
tests/test_links.py, tests/test_trackers.py, tests/web/{__init__,conftest,test_auth,test_profile_and_dashboard,test_snooze_links,test_cli_wiring}.py
```

Most tasks modify existing files; each "Write" step gives the **complete new file**.

---

### Task 1: Signed links, tracker actions, settings

**Files:**
- Modify (replace whole file): `pyproject.toml`, `ptopilot/settings.py`, `ptopilot/core/geo.py`, `tests/test_settings.py`, `tests/core/test_geo.py`
- Create: `ptopilot/links.py`, `ptopilot/trackers.py`
- Test: `tests/test_links.py`, `tests/test_trackers.py` (plus the two modified test files)

**Interfaces:**
- Produces: `Settings.secret_key`, `Settings.app_base_url` (trailing slash stripped); `Geo.destinations()`; `links.LOGIN_MAX_AGE_S`, `ACTION_MAX_AGE_S`, `ACTION_LABELS` (trip/snooze30/year/under), `TokenError`, `login_token(secret, email)`, `read_login_token(secret, token, max_age=…)`, `Action(tracker_id, kind, depart=None, ret=None)`, `action_token(secret, action)`, `read_action_token(secret, token, max_age=…)`, `action_links(base_url, secret, tracker_id, depart, ret) -> list[(label, url)]`; `trackers.snooze`, `unsnooze`, `exclude_trip`, `apply_action(session, tracker, action, today, price=None) -> str`.

After writing `pyproject.toml`, install the new dependencies: `.venv/Scripts/python -m pip install -e ".[dev]"`. Expected: fastapi, uvicorn, itsdangerous and python-multipart installed.

- [ ] **Step 1: Write** `pyproject.toml`

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
"ptopilot.web" = ["templates/*.html"]

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

- [ ] **Step 2: Write the failing test file** `tests/test_settings.py`

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


def test_web_settings():
    s = Settings.from_env({"SECRET_KEY": "k", "APP_BASE_URL": "https://ptopilot.onrender.com/"})
    assert (s.secret_key, s.app_base_url) == ("k", "https://ptopilot.onrender.com")
    assert Settings.from_env({}).app_base_url == ""
```

- [ ] **Step 3: Write the failing test file** `tests/core/test_geo.py`

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


def test_destinations_are_listed_by_name():
    assert [d.code for d in GEO.destinations()] == ["LAX", "TH"]  # Los Angeles, Thailand
```

- [ ] **Step 4: Write the failing test file** `tests/test_links.py`

```python
from datetime import date

import pytest
from itsdangerous import URLSafeTimedSerializer

from ptopilot.links import (
    Action,
    TokenError,
    action_links,
    action_token,
    login_token,
    read_action_token,
    read_login_token,
)

KEY = "test-secret"


def test_login_token_round_trip_and_normalises_email():
    assert read_login_token(KEY, login_token(KEY, " Nick@Example.com ")) == "nick@example.com"


def test_expired_and_tampered_tokens_are_rejected():
    token = login_token(KEY, "nick@example.com")
    with pytest.raises(TokenError, match="expired"):
        read_login_token(KEY, token, max_age=-1)
    with pytest.raises(TokenError, match="not valid"):
        read_login_token("other-secret", token)
    with pytest.raises(TokenError, match="not valid"):
        read_action_token(KEY, token)  # a login token is not an action token (different salt)


def test_action_token_round_trip():
    action = Action(7, "trip", date(2027, 3, 5), date(2027, 3, 14))
    assert read_action_token(KEY, action_token(KEY, action)) == action
    assert read_action_token(KEY, action_token(KEY, Action(7, "snooze30"))) == Action(7, "snooze30")


def test_unknown_action_kind_is_rejected():
    forged = URLSafeTimedSerializer(KEY, salt="action").dumps({"t": 7, "a": "delete_everything"})
    with pytest.raises(TokenError):
        read_action_token(KEY, forged)


def test_action_links_cover_every_button():
    links = action_links("https://app.example", KEY, 7, date(2027, 3, 5), date(2027, 3, 14))
    labels = [label for label, _ in links]
    assert labels == ["Not this trip", "Snooze 30 days", "Not this year", "Only if under $…"]
    assert all(url.startswith("https://app.example/s/") for _, url in links)
    assert read_action_token(KEY, links[0][1].rsplit("/", 1)[1]).kind == "trip"


def test_missing_secret_is_a_clear_error():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        login_token("", "nick@example.com")
```

- [ ] **Step 5: Write the failing test file** `tests/test_trackers.py`

```python
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from ptopilot.db.models import Tracker, TrackerExclusion, User
from ptopilot.links import Action
from ptopilot.trackers import apply_action

TODAY = date(2026, 10, 20)


@pytest.fixture
def tracker(session):
    user = User(
        email="t@example.com",
        home_airport="JFK",
        country="US",
        holiday_calendar="US",
        pto_days_total=15,
        max_trip_days=16,
    )
    session.add(user)
    session.flush()
    t = Tracker(user_id=user.id, destination_code="AZORES", min_stay_days=7, max_stay_days=10)
    session.add(t)
    session.flush()
    return t


def test_not_this_trip_adds_an_exclusion_once(session, tracker):
    action = Action(tracker.id, "trip", date(2027, 3, 5), date(2027, 3, 14))
    apply_action(session, tracker, action, TODAY)
    message = apply_action(session, tracker, action, TODAY)  # clicking twice is harmless
    rows = list(session.scalars(select(TrackerExclusion).where(TrackerExclusion.tracker_id == tracker.id)))
    assert [(r.depart_date, r.return_date) for r in rows] == [(date(2027, 3, 5), date(2027, 3, 14))]
    assert "Mar 5 → Mar 14" in message


def test_snooze_30_days_and_not_this_year(session, tracker):
    apply_action(session, tracker, Action(tracker.id, "snooze30"), TODAY)
    assert tracker.snoozed_until == date(2026, 11, 19)
    apply_action(session, tracker, Action(tracker.id, "year", date(2027, 3, 5), date(2027, 3, 14)), TODAY)
    assert tracker.snoozed_until == date(2027, 12, 31)  # the trip's year, not today's


def test_only_if_under_sets_max_price(session, tracker):
    message = apply_action(session, tracker, Action(tracker.id, "under"), TODAY, price=Decimal("750"))
    assert tracker.max_price == Decimal("750") and "$750" in message
    with pytest.raises(ValueError, match="above zero"):
        apply_action(session, tracker, Action(tracker.id, "under"), TODAY, price=Decimal("0"))


def test_trip_action_needs_dates(session, tracker):
    with pytest.raises(ValueError, match="no trip"):
        apply_action(session, tracker, Action(tracker.id, "trip"), TODAY)
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/test_settings.py tests/core/test_geo.py tests/test_links.py tests/test_trackers.py -q`
Expected: collection ERRORs in `tests/test_links.py` and `tests/test_trackers.py`: `ModuleNotFoundError: No module named 'ptopilot.links'`.

- [ ] **Step 7: Write** `ptopilot/settings.py`

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
    secret_key: str = (
        ""  # signs sign-in links, sessions and snooze links; shared by the web app and the digest job
    )
    app_base_url: str = (
        ""  # public URL of the web app, e.g. https://ptopilot.onrender.com; enables snooze links
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            database_url=normalize_database_url(env.get("DATABASE_URL") or DEV_DATABASE_URL),
            travelpayouts_token=env.get("TRAVELPAYOUTS_TOKEN", ""),
            serpapi_key=env.get("SERPAPI_KEY", ""),
            resend_api_key=env.get("RESEND_API_KEY", ""),
            admin_email=env.get("ADMIN_EMAIL", ""),
            email_from=env.get("EMAIL_FROM") or DEFAULT_EMAIL_FROM,
            secret_key=env.get("SECRET_KEY", ""),
            app_base_url=(env.get("APP_BASE_URL") or "").rstrip("/"),
        )
```

- [ ] **Step 8: Write** `ptopilot/core/geo.py`

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

- [ ] **Step 9: Write** `ptopilot/links.py`

```python
"""Signed tokens for sign-in links and one-click tracker actions (snooze buttons in the digest).

Shared by the digest job and the web app, so both must use the same SECRET_KEY. No web imports here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

LOGIN_MAX_AGE_S = 15 * 60
ACTION_MAX_AGE_S = 30 * 24 * 3600

ACTION_LABELS = {
    "trip": "Not this trip",
    "snooze30": "Snooze 30 days",
    "year": "Not this year",
    "under": "Only if under $…",
}


class TokenError(Exception):
    """A token that is malformed, tampered with, or expired."""


def _serializer(secret: str, salt: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("SECRET_KEY is not set")
    return URLSafeTimedSerializer(secret, salt=salt)


def _read(secret: str, salt: str, token: str, max_age: int):
    try:
        return _serializer(secret, salt).loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise TokenError("this link has expired") from exc
    except BadSignature as exc:
        raise TokenError("this link is not valid") from exc


def login_token(secret: str, email: str) -> str:
    return _serializer(secret, "login").dumps(email.strip().lower())


def read_login_token(secret: str, token: str, max_age: int = LOGIN_MAX_AGE_S) -> str:
    return _read(secret, "login", token, max_age)


@dataclass(frozen=True)
class Action:
    tracker_id: int
    kind: str  # one of ACTION_LABELS
    depart: date | None = None  # the trip the link was attached to
    ret: date | None = None


def action_token(secret: str, action: Action) -> str:
    payload = {"t": action.tracker_id, "a": action.kind}
    if action.depart and action.ret:
        payload |= {"d": action.depart.isoformat(), "r": action.ret.isoformat()}
    return _serializer(secret, "action").dumps(payload)


def read_action_token(secret: str, token: str, max_age: int = ACTION_MAX_AGE_S) -> Action:
    data = _read(secret, "action", token, max_age)
    if not isinstance(data, dict) or data.get("a") not in ACTION_LABELS or not isinstance(data.get("t"), int):
        raise TokenError("this link is not valid")
    depart = date.fromisoformat(data["d"]) if data.get("d") else None
    ret = date.fromisoformat(data["r"]) if data.get("r") else None
    return Action(data["t"], data["a"], depart, ret)


def action_links(
    base_url: str, secret: str, tracker_id: int, depart: date, ret: date
) -> list[tuple[str, str]]:
    """(label, url) for each snooze button on a deal card."""
    return [
        (label, f"{base_url}/s/{action_token(secret, Action(tracker_id, kind, depart, ret))}")
        for kind, label in ACTION_LABELS.items()
    ]
```

- [ ] **Step 10: Write** `ptopilot/trackers.py`

```python
"""Tracker actions shared by the dashboard and the digest's snooze links."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ptopilot.db.models import Tracker, TrackerExclusion
from ptopilot.links import Action


def snooze(tracker: Tracker, until: date) -> None:
    tracker.snoozed_until = until


def unsnooze(tracker: Tracker) -> None:
    tracker.snoozed_until = None


def exclude_trip(s: Session, tracker: Tracker, depart: date, ret: date) -> None:
    s.execute(
        insert(TrackerExclusion)
        .values(tracker_id=tracker.id, depart_date=depart, return_date=ret)
        .on_conflict_do_nothing()
    )


def apply_action(
    s: Session, tracker: Tracker, action: Action, today: date, price: Decimal | None = None
) -> str:
    """Apply a snooze-link action; returns a sentence describing what happened."""
    if action.kind == "trip":
        if not (action.depart and action.ret):
            raise ValueError("this link has no trip attached")
        exclude_trip(s, tracker, action.depart, action.ret)
        trip = f"{action.depart:%b} {action.depart.day} → {action.ret:%b} {action.ret.day}"
        return f"Got it: {trip} won't be suggested again."
    if action.kind == "snooze30":
        until = today + timedelta(days=30)
        snooze(tracker, until)
        return f"Snoozed until {until:%b} {until.day}, {until.year}."
    if action.kind == "year":
        year = action.depart.year if action.depart else today.year
        snooze(tracker, date(year, 12, 31))
        return f"Snoozed for the rest of {year}."
    if action.kind == "under":
        if price is None or price <= 0:
            raise ValueError("enter a price above zero")
        tracker.max_price = price
        return f"You'll only hear about this destination under ${price:,.0f}."
    raise ValueError(f"unknown action {action.kind!r}")
```

- [ ] **Step 11: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/test_settings.py tests/core/test_geo.py tests/test_links.py tests/test_trackers.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **298 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 12: Commit and push**

```bash
git add pyproject.toml ptopilot/settings.py ptopilot/core/geo.py ptopilot/links.py ptopilot/trackers.py tests/test_settings.py tests/core/test_geo.py tests/test_links.py tests/test_trackers.py
git commit -m "feat: signed sign-in and action links; tracker actions; web settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Snooze buttons in the digest; invite command; per-user digest building

**Files:**
- Modify (replace whole file): `ptopilot/digest/render.py`, `ptopilot/digest/send.py`, `ptopilot/digest/__main__.py`, `ptopilot/digest/select.py`, both digest templates, `ptopilot/profiles.py`, `.github/workflows/digest.yml`, `tests/digest/test_render.py`
- Create: `tests/web/__init__.py` (empty), `tests/web/test_cli_wiring.py`

**Interfaces:**
- Consumes: `action_links` (Task 1).
- Produces: `render(digest, now=None, links=None)` with `LinkBuilder = Callable[[DealCard], list[tuple[str, str]]]`; `deliver(..., links=None)`; the digest CLI builds links only when `APP_BASE_URL` and `SECRET_KEY` are set; `build_digests(..., user_id=None)`; CLI `python -m ptopilot.profiles invite EMAIL` (exit 2 on a non-email).

- [ ] **Step 1: Create the empty file** `tests/web/__init__.py`

- [ ] **Step 2: Write the failing test file** `tests/digest/test_render.py`

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
        "departs 10:00pm", "TP 202", "(outbound flight)", "checked 9 hours ago", "See flights",
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

- [ ] **Step 3: Write the failing test file** `tests/web/test_cli_wiring.py`

```python
from sqlalchemy import select

from ptopilot import profiles
from ptopilot.db.models import Invite
from ptopilot.db.session import session_scope
from ptopilot.digest import __main__ as digest_cli
from ptopilot.links import read_action_token
from tests.conftest import TEST_URL
from tests.digest.conftest import RUN, add_candidate, add_tracker, add_user


def test_digest_gets_snooze_buttons_when_the_web_app_is_configured(clean_engine, monkeypatch, tmp_path):
    tid = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, tid, 600)
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("APP_BASE_URL", "https://ptopilot.example")
    assert digest_cli.main(["send", "--date", str(RUN), "--preview", str(tmp_path)]) == 0
    text = (tmp_path / f"digest-1-{RUN}.txt").read_text(encoding="utf-8")
    link = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("Not this trip: "))
    assert link.startswith("https://ptopilot.example/s/")
    assert read_action_token("k", link.rsplit("/", 1)[1]).tracker_id == tid


def test_no_snooze_buttons_without_the_web_app(clean_engine, monkeypatch, tmp_path):
    add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    digest_cli.main(["send", "--date", str(RUN), "--preview", str(tmp_path)])
    assert "/s/" not in (tmp_path / f"digest-1-{RUN}.txt").read_text(encoding="utf-8")


def test_invite_command(clean_engine, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    assert profiles.main(["invite", " Friend@Example.com "]) == 0
    assert profiles.main(["invite", "Friend@Example.com"]) == 0  # idempotent
    assert profiles.main(["invite", "not-an-email"]) == 2
    with session_scope(clean_engine) as s:
        assert list(s.scalars(select(Invite.email))) == ["friend@example.com"]
    assert "invited friend@example.com" in capsys.readouterr().out
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest tests/web/test_cli_wiring.py -q`
Expected: 3 failed, 25 passed: `TypeError: render() got an unexpected keyword argument 'links'`; the digest CLI preview has no `Not this trip:` line; `argparse … invalid choice: 'invite' (choose from 'load')`.

- [ ] **Step 5: Write** `ptopilot/digest/render.py`

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
_env.filters.update(money=money, day=day, duration=duration, clock=clock, stops=stops)


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

- [ ] **Step 6: Write** `ptopilot/digest/templates/digest.html.j2`

```jinja
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>ptopilot digest</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#111827;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;">

  <tr><td style="padding:0 4px 16px;">
    <div style="font-size:13px;color:#6b7280;letter-spacing:.04em;text-transform:uppercase;">ptopilot · {{ digest.run_date | day }}</div>
    {% if digest.quiet %}
    <h1 style="margin:6px 0 0;font-size:22px;line-height:1.3;">A quiet week: nothing well below typical yet</h1>
    <p style="margin:8px 0 0;font-size:15px;color:#374151;">Your trackers are still watching. Here's where prices stand.</p>
    {% else %}
    <h1 style="margin:6px 0 0;font-size:22px;line-height:1.3;">{{ digest.deals | length }} trip{{ "s" if digest.deals | length != 1 }} worth a look</h1>
    {% endif %}
  </td></tr>

  {% for d in digest.deals %}
  <tr><td style="padding:0 0 14px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;">
      <tr><td style="padding:16px 18px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="font-size:18px;font-weight:700;">{{ d.destination }}</td>
          <td align="right" style="font-size:12px;">
            <span style="display:inline-block;padding:3px 8px;border-radius:999px;background:{{ '#dcfce7' if d.deal_level == 'great' else ('#e0f2fe' if d.deal_level == 'good' else '#f3f4f6') }};color:#111827;font-weight:600;">{{ levels[d.deal_level] }}</span>
            <span style="display:inline-block;padding:3px 8px;margin-left:4px;border-radius:999px;background:#f3f4f6;color:#374151;">Go-now {{ d.go_now }}</span>
          </td>
        </tr></table>
        <div style="margin-top:4px;font-size:14px;color:#374151;">
          {{ d.depart_date | day }} → {{ d.return_date | day }}{% if d.evening_departure %} · leave after work{% endif %}
          · {{ d.origin }} → {{ d.dest_airport }}{% if d.open_jaw %}, home from {{ d.return_airport }}{% endif %}
        </div>
        <div style="margin-top:12px;font-size:26px;font-weight:700;">{{ d.price | money(d.currency) }}
          <span style="font-size:14px;font-weight:400;color:#6b7280;">{{ "both flights" if d.open_jaw else "round trip" }}{% if d.typical %} · typically ~{{ d.typical | money(d.currency) }}{% if d.pct_below and d.pct_below > 0 %} ({{ d.pct_below }}% below){% endif %}{% endif %}</span>
        </div>
        <div style="margin-top:8px;font-size:14px;color:#111827;">
          Uses <b>{{ d.pto_cost }} PTO day{{ "s" if d.pto_cost != 1 }}</b> for {{ d.days_away }} days away{% if d.days_off %} ({{ d.days_off | join(", ") }} gives you a free day){% endif %}
        </div>
        {% if d.carrier %}
        <div style="margin-top:6px;font-size:14px;color:#374151;">
          {{ d.carrier }} · {{ d.stops | stops }}{% if d.duration_min %} · {{ d.duration_min | duration }} out{% endif %}{% if d.outbound_departure %}, departs {{ d.outbound_departure | clock }}{% endif %}{% if d.flight_numbers %} · {{ d.flight_numbers | join(", ") }}{% endif %}
          <span style="color:#9ca3af;">(outbound flight)</span>
        </div>
        {% endif %}
        {% if d.weather_note %}
        <div style="margin-top:6px;font-size:14px;color:#374151;">{{ "Off-season: " if d.season_rating == "avoid" }}{{ d.weather_note }}</div>
        {% endif %}
        <div style="margin-top:8px;font-size:12px;color:#6b7280;">
          {{ "Live price" if d.verified else "Cached price, not yet confirmed live" }}{% if checked[d.candidate_id] %}, {{ checked[d.candidate_id] }}{% endif %}. Fares change fast.
          {% if d.confidence == "low" %}Typical price is still being learned (low confidence).{% endif %}
        </div>
        {% if d.deep_link %}
        <div style="margin-top:14px;">
          <a href="{{ d.deep_link }}" style="display:inline-block;padding:10px 16px;border-radius:8px;background:#111827;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;">See flights →</a>
        </div>
        {% endif %}
        {% if actions[d.candidate_id] %}
        <div style="margin-top:12px;font-size:12px;color:#6b7280;">
          {% for label, url in actions[d.candidate_id] %}<a href="{{ url }}" style="color:#6b7280;">{{ label }}</a>{{ " · " if not loop.last }}{% endfor %}
        </div>
        {% endif %}
      </td></tr>
    </table>
  </td></tr>
  {% endfor %}

  <tr><td style="padding:10px 4px 6px;font-size:15px;font-weight:700;">Your trackers</td></tr>
  <tr><td>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;font-size:13px;">
      <tr style="color:#6b7280;">
        <td style="padding:10px 12px;">Destination</td><td style="padding:10px 6px;">Best now</td><td style="padding:10px 6px;">Typical</td><td style="padding:10px 6px;">7-day</td><td style="padding:10px 12px;">Next good month</td>
      </tr>
      {% for t in digest.trackers %}
      <tr style="border-top:1px solid #f3f4f6;">
        <td style="padding:8px 12px;border-top:1px solid #f3f4f6;">{{ t.destination }}{% if t.snoozed_until %} <span style="color:#9ca3af;">(snoozed to {{ t.snoozed_until | day }})</span>{% endif %}</td>
        <td style="padding:8px 6px;border-top:1px solid #f3f4f6;">{{ t.best_price | money }}</td>
        <td style="padding:8px 6px;border-top:1px solid #f3f4f6;">{{ t.typical | money }}</td>
        <td style="padding:8px 6px;border-top:1px solid #f3f4f6;">{{ arrows[t.trend] }}</td>
        <td style="padding:8px 12px;border-top:1px solid #f3f4f6;">{{ t.next_good_month or "—" }}</td>
      </tr>
      {% endfor %}
    </table>
  </td></tr>

  <tr><td style="padding:16px 4px 0;font-size:12px;color:#9ca3af;">
    Prices are per person in economy and change constantly; always confirm before booking. Sent by ptopilot to {{ digest.email }}.
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>
```

- [ ] **Step 7: Write** `ptopilot/digest/templates/digest.txt.j2`

```jinja
ptopilot · {{ digest.run_date | day }}
{% if digest.quiet %}
A quiet week: nothing well below typical yet. Your trackers are still watching.
{% else %}
{{ digest.deals | length }} trip{{ "s" if digest.deals | length != 1 }} worth a look
{% endif %}
{% for d in digest.deals %}

== {{ d.destination }}: {{ levels[d.deal_level] }}, go-now {{ d.go_now }}
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
See flights: {{ d.deep_link }}
{% endif %}
{% for label, url in actions[d.candidate_id] %}
{{ label }}: {{ url }}
{% endfor %}
{% endfor %}

Your trackers
{% for t in digest.trackers %}
- {{ t.destination }}: best {{ t.best_price | money }}, typical {{ t.typical | money }}, 7-day {{ arrows[t.trend] }}, next good month {{ t.next_good_month or "-" }}{% if t.snoozed_until %} (snoozed to {{ t.snoozed_until | day }}){% endif %}

{% endfor %}

Prices change constantly; always confirm before booking.
```

- [ ] **Step 8: Write** `ptopilot/digest/send.py`

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
        subject, html, text = render(digest, links=links)
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

- [ ] **Step 9: Write** `ptopilot/digest/__main__.py`

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

    counts = deliver(engine, digests, today, emailer=emailer, preview_dir=args.preview, links=links)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to send"
    print(f"digests for {today}: {len(digests)} built; {summary}")
    if args.preview:
        print(f"preview written to {args.preview.resolve()}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10: Write** `ptopilot/digest/select.py`

```python
"""Choose what goes into each traveler's digest (spec §8)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select

from ptopilot import config
from ptopilot.core.geo import Geo
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


@dataclass
class Digest:
    user_id: int
    email: str
    run_date: date
    deals: list[DealCard]
    trackers: list[TrackerRow]

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
        if prior is not None and c.price > prior * Decimal(str(config.DIGEST_RESEND_FACTOR)):
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
                )
            )
        digests.append(Digest(user.id, user.email, run_date, sorted(chosen, key=by_score), rows_for_user))
    return digests
```

- [ ] **Step 11: Write** `ptopilot/profiles.py`

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

- [ ] **Step 12: Write** `.github/workflows/digest.yml`

```yaml
name: digest
on:
  schedule:
    - cron: "0 12 * * 1,4"  # Mondays and Thursdays, 12:00 UTC (~8am US Eastern), after the 06:00 scan
  workflow_dispatch:
    inputs:
      min_level:
        description: "Lowest deal level to include (none = every priced trip, for tuning)"
        required: false
        default: good
        type: choice
        options: [good, great, none]
concurrency:
  group: digest
  cancel-in-progress: false
permissions:
  contents: read
jobs:
  digest:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
      EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
      SECRET_KEY: ${{ secrets.SECRET_KEY }}  # must match the web app's, or snooze links won't verify
      APP_BASE_URL: ${{ vars.APP_BASE_URL }}  # e.g. https://ptopilot.onrender.com; empty = no snooze buttons
      MIN_LEVEL: ${{ inputs.min_level || 'good' }}  # passed via env, never spliced into the shell script
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install -e .
      - run: python -m ptopilot.digest send --min-level "$MIN_LEVEL"
```

- [ ] **Step 13: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest tests/web/test_cli_wiring.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **302 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 14: Commit and push**

```bash
git add ptopilot/digest ptopilot/profiles.py .github/workflows/digest.yml tests/digest/test_render.py tests/web/__init__.py tests/web/test_cli_wiring.py
git commit -m "feat(digest): snooze buttons when the web app is configured; profiles invite command" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 3: The web app and its deployment blueprint

**Files:**
- Create: `ptopilot/web/__init__.py` (empty), `ptopilot/web/forms.py`, `ptopilot/web/app.py`, `ptopilot/web/main.py`, `ptopilot/web/templates/*.html` (7 files), `render.yaml`
- Modify (replace whole file): `README.md`
- Test: `tests/web/conftest.py`, `tests/web/test_auth.py`, `tests/web/test_profile_and_dashboard.py`, `tests/web/test_snooze_links.py`

**Interfaces:**
- Consumes: Tasks 1–2, `profiles.parse_profile/apply_profile`, `build_digests(user_id=…)`, `digest.render.money/day`.
- Produces: `create_app(settings, engine=None, emailer=None, geo=None, seasons=None, today=None) -> FastAPI` (raises `ValueError` without `SECRET_KEY`); `ptopilot.web.main:app`; routes `GET /healthz`, `GET /favicon.ico` (204), `GET|POST /login`, `GET /auth?token=`, `POST /logout`, `GET /` (dashboard), `POST /trackers/{{id}}/snooze` and `/unsnooze`, `GET|POST /profile`, `GET|POST /s/{{token}}`; `forms.form_to_profile(form, email)`, `profile_to_form(session, user)`, `row_count(form, prefix)`.

Run it locally afterwards to see it: `$env:SECRET_KEY='local-dev-key'; .venv/Scripts/python -m uvicorn ptopilot.web.main:app --port 8000`, invite yourself with `profiles invite`, sign in at http://127.0.0.1:8000/login, and take the sign-in link from the server log (no emailer locally).

- [ ] **Step 1: Write the failing test file** `tests/web/conftest.py`

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

- [ ] **Step 2: Write the failing test file** `tests/web/test_auth.py`

```python
from ptopilot.links import login_token
from tests.web.conftest import KEY, invite, sign_in


def test_health_check(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/favicon.ico").status_code == 204


def test_pages_require_sign_in(client):
    for path in ("/", "/profile"):
        response = client.get(path)
        assert (response.status_code, response.headers["location"]) == (303, "/login")


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
    assert client.get("/").headers["location"] == "/login"


def test_sign_out(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/logout").headers["location"] == "/login"
    assert client.get("/").headers["location"] == "/login"


def test_token_for_a_valid_key_signs_in_directly(client):
    response = client.get(f"/auth?token={login_token(KEY, 'nick@example.com')}")
    assert response.status_code == 303
```

- [ ] **Step 3: Write the failing test file** `tests/web/test_profile_and_dashboard.py`

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
    assert "Profile saved" in dashboard.text and "15</b> days available" in dashboard.text
    assert "Azores" in dashboard.text and "No prices yet" in dashboard.text


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
    assert "$603" in page and "Good deal" in page and "See flights" in page
    assert client.post(f"/trackers/{tracker_id}/snooze", data={"days": "30"}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).snoozed_until == TODAY + timedelta(days=30)
    assert "snoozed to" in client.get("/").text
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

- [ ] **Step 4: Write the failing test file** `tests/web/test_snooze_links.py`

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ptopilot.db.models import Tracker, TrackerExclusion
from ptopilot.db.session import session_scope
from ptopilot.links import Action, action_token
from tests.digest.conftest import add_tracker, add_user
from tests.web.conftest import KEY

TRIP = (date(2027, 3, 5), date(2027, 3, 14))


def tracker(engine) -> int:
    return add_tracker(engine, add_user(engine))


def test_opening_a_link_only_shows_a_confirmation(client, clean_engine):
    tid = tracker(clean_engine)
    token = action_token(KEY, Action(tid, "snooze30"))
    page = client.get(f"/s/{token}")
    assert page.status_code == 200 and "Azores: Snooze 30 days?" in page.text and "Confirm" in page.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).snoozed_until is None  # a mail scanner's GET changes nothing


def test_confirming_applies_the_action_without_signing_in(client, clean_engine):
    tid = tracker(clean_engine)
    token = action_token(KEY, Action(tid, "trip", *TRIP))
    done = client.post(f"/s/{token}")
    assert done.status_code == 200 and "Mar 5 → Mar 14 won&#39;t be suggested again" in done.text
    with session_scope(clean_engine) as s:
        rows = list(s.scalars(select(TrackerExclusion)))
        assert [(r.tracker_id, r.depart_date, r.return_date) for r in rows] == [(tid, *TRIP)]


def test_only_if_under_asks_for_a_price(client, clean_engine):
    tid = tracker(clean_engine)
    token = action_token(KEY, Action(tid, "under", *TRIP))
    assert 'name="price"' in client.get(f"/s/{token}").text
    bad = client.post(f"/s/{token}", data={"price": "cheap"})
    assert bad.status_code == 400 and "above zero" in bad.text
    ok = client.post(f"/s/{token}", data={"price": "$1,200"})
    assert ok.status_code == 200 and "$1,200" in ok.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).max_price == Decimal("1200")


def test_tampered_or_stale_links_are_refused(client, clean_engine):
    tid = tracker(clean_engine)
    forged = action_token("wrong-key", Action(tid, "snooze30"))
    assert client.get(f"/s/{forged}").status_code == 400
    assert client.post(f"/s/{forged}").status_code == 400
    gone = action_token(KEY, Action(9999, "snooze30"))
    response = client.get(f"/s/{gone}")
    assert response.status_code == 400 and "no longer exists" in response.text
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/web -q`
Expected: conftest import ERROR: `ModuleNotFoundError: No module named 'ptopilot.web'`.

- [ ] **Step 6: Create the empty file** `ptopilot/web/__init__.py`

- [ ] **Step 7: Write** `ptopilot/web/forms.py`

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
    for key in INT_FIELDS:
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
        }
        windows, trackers = [], []
    else:
        form = {key: str(getattr(user, key)) for key in INT_FIELDS} | {
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

- [ ] **Step 8: Write** `ptopilot/web/app.py`

```python
"""The web app (spec §9): sign-in by emailed link, profile, dashboard, and the digest's snooze links.

Server-rendered Jinja pages and plain HTML forms (POST, then redirect). The session cookie is signed
with SECRET_KEY and SameSite=Lax, which is what keeps other sites from submitting these forms.
Snooze links open a confirmation page and act only on POST: mail scanners pre-fetch links (GET), and
a GET that changed state would snooze trackers nobody clicked.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from starlette.middleware.sessions import SessionMiddleware

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Invite, Tracker, User
from ptopilot.db.session import make_engine, session_scope
from ptopilot.digest.render import day, money
from ptopilot.digest.select import TrackerRow, build_digests
from ptopilot.links import ACTION_LABELS, TokenError, login_token, read_action_token, read_login_token
from ptopilot.notify.email import Emailer, EmailError, ResendEmailer
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.trackers import apply_action, snooze, unsnooze
from ptopilot.web.forms import form_to_profile, profile_to_form, row_count

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters.update(money=money, day=day)
SESSION_MAX_AGE_S = 30 * 24 * 3600


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    emailer: Emailer | None = None,
    geo: Geo | None = None,
    seasons: SeasonTable | None = None,
    today: Callable[[], date] | None = None,
) -> FastAPI:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY is required to run the web app")
    engine = engine or make_engine(settings.database_url)
    geo = geo or load_geo()
    seasons = seasons or load_seasons()
    today = today or (lambda: datetime.now(UTC).date())
    if emailer is None and settings.resend_api_key:
        emailer = ResendEmailer(settings.resend_api_key, settings.email_from)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
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

    def signed_in_user(s, request: Request) -> User | None:
        email = request.session.get("email")
        return s.scalar(select(User).where(User.email == email)) if email else None

    def owned_tracker(s, request: Request, tracker_id: int) -> Tracker | None:
        user = signed_in_user(s, request)
        tracker = s.get(Tracker, tracker_id)
        return tracker if user and tracker and tracker.user_id == user.id else None

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

    @app.post("/login")
    def login(request: Request, email: str = Form("")):
        email = email.strip().lower()
        with session_scope(engine) as s:
            invited = s.scalar(select(Invite.email).where(Invite.email == email)) if email else None
        if invited:
            base = settings.app_base_url or str(request.base_url).rstrip("/")
            link = f"{base}/auth?token={login_token(settings.secret_key, email)}"
            if emailer is None:
                log.warning("no emailer configured; sign-in link for an invited user: %s", link)
            else:
                try:
                    emailer.send(
                        email,
                        "Your ptopilot sign-in link",
                        f'<p><a href="{link}">Sign in to ptopilot</a>. The link works for 15 minutes.</p>',
                        f"Sign in to ptopilot (link works for 15 minutes): {link}",
                    )
                except EmailError as exc:
                    log.error("sign-in email not sent: %s", exc)
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
        if not request.session.get("email"):
            return redirect("/login")
        with session_scope(engine) as s:
            user = signed_in_user(s, request)
            if user is None:
                return redirect("/profile")
            user_id, pto_total, pto_committed = user.id, user.pto_days_total, user.pto_committed
        digests = build_digests(engine, geo, seasons, today(), "none", user_id=user_id)
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
            deals=(digest.deals[:5] if digest else []),
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
        if not request.session.get("email"):
            return redirect("/login")
        with session_scope(engine) as s:
            form = profile_to_form(s, signed_in_user(s, request))
        return profile_page(request, form, [])

    @app.post("/profile")
    async def save_profile(request: Request):
        email = request.session.get("email")
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

- [ ] **Step 9: Write** `ptopilot/web/main.py`

```python
"""ASGI entry point for the server: `uvicorn ptopilot.web.main:app`. Reads settings from the environment."""

from ptopilot.settings import Settings
from ptopilot.web.app import create_app

app = create_app(Settings.from_env())
```

- [ ] **Step 10: Write** `ptopilot/web/templates/base.html`

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}ptopilot{% endblock %}</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#111827; --muted:#6b7280; --line:#e5e7eb; --accent:#111827; --ok:#15803d; --bad:#b91c1c; --soft:#f3f4f6; }
  @media (prefers-color-scheme: dark) { :root { --bg:#0f1115; --card:#171a21; --ink:#e5e7eb; --muted:#9ca3af; --line:#2a2f3a; --accent:#e5e7eb; --ok:#4ade80; --bad:#f87171; --soft:#1f2430; } }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
  header { display:flex; align-items:center; justify-content:space-between; gap:12px; max-width:760px; margin:0 auto; padding:16px; }
  header a.brand { font-weight:700; color:var(--ink); text-decoration:none; letter-spacing:.02em; }
  nav { display:flex; gap:14px; align-items:center; font-size:14px; }
  nav a { color:var(--muted); text-decoration:none; }
  main { max-width:760px; margin:0 auto; padding:0 16px 48px; }
  h1 { font-size:22px; margin:8px 0 12px; } h2 { font-size:16px; margin:24px 0 8px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin:0 0 12px; }
  .muted { color:var(--muted); } .small { font-size:13px; }
  .ok { color:var(--ok); } .error { color:var(--bad); }
  .price { font-size:22px; font-weight:700; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:8px 6px; border-top:1px solid var(--line); vertical-align:middle; }
  th { color:var(--muted); font-weight:500; border-top:none; }
  .scroll { overflow-x:auto; }
  label { display:block; font-size:13px; color:var(--muted); margin:10px 0 4px; }
  input, select { width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--ink); font:inherit; }
  input[type=checkbox] { width:auto; margin-right:6px; }
  .check { display:flex; align-items:center; color:var(--ink); font-size:14px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:0 12px; }
  .row { display:grid; grid-template-columns:2fr 1fr 1fr 1fr 1fr; gap:8px; align-items:end; }
  @media (max-width:560px) { .row { grid-template-columns:1fr 1fr; } .row > div:first-child { grid-column:1 / -1; } }
  button, .button { display:inline-block; padding:9px 14px; border-radius:8px; border:1px solid var(--accent); background:var(--accent); color:var(--bg); font:inherit; font-weight:600; cursor:pointer; text-decoration:none; }
  button.link { background:none; border:none; color:var(--muted); padding:0; font-weight:400; text-decoration:underline; }
  form.inline { display:inline; }
  .bar { height:10px; border-radius:999px; background:var(--soft); overflow:hidden; } .bar > span { display:block; height:100%; background:var(--accent); }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; background:var(--soft); font-size:12px; }
</style>
</head>
<body>
<header>
  <a class="brand" href="/">ptopilot</a>
  {% if signed_in %}
  <nav>
    <a href="/">Dashboard</a>
    <a href="/profile">Profile</a>
    <form class="inline" method="post" action="/logout"><button class="link" type="submit">Sign out</button></form>
  </nav>
  {% endif %}
</header>
<main>
{% block content %}{% endblock %}
</main>
</body>
</html>
```

- [ ] **Step 11: Write** `ptopilot/web/templates/login.html`

```html
{% extends "base.html" %}
{% block title %}Sign in · ptopilot{% endblock %}
{% block content %}
<h1>Sign in</h1>
<div class="card">
  <p class="muted">ptopilot is invite-only. Enter your email and we'll send you a sign-in link.</p>
  <form method="post" action="/login">
    <label for="email">Email</label>
    <input id="email" name="email" type="email" autocomplete="email" required>
    <p><button type="submit">Email me a link</button></p>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 12: Write** `ptopilot/web/templates/login_sent.html`

```html
{% extends "base.html" %}
{% block title %}Check your email · ptopilot{% endblock %}
{% block content %}
<h1>Check your email</h1>
<div class="card">
  <p>If that address is invited, a sign-in link is on its way. It works for 15 minutes.</p>
  <p class="muted small">Not there? Check spam, or <a href="/login">try again</a>.</p>
</div>
{% endblock %}
```

- [ ] **Step 13: Write** `ptopilot/web/templates/message.html`

```html
{% extends "base.html" %}
{% block title %}{{ title }} · ptopilot{% endblock %}
{% block content %}
<h1>{{ title }}</h1>
<div class="card">
  <p>{{ message }}</p>
  {% if login %}<p><a class="button" href="/login">Get a new link</a></p>{% endif %}
  {% if signed_in %}<p><a href="/">Back to your dashboard</a></p>{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 14: Write** `ptopilot/web/templates/action_confirm.html`

```html
{% extends "base.html" %}
{% block title %}{{ label }} · ptopilot{% endblock %}
{% block content %}
<h1>{{ destination }}: {{ label | replace("…", "a price") }}?</h1>
<div class="card">
  {% if action.kind == "trip" %}
  <p>Stop suggesting <b>{{ action.depart | day }} → {{ action.ret | day }}</b> for {{ destination }}. Other dates keep being tracked.</p>
  {% elif action.kind == "snooze30" %}
  <p>Pause all {{ destination }} alerts for 30 days. Prices keep being collected in the background.</p>
  {% elif action.kind == "year" %}
  <p>Pause {{ destination }} alerts until the end of {{ action.depart.year if action.depart else "this year" }}.</p>
  {% else %}
  <p>Only tell me about {{ destination }} trips under this price (round trip, per person):</p>
  {% endif %}
  <form method="post">
    {% if action.kind == "under" %}
    <label for="price">Maximum price (USD)</label>
    <input id="price" name="price" inputmode="numeric" placeholder="e.g. 750" required>
    {% endif %}
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p><button type="submit">Confirm</button></p>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 15: Write** `ptopilot/web/templates/dashboard.html`

```html
{% extends "base.html" %}
{% block title %}Dashboard · ptopilot{% endblock %}
{% block content %}
{% if saved %}<p class="ok">Profile saved. The next morning scan will use it.</p>{% endif %}
<h1>Your trips</h1>

<div class="card">
  <div class="small muted">PTO for the year</div>
  <div style="display:flex;justify-content:space-between;margin:4px 0 8px;">
    <span><b>{{ pto_total - pto_committed }}</b> days available</span>
    <span class="muted">{{ pto_committed }} of {{ pto_total }} committed</span>
  </div>
  <div class="bar"><span style="width:{{ (100 * pto_committed / pto_total) | round | int if pto_total else 0 }}%"></span></div>
</div>

<h2>Trackers</h2>
<div class="card scroll">
  {% if trackers %}
  <table>
    <tr><th>Destination</th><th>Best now</th><th>Typical</th><th>Next good</th><th></th></tr>
    {% for t in trackers %}
    <tr>
      <td>{{ t.destination }}{% if t.snoozed_until %}<br><span class="pill">snoozed to {{ t.snoozed_until | day }}</span>{% endif %}</td>
      <td>{{ t.best_price | money }}</td>
      <td>{{ t.typical | money }}</td>
      <td>{{ t.next_good_month or "—" }}</td>
      <td style="text-align:right;white-space:nowrap;">
        {% if t.snoozed_until %}
        <form class="inline" method="post" action="/trackers/{{ t.tracker_id }}/unsnooze"><button class="link">Resume</button></form>
        {% else %}
        <form class="inline" method="post" action="/trackers/{{ t.tracker_id }}/snooze"><input type="hidden" name="days" value="30"><button class="link">Snooze 30d</button></form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="muted">No trackers yet. <a href="/profile">Add destinations to your profile.</a></p>
  {% endif %}
</div>

<h2>Best options right now</h2>
{% for d in deals %}
<div class="card">
  <div style="display:flex;justify-content:space-between;gap:8px;">
    <b>{{ d.destination }}</b>
    <span class="pill">{{ {"great": "Great deal", "good": "Good deal"}.get(d.deal_level, "Tracking") }} · go-now {{ d.go_now }}</span>
  </div>
  <div class="small muted">{{ d.depart_date | day }} → {{ d.return_date | day }} · {{ d.origin }} → {{ d.dest_airport }}{% if d.open_jaw %}, home from {{ d.return_airport }}{% endif %} · {{ d.pto_cost }} PTO days</div>
  <div style="margin-top:6px;"><span class="price">{{ d.price | money(d.currency) }}</span>
    <span class="muted small">{% if d.typical %}typically ~{{ d.typical | money(d.currency) }}{% endif %}</span></div>
  {% if d.deep_link %}<p style="margin:8px 0 0;"><a href="{{ d.deep_link }}">See flights →</a></p>{% endif %}
</div>
{% else %}
<div class="card"><p class="muted">No prices yet. The daily scan runs at 06:00 UTC; check back tomorrow.</p></div>
{% endfor %}
{% endblock %}
```

- [ ] **Step 16: Write** `ptopilot/web/templates/profile.html`

```html
{% extends "base.html" %}
{% block title %}Profile · ptopilot{% endblock %}
{% block content %}
<h1>Your travel profile</h1>
{% if errors %}
<div class="card">
  <p class="error"><b>Please fix {{ errors | length }} thing{{ "s" if errors | length != 1 }}:</b></p>
  <ul class="error">{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
</div>
{% endif %}
<form method="post" action="/profile">
  <div class="card">
    <h2 style="margin-top:0;">Home and calendar</h2>
    <div class="grid">
      <div><label for="home_airport">Home airport</label><input id="home_airport" name="home_airport" value="{{ form.home_airport }}" placeholder="JFK" required></div>
      <div><label for="nearby_airports">Also fly from</label><input id="nearby_airports" name="nearby_airports" value="{{ form.nearby_airports }}" placeholder="EWR, PHL"></div>
      <div><label for="country">Country</label><input id="country" name="country" value="{{ form.country }}" maxlength="2"></div>
      <div><label for="holiday_calendar">Holiday calendar</label><input id="holiday_calendar" name="holiday_calendar" value="{{ form.holiday_calendar }}" placeholder="US or GB-ENG"></div>
    </div>
    <label for="ignored_holidays">Holidays your office works (comma-separated)</label>
    <input id="ignored_holidays" name="ignored_holidays" value="{{ form.ignored_holidays }}" placeholder="Columbus Day, Veterans Day">
    <label for="extra_days_off">Company days off (YYYY-MM-DD, comma-separated)</label>
    <input id="extra_days_off" name="extra_days_off" value="{{ form.extra_days_off }}">
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Time off</h2>
    <div class="grid">
      <div><label for="pto_days_total">PTO days this year</label><input id="pto_days_total" name="pto_days_total" value="{{ form.pto_days_total }}" inputmode="numeric" required></div>
      <div><label for="pto_committed">Already committed</label><input id="pto_committed" name="pto_committed" value="{{ form.pto_committed }}" inputmode="numeric"></div>
      <div><label for="min_trip_days">Shortest trip (days away)</label><input id="min_trip_days" name="min_trip_days" value="{{ form.min_trip_days }}" inputmode="numeric"></div>
      <div><label for="max_trip_days">Longest trip (days away)</label><input id="max_trip_days" name="max_trip_days" value="{{ form.max_trip_days }}" inputmode="numeric" required></div>
    </div>
    <h2>Travel windows</h2>
    {% for i in range(windows) %}
    <div class="grid">
      <div><label for="window_start_{{ i }}">From</label><input id="window_start_{{ i }}" type="date" name="window_start_{{ i }}" value="{{ form['window_start_%d' % i] }}"></div>
      <div><label for="window_end_{{ i }}">To</label><input id="window_end_{{ i }}" type="date" name="window_end_{{ i }}" value="{{ form['window_end_%d' % i] }}"></div>
    </div>
    {% endfor %}
    <p class="muted small">Leave a row blank to remove it.</p>
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Bucket list</h2>
    <p class="muted small">Days on the ground, after travel days. Priority 1 is checked first.</p>
    {% for i in range(trackers) %}
    <div class="row">
      <div><label for="tracker_dest_{{ i }}">Destination</label>
        <select id="tracker_dest_{{ i }}" name="tracker_dest_{{ i }}">
          <option value=""></option>
          {% for d in destinations %}<option value="{{ d.code }}" {{ "selected" if form['tracker_dest_%d' % i] == d.code }}>{{ d.name }}</option>{% endfor %}
        </select></div>
      <div><label for="tracker_min_{{ i }}">Min days</label><input id="tracker_min_{{ i }}" name="tracker_min_{{ i }}" value="{{ form['tracker_min_%d' % i] }}" inputmode="numeric"></div>
      <div><label for="tracker_max_{{ i }}">Max days</label><input id="tracker_max_{{ i }}" name="tracker_max_{{ i }}" value="{{ form['tracker_max_%d' % i] }}" inputmode="numeric"></div>
      <div><label for="tracker_priority_{{ i }}">Priority</label><input id="tracker_priority_{{ i }}" name="tracker_priority_{{ i }}" value="{{ form['tracker_priority_%d' % i] }}" inputmode="numeric"></div>
      <div><label for="tracker_price_{{ i }}">Max price</label><input id="tracker_price_{{ i }}" name="tracker_price_{{ i }}" value="{{ form['tracker_price_%d' % i] }}" inputmode="numeric" placeholder="any"></div>
    </div>
    {% endfor %}
    <p class="muted small">Missing a destination? It has to be added to the app's data first.</p>
  </div>

  <div class="card">
    <h2 style="margin-top:0;">Preferences</h2>
    <div class="grid">
      <div><label for="weather_tolerance">Weather</label>
        <select id="weather_tolerance" name="weather_tolerance">
          {% for value, text in [("strict", "Only the best months"), ("normal", "Skip bad-weather months"), ("relaxed", "Any month")] %}
          <option value="{{ value }}" {{ "selected" if form.weather_tolerance == value }}>{{ text }}</option>
          {% endfor %}
        </select></div>
      <div><label for="max_stops_short">Max stops (short haul)</label><input id="max_stops_short" name="max_stops_short" value="{{ form.max_stops_short }}" inputmode="numeric"></div>
      <div><label for="max_stops_long">Max stops (long haul)</label><input id="max_stops_long" name="max_stops_long" value="{{ form.max_stops_long }}" inputmode="numeric"></div>
      <div><label for="friday_evening_min_time">Leave-after-work time</label><input id="friday_evening_min_time" type="time" name="friday_evening_min_time" value="{{ form.friday_evening_min_time }}"></div>
    </div>
    <label class="check"><input type="checkbox" name="allow_overnight_layover" {{ "checked" if form.allow_overnight_layover }}> Overnight layovers are OK</label>
    <label class="check"><input type="checkbox" name="friday_evening_departure" {{ "checked" if form.friday_evening_departure }}> I can leave after work on my last workday</label>
  </div>

  <p><button type="submit">Save profile</button></p>
</form>
{% endblock %}
```

- [ ] **Step 17: Write** `render.yaml`

```yaml
# Render Blueprint: Dashboard -> New -> Blueprint -> pick this repo. Free web service; sleeps when idle.
services:
  - type: web
    name: ptopilot
    runtime: python
    plan: free
    region: virginia
    buildCommand: pip install -e .
    startCommand: uvicorn ptopilot.web.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'
    healthCheckPath: /healthz
    autoDeploy: true
    envVars:
      - key: PYTHON_VERSION
        value: "3.12.7"
      - key: DATABASE_URL       # Neon pooled URL (DATABASE_URL in .env.local)
        sync: false
      - key: SECRET_KEY         # the same value as the GitHub secret SECRET_KEY
        sync: false
      - key: RESEND_API_KEY
        sync: false
      - key: EMAIL_FROM
        sync: false
      - key: APP_BASE_URL       # this service's own URL, e.g. https://ptopilot.onrender.com
        sync: false
```

- [ ] **Step 18: Write** `README.md`

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

## Digest

```powershell
.venv/Scripts/python -m ptopilot.digest send --preview out/                 # write each digest to out/*.html + .txt
.venv/Scripts/python -m ptopilot.digest send --preview out/ --min-level none # include trips that aren't deals yet (tuning)
.venv/Scripts/python -m ptopilot.digest send                                 # email them (needs RESEND_API_KEY)
```

`.github/workflows/digest.yml` sends on Mondays and Thursdays at 12:00 UTC, after the morning scan. A digest with no deals ("quiet week") only goes out on Mondays. Run it by hand from the Actions tab with `min_level: none` to get a tuning email built from every priced trip. Tuning emails go only to `ADMIN_EMAIL` and never count as "already sent". Without a verified sending domain, Resend only delivers to the Resend account's own address; a send to anyone else fails, is logged, and the run exits red while the other digests still go out.

## Web app

```powershell
$env:SECRET_KEY = "local-dev-key"
.venv/Scripts/python -m uvicorn ptopilot.web.main:app --reload --port 8000   # http://127.0.0.1:8000
.venv/Scripts/python -m ptopilot.profiles invite you@example.com            # only invited emails can sign in
```

Sign-in is by emailed link (valid 15 minutes). Without `RESEND_API_KEY` the server logs the link instead, which is handy locally. Signed-in travelers get a dashboard (trackers, best current prices, snooze), and a profile page that validates exactly like `profiles load`. With `APP_BASE_URL` and `SECRET_KEY` set, digests get snooze buttons that open a confirmation page in the app. They only act when you press Confirm, because mail scanners pre-open links.

### Deploying (Render, free tier)

1. Render dashboard → **New → Blueprint** → connect this GitHub repo. `render.yaml` defines the service.
2. Fill in the environment variables it asks for: `DATABASE_URL` (Neon **pooled** URL), `SECRET_KEY` (the same value as the GitHub secret), `RESEND_API_KEY`, `EMAIL_FROM` (optional), `APP_BASE_URL` (the service's own `https://….onrender.com` URL).
3. Set the GitHub variable `APP_BASE_URL` to the same URL so the digest links to it: `gh variable set APP_BASE_URL`.

The free service sleeps after ~15 idle minutes; the first request after that takes ~30–60 s.

## Configuration

Environment variables (never committed; GitHub Actions secrets in production):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (Neon in production); defaults to the local dev database |
| `TRAVELPAYOUTS_TOKEN` | Cached fares for the broad scan; without it `broad_scan` is skipped |
| `SERPAPI_KEY` | Live-check fallback (~8 searches/run, 250/month) |
| `RESEND_API_KEY`, `ADMIN_EMAIL` | Health email after each scan |
| `EMAIL_FROM` | Sender; defaults to Resend's shared `onboarding@resend.dev`, which only delivers to your own Resend account address |
| `SECRET_KEY` | Signs sign-in links, sessions and snooze links; must be identical for the web app and the digest job |
| `APP_BASE_URL` | Public URL of the web app; turns on snooze buttons in the digest (a GitHub *variable* for the workflow) |
````

- [ ] **Step 19: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/web -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **321 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 20: Commit and push**

```bash
git add ptopilot/web render.yaml README.md tests/web/conftest.py tests/web/test_auth.py tests/web/test_profile_and_dashboard.py tests/web/test_snooze_links.py
git commit -m "feat(web): sign-in, profile, dashboard, snooze links; Render blueprint" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Then: `& "C:\Program Files\GitHub CLI\gh.exe" run watch --exit-status` on the `ci` run → green.

---

### Task 4: Deploy and connect (needs the user for the Render steps)

- [ ] **Step 1: Create the shared secret without ever displaying it.** With Python's `secrets.token_urlsafe(48)`, generate one value. Pipe it straight into `& "C:\Program Files\GitHub CLI\gh.exe" secret set SECRET_KEY --repo nick-dahl/ptopilot`, and append `SECRET_KEY=<value>` to the git-ignored `.env.keys` so the user can paste it into Render. Confirm with `git check-ignore -v .env.keys` and `& "C:\Program Files\GitHub CLI\gh.exe" secret list`. The value must never appear in output.
- [ ] **Step 2: Hand over to the user for Render.** Ask them to:
  - go to Render → **New → Blueprint** → connect `nick-dahl/ptopilot` (`render.yaml` defines everything)
  - fill in `DATABASE_URL` (the **pooled** `DATABASE_URL` from `.env.local`), `SECRET_KEY` (from `.env.keys`), `RESEND_API_KEY` (from `.env.keys`), leave `EMAIL_FROM` blank, and set `APP_BASE_URL` to the service URL Render shows (e.g. `https://ptopilot.onrender.com`)
  - send the URL back once the deploy shows *Live*

  Wait for their reply.
- [ ] **Step 3: Check the deployment:** `curl -s <URL>/healthz` → `{"ok":true}`. The first call may take up to a minute (cold start).
- [ ] **Step 4: Point the digest at it:** `& "C:\Program Files\GitHub CLI\gh.exe" variable set APP_BASE_URL --body <URL> --repo nick-dahl/ptopilot`.
- [ ] **Step 5: Confirm the user is invited** (the profile loader added the invite). Run `python -m ptopilot.profiles invite <their email>` against Neon, with `DATABASE_URL` from `.env.local`'s `DATABASE_URL_UNPOOLED`. It's idempotent. Then ask the user to sign in at `<URL>/login` and say whether the email arrived, the dashboard shows their 4 trackers and prices, and the profile page is pre-filled.
- [ ] **Step 6: Snooze buttons end to end:** `& "C:\Program Files\GitHub CLI\gh.exe" workflow run digest.yml -f min_level=none`, then watch it go green. Ask the user to open one *Snooze 30 days* link and check that it shows a confirmation page without acting. They decide whether to confirm.
- [ ] **Step 7:** Record the URL, the run IDs and the user's confirmations in the ledger.

### Final check

- [ ] `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q` → **321 passed, 1 deselected**. `git status` clean. Nothing unpushed. Latest `ci` and `digest` runs green. `/healthz` on Render OK.

## After this plan

- **Before inviting friends:** verify a sending domain in Resend (DNS records at a registrar), set `EMAIL_FROM` to an address on it in both Render and GitHub secrets, then `profiles invite friend@…`. Until then, sign-in and digest emails reach only the Resend account owner.
- Everything in `ROADMAP.md` (V2: year-plan view, buy-now-or-wait advice, related destinations, …).
