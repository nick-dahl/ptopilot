# ptopilot Plan 8: Better Price Data (history seeding, full daily coverage, Google crash fix, source audit)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get confident baselines, and therefore deals, within days instead of weeks, check every in-range route daily, stop one unparseable Google route from disabling Google for the whole run, and measure how often fast-flights misses cheaper fares.

**Architecture:**
- **Seeding.** SerpApi round-trip results already carry ~61 days of Google's own daily prices. A new `seed_history` stage (after `shortlist`, before `live_verify`) spends up to 6 SerpApi calls a day, one per not-yet-confident baseline key. Each call stores the history as unverified `google_history` observations dated on their own days, which the existing `baselines` stage uses unchanged.
- **No-itinerary pages.** `google_flights` reads Google's results script itself so a page with no itineraries becomes "no flights". Other parse errors are flagged `route_specific` and never trip the breaker.
- **Coverage.** The daily check cap rises to 150.
- **Audit.** The health email compares fast-flights with SerpApi on trips both priced the same day.

**Tech Stack:** No new dependencies. Uses fast-flights' own `fetch_flights_html`/`parse_js` and selectolax, which fast-flights already depends on.

**Spec:** [`docs/superpowers/specs/2026-10-18-ptopilot-v2-price-data-design.md`](../specs/2026-10-18-ptopilot-v2-price-data-design.md)

## Global Constraints

- **No paid services.** SerpApi stays within `SOURCE_BUDGETS["serpapi"]` (8/day, 250/month). Every attempted SerpApi call, seeding included, is charged through `Budget` and recorded in `live_checks`.
- **Seeding leaves `SEED_RESERVE_FOR_OPEN_JAW = 2` SerpApi calls a day** for open-jaw routes, which only SerpApi can price.
- **History never becomes a user-facing price:** `google_history` observations are unverified and excluded from `cached_prices`. Only live (verified) options become candidates.
- **No schema change.**
- **Route-specific source failures never count toward, or reset, a source's circuit breaker.** Outages still trip it after `BREAKER_THRESHOLD` (3).
- `LIVE_CHECK_CAP = 150`; `scan.yml` `timeout-minutes: 75`; pacing `LIVE_DELAY_S` unchanged.
- Default `pytest` never touches the network. Run database tests with `PTOPILOT_REQUIRE_DB=1`. `ruff check .` and `ruff format --check .` must pass.
- **Work directly on `main`; every task ends with a commit and a `git push`, with the full suite green.** Every commit message ends with a `Co-Authored-By:` line for the model that wrote it.
- Never print, commit or log secrets: `.env.local`, `.env.keys` and `profiles/nick.yaml` stay git-ignored and unread on screen.
- Commands run from `C:\Users\nickd\dev\ptopilot` with `.venv/Scripts/python`. The local Postgres must be running on port 5433.

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **SerpApi returns no history for a key** (Google has none, or the payload changes shape) → the call still counts, the key is "tried" and isn't retried for 30 days, and its live options are still stored. *Task 4: `test_a_same_day_rerun_makes_no_new_calls`, `test_a_key_tried_without_history_is_retried_after_30_days`; Task 1: `test_malformed_points_are_skipped`, `test_missing_history_is_empty`.*
2. **History points older than the baseline window or after the run date** → dropped, so they can't skew a baseline. *Task 4: `test_points_outside_the_baseline_window_are_dropped`.*
3. **A scan re-run on the same day** → no second SerpApi call per key, and the budget is still respected across stages. *Task 4: `test_a_same_day_rerun_makes_no_new_calls`, `test_seeding_keeps_two_calls_a_day_for_open_jaw`.*
4. **An outage mixed with route-specific failures** → the breaker trips on three outages in a row, whatever route failures sit in between. *Task 3: `test_route_failures_neither_count_toward_nor_reset_the_breaker`.*
5. **History rows leaking into the user-facing price path** (the cached estimate, the score fallback) → never. *Task 4: `test_history_never_becomes_a_cached_price`.*

## Verified before writing (2026-10-18)

- **Probes against the real services, all read-only except one Google search pair:**
  - Travelpayouts "to anywhere" for NYC/JFK/EWR/PHL in Dec 2026, Mar 2027 and Oct 2027 returned none of the traveler's destinations.
  - The recorded SerpApi response has 61 history points.
  - Neon stats: 30 baselines, all low-confidence (n ≤ 4); about 28 routes unchecked per day; 8 of 9 PHL→PUQ Google checks failed.
  - A live fast-flights capture of PHL→PUQ shows Google's results slot is `null`, so the route has no itineraries. JFK→PUQ, same dates, has results.
  - After Task 2's change, a live run returned PHL→PUQ 0 options and JFK→PUQ 4 options.
- **Built test-first in a scratch worktree** (branch `v2-data-scratch`, never pushed), one commit per task. Key rules were mutation-checked: removing the history exclusion from `cached_prices`, removing the open-jaw reserve, or shifting the 30-day retry by a day each makes a Task 4 test fail.
- **Replayed on a fresh copy of `main`** by `sim_plan8.py`: test files first (watched fail), then the rest, then the full suite and ruff. The "Verified tail" lines below come from that replay, and the final tree matched the verified branch byte for byte (20 files).
- Verified files: `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\wt8`.

## File structure

```
ptopilot/config.py                      # HISTORY_SOURCE, SEED_RESERVE_FOR_OPEN_JAW, SEED_RETRY_DAYS,
                                        # AUDIT_EQUAL_USD, AUDIT_DAYS; LIVE_CHECK_CAP 150
ptopilot/sources/base.py                # ExactResult.price_history; SourceUnavailable.route_specific
ptopilot/sources/serpapi.py             # parse_price_history; provides_history
ptopilot/sources/google_flights.py      # flights_from_script (no-itinerary pages); route-specific errors
ptopilot/pipeline/live_verify.py        # store_options / store_history / record_check; route failures
ptopilot/pipeline/seed_history.py       # NEW stage
ptopilot/pipeline/queries.py            # cached_prices ignores google_history
ptopilot/pipeline/runner.py             # stage order + CONTINUE_ON_FAILURE
ptopilot/pipeline/health.py             # audit_lines in the health email
.github/workflows/scan.yml              # timeout-minutes 75
tests/sources/fixtures/real_google_page_{PHL,JFK}_PUQ_2027-03-05_2027-03-14.js   # NEW recordings
ROADMAP.md
```

## Pre-flight: shared interfaces

| Producer → consumer | Interface | Checked |
|---|---|---|
| 1 → 4 | `ExactResult.price_history` | same name |
| 2 → 3, 4 | `SourceUnavailable(..., route_specific=)` / `.route_specific` | same |
| 3 → 4 | `store_options`, `record_check` (public) | same |
| 4 → 6 | none (audit reads `price_observations` by source) | — |
| 5 | config + workflow only | — |

### Task 1: Keep SerpApi's Google price history

SerpApi round-trip results include `price_insights.price_history`, about 61 daily `[unix_ts, price]` points for the searched dates. Parse them into `ExactResult.price_history` instead of discarding them.

**Files:**
- Modify: `ptopilot/sources/base.py`
- Modify: `ptopilot/sources/serpapi.py`
- Create: `tests/sources/test_serpapi_history.py`

**Interfaces:**
- Consumes: `ExactResult`, `serpapi.parse_google_flights` (existing).
- Produces: `ExactResult.price_history: tuple[tuple[date, float], ...] = ()`; `ptopilot.sources.serpapi.parse_price_history(insights) -> tuple[tuple[date, float], ...]`.

- [ ] **Step 1: Write the failing test file `tests/sources/test_serpapi_history.py`**

```python
"""SerpApi round-trip results carry Google's own daily price history for the searched dates."""

import json
from datetime import date
from pathlib import Path

from ptopilot.sources.base import ExactQuery
from ptopilot.sources.serpapi import parse_google_flights, parse_price_history

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


REAL = load("real_serpapi_ORD_LIS_2027-06-12_2027-06-20.json")
MULTI = load("real_serpapi_multicity_JFK-OPO_SCQ-JFK_2027-03.json")
QUERY = ExactQuery("ORD", "LIS", date(2027, 6, 12), date(2027, 6, 20))


def test_real_response_carries_61_days_of_history():
    history = parse_google_flights(REAL, QUERY).price_history
    assert len(history) == 61
    assert [d for d, _ in history] == sorted(d for d, _ in history)
    assert history[-1] == (date(2026, 10, 16), 1098.0)


def test_history_points_are_utc_dates():
    assert parse_price_history({"price_history": [[1792126800, 1098]]}) == ((date(2026, 10, 16), 1098.0),)


def test_malformed_points_are_skipped():
    insights = {"price_history": [[1792126800, 1098], ["x", 5], [1792126800], None, [1792213200, "n/a"]]}
    assert parse_price_history(insights) == ((date(2026, 10, 16), 1098.0),)


def test_missing_history_is_empty():
    assert parse_price_history(None) == ()
    assert parse_price_history({}) == ()
    assert parse_price_history({"price_history": "nope"}) == ()


def test_multi_city_results_have_no_history():
    query = ExactQuery("JFK", "OPO", date(2027, 3, 5), date(2027, 3, 19), return_from="SCQ")
    assert parse_google_flights(MULTI, query).price_history == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/sources/test_serpapi_history.py`

Expected: FAIL. Verified tail: `1 error in 0.29s`

- [ ] **Step 3: Write `ptopilot/sources/base.py` (full new contents)**

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
    # Google's daily price history for these exact dates, (day, price), when the source has it (SerpApi)
    price_history: tuple[tuple[date, float], ...] = ()

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

- [ ] **Step 4: Write `ptopilot/sources/serpapi.py` (full new contents)**

```python
"""SerpApi Google Flights: quota-limited fallback that also returns Google's typical price range."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

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


def parse_price_history(insights: object) -> tuple[tuple[date, float], ...]:
    """price_insights.price_history, [[unix_ts, price], ...] -> ((UTC day, price), ...). Skips bad points."""
    raw = insights.get("price_history") if isinstance(insights, dict) else None
    if not isinstance(raw, list):
        return ()
    points = []
    for point in raw:
        if not (isinstance(point, list) and len(point) == 2):
            continue
        ts, price = point
        if isinstance(ts, bool) or isinstance(price, bool):
            continue
        if not (isinstance(ts, int | float) and isinstance(price, int | float)):
            continue
        points.append((datetime.fromtimestamp(ts, UTC).date(), float(price)))
    return tuple(points)


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
    insights = payload.get("price_insights") or {}
    typical = insights.get("typical_price_range")
    typical_range = (float(typical[0]), float(typical[1])) if typical and len(typical) == 2 else None
    url = (payload.get("search_metadata") or {}).get("google_flights_url", "")
    return ExactResult(
        source="serpapi",
        query=query,
        currency=query.currency,
        options=options,
        deep_link=url,
        typical_range=typical_range,
        price_history=parse_price_history(insights),
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/sources/test_serpapi_history.py`

Expected: PASS. Verified tail: `5 passed in 0.30s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `447 passed, 1 deselected, 1 warning in 67.52s (0:01:07)`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(sources): keep SerpApi's Google price history

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 2: Google pages with no itineraries; route-specific errors

For PHL→PUQ, Google returns a page with no itineraries at all (results slot `null`), and fast-flights 3.1 crashes on it with `TypeError: 'NoneType' object is not subscriptable`. That's 8 of 9 production checks. Treat that page as "no flights". Any other parse error (`TypeError`/`IndexError`/`KeyError`) becomes a `SourceUnavailable(route_specific=True)`. The fixtures are real Google results scripts captured 2026-10-18. A live run returned PHL→PUQ 0 options and JFK→PUQ 4 options (cheapest $1,238).

**Files:**
- Modify: `ptopilot/sources/base.py`
- Modify: `ptopilot/sources/google_flights.py`
- Create: `tests/sources/fixtures/real_google_page_JFK_PUQ_2027-03-05_2027-03-14.js`
- Create: `tests/sources/fixtures/real_google_page_PHL_PUQ_2027-03-05_2027-03-14.js`
- Create: `tests/sources/test_google_flights_pages.py`

**Interfaces:**
- Consumes: `SourceUnavailable`, `GoogleFlightsSource` (existing); fast-flights' `fetch_flights_html`, `parse_js`, selectolax (its dependency).
- Produces: `SourceUnavailable(message, route_specific: bool = False)` with `.route_specific`; `ptopilot.sources.google_flights.flights_from_script(js) -> list`; `ROUTE_ERRORS`.

- [ ] **Step 1: Write the failing test file `tests/sources/fixtures/real_google_page_JFK_PUQ_2027-03-05_2027-03-14.js`**

```
AF_initDataCallback({key: 'ds:1', hash: '9', data:[[null,[[1792347802679287,44789107,3390031733],null,null,null,null,[[1]]],0,"mg7Vave6KfParcUP9Y6_0Aw","HovvqKcXRMnIAAg0rwBG--------vtbeu16AAAAAGrVDpoKUdeGA"],[[[[["JFK",0],"John F. Kennedy International Airport",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]]],[40.6397222,-73.778889],"US",0,"United States"]],[[["PUQ",0],"Punta Arenas C.Ibanez del Campo",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]]],[-53.003611,-70.853611],"CL",0,"Chile"]]],[[[["PUQ",0],"Punta Arenas C.Ibanez del Campo",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]]],[-53.003611,-70.853611],"CL",0,"Chile"]],[[["JFK",0],"John F. Kennedy International Airport",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]]],[40.6397222,-73.778889],"US",0,"United States"]]]],null,[[[["LA",["LATAM"],[[null,null,"Latam Airlines Group","JFK","John F. Kennedy International Airport","Arturo Merino Benitez International Airport","SCL",null,[18,25],1,[6,55],630,[null,1,null,null,null,null,null,null,null,1],3,"32 in",null,1,"Boeing 787",[1,1],0,[2027,3,5],[2027,3,6],["LA","533",null,"LATAM"],null,null,1,null,null,null,null,"32 inches",455029,2],[null,null,"Latam Airlines Chile","SCL","Arturo Merino Benitez International Airport","Aeropuerto El Tepual","PMC",1,[11,29],1,[13,14],105,[null,null,null,null,null,1,null,null,null,null,1,3],2,"28 in",null,1,"Airbus A321",null,0,[2027,3,6],[2027,3,6],["LA","311",null,"LATAM"],null,null,1,null,null,null,null,"28 inches",93003,1],[null,null,"Latam Airlines Chile","PMC","Aeropuerto El Tepual","Punta Arenas C.Ibanez del Campo","PUQ",1,[14,10],1,[16,20],130,[null,null,null,null,null,1,null,null,null,null,1,3],2,"28 in",null,1,"Airbus A321",null,0,[2027,3,6],[2027,3,6],["LA","311",null,"LATAM"],null,null,1,null,null,null,null,"28 inches",121756,2]],"JFK",[2027,3,5],[18,25],"PUQ",[2027,3,6],[16,20],1195,1,null,0,[[274,"SCL","SCL",null,"Arturo Merino Benitez International Airport","Santiago","Arturo Merino Benitez International Airport","Santiago"],[56,"PMC","PMC",null,"Aeropuerto El Tepual","Puerto Montt","Aeropuerto El Tepual","Puerto Montt"]],null,null,null,"XrkEeb",[[1792347802679287,44789107,3390031733],null,null,null,null,[[2]]],1,null,null,[null,null,1,-10,null,1,1,670000,741000,[1],655000,2,0,null,null,2,null,4],[1],[["LA","LATAM","https://www.latamairlines.com/us/en/help-center/faq/special-needs"]]],[[null,1238],"CjRIb3Z2cUtjWFJNbklBQWcwcndCRy0tLS0tLS0tdnRiZXUxNkFBQUFBR3JWRHBvS1VkZUdBEhFMQTUzM3xMQTMxMXxMQTMxMRoLCI3HBxACGgNVU0Q4HXCNxwc\u003d"],null,1,[null,null,null,null,1,null,[null,1]],[0,0,0],0,[],"[\"CAISA1VTRBoECI3HByKnAgqRAgpZCgNKRksSGTIwMjctMDMtMDVUMTg6MjU6MDAtMDU6MDAaA1NDTCIZMjAyNy0wMy0wNlQwNjo1NTowMC0wMzowMCoCTEEyAzUzMzoCTEFCAzUzM0gBUgM3ODkKWQoDU0NMEhkyMDI3LTAzLTA2VDExOjI5OjAwLTAzOjAwGgNQTUMiGTIwMjctMDMtMDZUMTM6MTQ6MDAtMDM6MDAqAkxBMgMzMTE6AkxBQgMzMTFIAVIDMzIxClkKA1BNQxIZMjAyNy0wMy0wNlQxNDoxMDowMC0wMzowMBoDUFVRIhkyMDI3LTAzLTA2VDE2OjIwOjAwLTAzOjAwKgJMQTIDMzExOgJMQUIDMzExSAFSAzMyMRIECAMQARgBKAAyBwoFTEFUQU0qBkNocm9tZQ\\u003d\\u003d\"]",[[1]],0],[["LA",["LATAM"],[[null,null,"Latam Airlines Group","JFK","John F. Kennedy International Airport","Arturo Merino Benitez International Airport","SCL",null,[18,25],1,[6,55],630,[null,1,null,null,null,null,null,null,null,1],3,"32 in",null,1,"Boeing 787",[1,1],0,[2027,3,5],[2027,3,6],["LA","533",null,"LATAM"],null,null,1,null,null,null,null,"32 inches",455029,2],[null,null,"Latam Airlines Group","SCL","Arturo Merino Benitez International Airport","Punta Arenas C.Ibanez del Campo","PUQ",1,[15,32],1,[18,57],205,[null,null,null,null,null,1,null,null,null,null,1,3],2,"28 in",null,1,"Airbus A321",null,0,[2027,3,6],[2027,3,6],["LA","91",null,"LATAM"],null,null,1,null,null,null,null,"28 inches",185083,2]],"JFK",[2027,3,5],[18,25],"PUQ",[2027,3,6],[18,57],1352,1,null,0,[[517,"SCL","SCL",[3],"Arturo Merino Benitez International Airport","Santiago","Arturo Merino Benitez International Airport","Santiago"]],null,null,null,"my8qp",[[1792347802679287,44789107,3390031733],null,null,null,null,[[3]]],1,null,null,[null,null,1,-14,null,1,1,640000,741000,[1],655000,2,0,null,null,2,null,4],[1],[["LA","LATAM","https://www.latamairlines.com/us/en/help-center/faq/special-needs"]]],[[null,1238],"CjRIb3Z2cUtjWFJNbklBQWcwcndCRy0tLS0tLS0tdnRiZXUxNkFBQUFBR3JWRHBvS1VkZUdBEgpMQTUzM3xMQTkxGgsIjccHEAIaA1VTRDgdcI3HBw\u003d\u003d"],null,1,[null,null,null,null,1,null,[null,1]],[0,0,0],0,[],"[\"CAISA1VTRBoECI3HByLKAQq0AQpZCgNKRksSGTIwMjctMDMtMDVUMTg6MjU6MDAtMDU6MDAaA1NDTCIZMjAyNy0wMy0wNlQwNjo1NTowMC0wMzowMCoCTEEyAzUzMzoCTEFCAzUzM0gBUgM3ODkKVwoDU0NMEhkyMDI3LTAzLTA2VDE1OjMyOjAwLTAzOjAwGgNQVVEiGTIwMjctMDMtMDZUMTg6NTc6MDAtMDM6MDAqAkxBMgI5MToCTEFCAjkxSAFSAzMyMRIECAMQARgBKAAyBwoFTEFUQU0qBkNocm9tZQ\\u003d\\u003d\"]",[[1]],0],[["LA",["LATAM"],[[null,null,"Latam Airlines Group","JFK","John F. Kennedy International Airport","Arturo Merino Benitez International Airport","SCL",null,[18,25],1,[6,55],630,[null,1,null,null,null,null,null,null,null,1],3,"32 in",null,1,"Boeing 787",[1,1],0,[2027,3,5],[2027,3,6],["LA","533",null,"LATAM"],null,null,1,null,null,null,null,"32 inches",455029,2],[null,null,"Latam Airlines Group","SCL","Arturo Merino Benitez International Airport","Punta Arenas C.Ibanez del Campo","PUQ",1,[8,51],1,[12,16],205,[null,null,null,null,null,1,null,null,null,null,1,3],2,"28 in",null,1,"Airbus A321",null,0,[2027,3,6],[2027,3,6],["LA","83",null,"LATAM"],null,null,1,null,null,null,null,"28 inches",185083,2]],"JFK",[2027,3,5],[18,25],"PUQ",[2027,3,6],[12,16],951,1,null,0,[[116,"SCL","SCL",null,"Arturo Merino Benitez International Airport","Santiago","Arturo Merino Benitez International Airport","Santiago"]],null,null,null,"vCeKhf",[[1792347802679287,44789107,3390031733],null,null,null,null,[[4]]],1,null,null,[null,null,1,-14,null,1,1,640000,741000,[1],655000,2,0,null,null,2,null,4],[1],[["LA","LATAM","https://www.latamairlines.com/us/en/help-center/faq/special-needs"]]],[[null,1256],"CjRIb3Z2cUtjWFJNbklBQWcwcndCRy0tLS0tLS0tdnRiZXUxNkFBQUFBR3JWRHBvS1VkZUdBEgpMQTUzM3xMQTgzGgsIldUHEAIaA1VTRDgdcJXVBw\u003d\u003d"],null,1,[null,null,null,null,1,null,[null,1]],[0,0,0],0,[],"[\"CAISA1VTRBoECJXVByLKAQq0AQpZCgNKRksSGTIwMjctMDMtMDVUMTg6MjU6MDAtMDU6MDAaA1NDTCIZMjAyNy0wMy0wNlQwNjo1NTowMC0wMzowMCoCTEEyAzUzMzoCTEFCAzUzM0gBUgM3ODkKVwoDU0NMEhkyMDI3LTAzLTA2VDA4OjUxOjAwLTAzOjAwGgNQVVEiGTIwMjctMDMtMDZUMTI6MTY6MDAtMDM6MDAqAkxBMgI4MzoCTEFCAjgzSAFSAzMyMRIECAMQARgBKAAyBwoFTEFUQU0qBkNocm9tZQ\\u003d\\u003d\"]",[[1]],0],[["LA",["LATAM"],[[null,null,"Latam Airlines Peru","JFK","John F. Kennedy International Airport","New Jorge Chávez International Airport","LIM",null,[12,50],null,[21],490,[null,1,null,null,null,null,null,null,null,1],1,"31 in",null,1,"Boeing 767",null,0,[2027,3,5],[2027,3,5],["LA","2691",null,"LATAM"],null,null,1,null,null,null,null,"31 inches",479947,2],[null,null,"Latam Airlines Group","LIM","New Jorge Chávez International Airport","Arturo Merino Benitez International Airport","SCL",null,[23,50],1,[5,20],210,[null,null,null,null,null,1,null,null,null,null,1,3],2,"28 in",null,1,"Airbus A320",[1],0,[2027,3,5],[2027,3,6],["LA","509",null,"LATAM"],null,null,1,null,null,null,null,"28 inches",201374,2],[null,null,"Latam Airlines Group","SCL","Arturo Merino Benitez International Airport","Punta Arenas C.Ibanez del Campo","PUQ",1,[7,24],1,[10,49],205,[null,null,null,null,null,1,null,null,null,null,1,3],2,"28 in",null,1,"Airbus A320",null,0,[2027,3,6],[2027,3,6],["LA","81",null,"LATAM"],null,null,1,null,null,null,null,"28 inches",184356,2]],"JFK",[2027,3,5],[12,50],"PUQ",[2027,3,6],[10,49],1199,1,null,0,[[170,"LIM","LIM",null,"New Jorge Chávez International Airport","Lima","New Jorge Chávez International Airport","Lima"],[124,"SCL","SCL",null,"Arturo Merino Benitez International Airport","Santiago","Arturo Merino Benitez International Airport","Santiago"]],null,null,null,"xtzYEb",[[1792347802679287,44789107,3390031733],null,null,null,null,[[5]]],1,null,null,[null,null,3,17,null,1,1,866000,741000,null,655000,3,0,null,null,2,null,6],[1],[["LA","LATAM","https://www.latamairlines.com/us/en/help-center/faq/special-needs"]]],[[null,1266],"CjRIb3Z2cUtjWFJNbklBQWcwcndCRy0tLS0tLS0tdnRiZXUxNkFBQUFBR3JWRHBvS1VkZUdBEhFMQTI2OTF8TEE1MDl8TEE4MRoLCLjcBxACGgNVU0Q4HXC43Ac\u003d"],null,1,[null,null,null,null,1,null,[null,1]],[0,0,0],0,[],"[\"CAISA1VTRBoECLjcByKnAgqRAgpbCgNKRksSGTIwMjctMDMtMDVUMTI6NTA6MDAtMDU6MDAaA0xJTSIZMjAyNy0wMy0wNVQyMTowMDowMC0wNTowMCoCTEEyBDI2OTE6AkxBQgQyNjkxSAFSAzc2MwpZCgNMSU0SGTIwMjctMDMtMDVUMjM6NTA6MDAtMDU6MDAaA1NDTCIZMjAyNy0wMy0wNlQwNToyMDowMC0wMzowMCoCTEEyAzUwOToCTEFCAzUwOUgBUgMzMjAKVwoDU0NMEhkyMDI3LTAzLTA2VDA3OjI0OjAwLTAzOjAwGgNQVVEiGTIwMjctMDMtMDZUMTA6NDk6MDAtMDM6MDAqAkxBMgI4MToCTEFCAjgxSAFSAzMyMBIECAMQARgBKAAyBwoFTEFUQU0qBkNocm9tZQ\\u003d\\u003d\"]",[[2]],0]],4,0,0,[1]],null,[5,[null,1238],[null,995],[null,-244],[null,930],[null,1150],1,null,null,null,[[[1787112000000,943],[1787198400000,943],[1787284800000,943],[1787371200000,1159],[1787457600000,1159],[1787544000000,1159],[1787630400000,1159],[1787716800000,1140],[1787803200000,1140],[1787889600000,940],[1787976000000,940],[1788062400000,940],[1788148800000,940],[1788235200000,940],[1788321600000,940],[1788408000000,940],[1788494400000,1140],[1788580800000,1194],[1788667200000,1194],[1788753600000,1194],[1788840000000,1194],[1788926400000,1140],[1789012800000,1140],[1789099200000,1159],[1789185600000,1159],[1789272000000,1187],[1789358400000,1159],[1789444800000,1159],[1789531200000,1214],[1789617600000,1214],[1789704000000,1220],[1789790400000,1253],[1789876800000,1253],[1789963200000,1214],[1790049600000,1223],[1790136000000,1259],[1790222400000,1245],[1790308800000,1244],[1790395200000,1241],[1790481600000,1241],[1790568000000,1241],[1790654400000,1241],[1790740800000,1063],[1790827200000,1016],[1790913600000,1016],[1791000000000,1016],[1791086400000,1016],[1791172800000,1016],[1791259200000,1016],[1791345600000,1016],[1791432000000,1016],[1791518400000,1286],[1791604800000,1239],[1791691200000,1239],[1791777600000,1239],[1791864000000,1239],[1791950400000,1239],[1792036800000,1287],[1792123200000,1239],[1792209600000,1238],[1792296000000,1238]]],[[1792347802679287,44789107,3390031733],null,null,null,null,[[6]]],"Punta Arenas"],null,[[[null,1238],[null,2500]],[[["ONEWORLD","Oneworld"],["SKYTEAM","SkyTeam"],["STAR_ALLIANCE","Star Alliance"]],[["DL","Delta"],["LA","LATAM"]]],[[["ATL","Atlanta"],["EZE","Buenos Aires"],["GYE","Guayaquil"],["LIM","Lima"],["LAX","Los Angeles"],["MIA","Miami"],["PMC","Puerto Montt"],["SCL","Santiago"],["GRU","São Paulo"]],50,1491],[951,2329],[[2,3]],[1,0,0,0],null,[0]],null,null,null,[["LA","LATAM","https://www.latam.com/en_us/travel-information/baggage/checked-baggage/"]],["EAEaBAgDEAEhw/UoXI9Xk0AqA1VTRDIwChYKA0pGSxIDUFVRGgoyMDI3LTAzLTA1ChYKA1BVURIDSkZLGgoyMDI3LTAzLTE0UAFiOQoqCgcKA0pGSxABEgcKA1BVURABGgoyMDI3LTAzLTA1IgoyMDI3LTAzLTE0GgsKBAgDEAEQAYgBAWgAcMib9zJw/pP2MnC9mOkycJHd1jI\u003d",0],null,[[1792347802679287,44789107,3390031733],null,null,null,null,[[0]]],null,null,[[["ATL",0],"Hartsfield-Jackson Atlanta International Airport",["/m/013yq","Atlanta",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRJh6WEANkd6cril2a8Csnk2i_WTs-ZTUE-pamQ4iTfpTi0hlx5P9xhDKrUeBWRPb-4hiLgvoegdgPZ2t2R8qpkN_a7BzJjUNSnSonV664"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQYBXd-jsaFCOrq3Ftbagud_RXYRp8gK_jeDmxAfPmI5pP7SIRedYhExpUTLErX68PeHFvOzs8P_D0v_w"]]],[33.6366667,-84.427778],"US",0,"United States"],[["/m/013yq",4],"Atlanta",["/m/013yq","Atlanta",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRJh6WEANkd6cril2a8Csnk2i_WTs-ZTUE-pamQ4iTfpTi0hlx5P9xhDKrUeBWRPb-4hiLgvoegdgPZ2t2R8qpkN_a7BzJjUNSnSonV664"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQYBXd-jsaFCOrq3Ftbagud_RXYRp8gK_jeDmxAfPmI5pP7SIRedYhExpUTLErX68PeHFvOzs8P_D0v_w"]],"Coca-Cola, Buckhead \u0026 Martin Luther King","Georgia capital with Coca-Cola museum, Buckhead \u0026 Martin Luther King Jr National Historic Site.","ATL"],[33.7501275,-84.3885209],"US",null,"United States"],[["BUE",0],"Metropolitan Area",["/m/01ly5m","Buenos Aires",[["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcRjPsid8HQwZLpCB-QGyp_Sv0aoHPrBnZ7h7mygjconIcppC2tUm7xktKrXHl4E6I1cxwdLTaixDzmpo6dPL7DUHAyyhtojQ0gEZOSSnu4"],["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcT-_8Wir2bWSV6c5vDI6iSYjPHXjnWEuFr-Xg33JSybgBo36nv4VTOA4K1Sl04Tl_Y4XIp-2BjVw0X7QA"]]],[-34.6036844,-58.3815591],"AR",0,"Argentina"],[["/m/01ly5m",4],"Buenos Aires",["/m/01ly5m","Buenos Aires",[["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcRjPsid8HQwZLpCB-QGyp_Sv0aoHPrBnZ7h7mygjconIcppC2tUm7xktKrXHl4E6I1cxwdLTaixDzmpo6dPL7DUHAyyhtojQ0gEZOSSnu4"],["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcT-_8Wir2bWSV6c5vDI6iSYjPHXjnWEuFr-Xg33JSybgBo36nv4VTOA4K1Sl04Tl_Y4XIp-2BjVw0X7QA"]],"Casa Rosada, Teatro Colón \u0026 MALBA museum","Argentina capital with European-style landmarks Casa Rosada \u0026 Teatro Colón, plus MALBA art museum.","BUE"],[-34.6036739,-58.3821215],"AR",null,"Argentina"],[["EZE",0],"Ezeiza International Airport",["/m/01ly5m","Buenos Aires",[["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcRjPsid8HQwZLpCB-QGyp_Sv0aoHPrBnZ7h7mygjconIcppC2tUm7xktKrXHl4E6I1cxwdLTaixDzmpo6dPL7DUHAyyhtojQ0gEZOSSnu4"],["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcT-_8Wir2bWSV6c5vDI6iSYjPHXjnWEuFr-Xg33JSybgBo36nv4VTOA4K1Sl04Tl_Y4XIp-2BjVw0X7QA"]]],[-34.822222,-58.535833],"AR",0,"Argentina"],[["GRU",0],"São Paulo/Guarulhos–Governor André Franco Montoro International Airport",["/m/022pfm","São Paulo",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcQ4D5SB4Yfugl7neBSWCiZ5gRiYxGRSSCYavaGuPsXj1q6Hk3Gv5C78US7ZqeotwTy5BX6xGe9CpXQkvQM45Mjnol7egb_CdoPyBoVeqB8"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTkx9athZsBRDrcQSs15lBM_on9PkrTwz-ySvt8J6pcJZSuqg14GFxUPDm1FgV3ckvtmLWX0pDDIkRldw"]]],[-23.435556,-46.473056],"BR",0,"Brazil"],[["/m/022pfm",4],"São Paulo",["/m/022pfm","São Paulo",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcQ4D5SB4Yfugl7neBSWCiZ5gRiYxGRSSCYavaGuPsXj1q6Hk3Gv5C78US7ZqeotwTy5BX6xGe9CpXQkvQM45Mjnol7egb_CdoPyBoVeqB8"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTkx9athZsBRDrcQSs15lBM_on9PkrTwz-ySvt8J6pcJZSuqg14GFxUPDm1FgV3ckvtmLWX0pDDIkRldw"]],"Financial center and Edifício Copan","Vast Brazilian metropolis with iconic architecture, São Paulo Museum of Modern Art \u0026 shopping.","SAO"],[-23.5557714,-46.6395571],"BR",null,"Brazil"],[["GYE",0],"José Joaquín de Olmedo International Airport",["/m/01fknt","Guayaquil",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRZv3qTTQnpI_jDm8iA91jkUxztPud8NkEcfnQk5JNvKkGpjUAFdpGuxm13YYwE_9sKEdIcXLKIM7vuEa_uZQZgME1O171bsGMDUwHAgQA"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS1momD9pcfz1lL5sdJ6ETswtbac8hAgJnw97uEzAB8XeZT5pNStWY0O9vq-rI6ohNaK6iMLozLmiFQuQ"]]],[-2.1580556,-79.883889],"EC",0,"Ecuador"],[["/m/01fknt",4],"Guayaquil",["/m/01fknt","Guayaquil",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRZv3qTTQnpI_jDm8iA91jkUxztPud8NkEcfnQk5JNvKkGpjUAFdpGuxm13YYwE_9sKEdIcXLKIM7vuEa_uZQZgME1O171bsGMDUwHAgQA"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS1momD9pcfz1lL5sdJ6ETswtbac8hAgJnw97uEzAB8XeZT5pNStWY0O9vq-rI6ohNaK6iMLozLmiFQuQ"]],"Simón Bolívar promenade \u0026 Santa Ana Hill","Ecuadorian port city known for Simón Bolívar promenade, Santa Ana Hill \u0026 colorful Las Peñas houses.","GYE"],[-2.1891341,-79.8899031],"EC",null,"Ecuador"],[["JFK",0],"John F. Kennedy International Airport",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]]],[40.6397222,-73.778889],"US",0,"United States"],[["/m/02_286",4],"New York",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]],"Statue of Liberty, skyscrapers \u0026 culture","Influential metropolis known for the Statue of Liberty, Empire State Building \u0026 Times Square.","NYC"],[40.7127753,-74.0059728],"US",null,"United States"],[["LAX",0],"Los Angeles International Airport",["/m/030qb3t","Los Angeles",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcT4B0K7etaN3KgEgtU5dJajdcmLtB5QSDRYr4KqcwH1iWxMm7TIqwtcUTTHD5AmNyeeFIpVpTnbSDeuD_HVlkYzOam-TO9w1worRSGRTUo"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTFuS2Y5_b7ZIl-g2Hm7jnG7zoi2uk0CQltF_DFbp6gIzfYznnOB6uJm9d6ePT5PJO5XM1j8vigwCNxRA"]]],[33.9425,-118.40806],"US",0,"United States"],[["/m/030qb3t",4],"Los Angeles",["/m/030qb3t","Los Angeles",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcT4B0K7etaN3KgEgtU5dJajdcmLtB5QSDRYr4KqcwH1iWxMm7TIqwtcUTTHD5AmNyeeFIpVpTnbSDeuD_HVlkYzOam-TO9w1worRSGRTUo"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTFuS2Y5_b7ZIl-g2Hm7jnG7zoi2uk0CQltF_DFbp6gIzfYznnOB6uJm9d6ePT5PJO5XM1j8vigwCNxRA"]],"Hollywood, Venice beach \u0026 the Lakers","Sunny city known for the Hollywood film industry, Venice \u0026 Santa Monica beaches \u0026 Lakers basketball.","LAX"],[34.0549076,-118.242643],"US",null,"United States"],[["LIM",0],"New Jorge Chávez International Airport",["/m/0lpfh","Lima",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTEtUnreFpY47ZyuGpKyyuUXxdu4-fNeyFjjAQxzmRlO-2yTAr7QR6txl0_bpdD4WNOMNnMVXsEMHOdh7iU-JhOZ3SLpg1oPfPdPyLGz5g"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcSfj6UMMOtH7UfdiBBAwDzl9eZfkmq2MSdmuiXiTlDf8DzzkasO79cO5jXlUEqfqycQTQd3-RTmn4H9FQ"]]],[-12.021944,-77.114444],"PE",0,"Peru"],[["/m/0lpfh",4],"Lima",["/m/0lpfh","Lima",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTEtUnreFpY47ZyuGpKyyuUXxdu4-fNeyFjjAQxzmRlO-2yTAr7QR6txl0_bpdD4WNOMNnMVXsEMHOdh7iU-JhOZ3SLpg1oPfPdPyLGz5g"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcSfj6UMMOtH7UfdiBBAwDzl9eZfkmq2MSdmuiXiTlDf8DzzkasO79cO5jXlUEqfqycQTQd3-RTmn4H9FQ"]],"Museo Larco art \u0026 colonial architecture","Peru's bustling capital, with Spanish colonial buildings, Museo Larco art \u0026 a vibrant food scene.","LIM"],[-12.0466888,-77.0430886],"PE",null,"Peru"],[["MIA",0],"Miami International Airport",["/m/0f2v0","Miami",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRScvUK_JtYRXmQWoXHiT98Ajl1KTuUVO40d0Q678OpK1xyyWI8VIkHqzXE9BHfY5R35UpgbeEdcf1IhMDncXwDo29wOABY9MIUzCFLkwU"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRjsG6ybk9C2oSVnPZUal-6l7EimKLf5gtMAhOumgD16nXBwB4X0lHH3nh-178HKbonabZtnDMdZKfDEQ"]]],[25.7952778,-80.29],"US",0,"United States"],[["/m/0f2v0",4],"Miami",["/m/0f2v0","Miami",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRScvUK_JtYRXmQWoXHiT98Ajl1KTuUVO40d0Q678OpK1xyyWI8VIkHqzXE9BHfY5R35UpgbeEdcf1IhMDncXwDo29wOABY9MIUzCFLkwU"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRjsG6ybk9C2oSVnPZUal-6l7EimKLf5gtMAhOumgD16nXBwB4X0lHH3nh-178HKbonabZtnDMdZKfDEQ"]],"South Beach, art deco \u0026 Little Havana","Stylish Florida city known for South Beach, art deco architecture, contemporary art \u0026 Little Havana.","MIA"],[25.7616798,-80.1917902],"US",null,"United States"],[["NYC",0],"Metropolitan Area",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]]],[40.7127837,-74.0059413],"US",0,"United States"],[["PMC",0],"Aeropuerto El Tepual",["/m/03fxkl","Puerto Montt",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRORwEeMxi4KrNjFXknRPgTiiipVv76ScHe5CbiWC1kTFKY2vKFG7MLWOUuyeD2rF6WaRGGC9uU3txX7glRYM-UpYw5-QYJqbBTizRB-zo"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRqwbGgcYEeQq1e-wWMkVRLV2oiaiSXvpXSTUIlJPj-7lfi1nPGV1NQKwl90T0dz5GfUQbgdWChTh6xsw"]]],[-41.438889,-73.093889],"CL",0,"Chile"],[["/m/03fxkl",4],"Puerto Montt",["/m/03fxkl","Puerto Montt",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRORwEeMxi4KrNjFXknRPgTiiipVv76ScHe5CbiWC1kTFKY2vKFG7MLWOUuyeD2rF6WaRGGC9uU3txX7glRYM-UpYw5-QYJqbBTizRB-zo"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRqwbGgcYEeQq1e-wWMkVRLV2oiaiSXvpXSTUIlJPj-7lfi1nPGV1NQKwl90T0dz5GfUQbgdWChTh6xsw"]],"Lake District town by Andes \u0026 fjords ","Port city in southern Chile’s Lake District, with access to the Andes \u0026 the Patagonian fjords.","PMC"],[-41.4693622,-72.9424405],"CL",null,"Chile"],[["PUQ",0],"Punta Arenas C.Ibanez del Campo",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]]],[-53.003611,-70.853611],"CL",0,"Chile"],[["/m/02n5vc",4],"Punta Arenas",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]],"Strait of Magellan city \u0026 travel base ","Chilean city on the Strait of Magellan often used as a base for exploring Patagonia or Antarctica.","PUQ"],[-53.1633778,-70.907705],"CL",null,"Chile"],[["SAO",0],"Metropolitan Area",["/m/022pfm","São Paulo",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcQ4D5SB4Yfugl7neBSWCiZ5gRiYxGRSSCYavaGuPsXj1q6Hk3Gv5C78US7ZqeotwTy5BX6xGe9CpXQkvQM45Mjnol7egb_CdoPyBoVeqB8"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTkx9athZsBRDrcQSs15lBM_on9PkrTwz-ySvt8J6pcJZSuqg14GFxUPDm1FgV3ckvtmLWX0pDDIkRldw"]]],[-23.5505199,-46.6333094],"BR",0,"Brazil"],[["SCL",0],"Arturo Merino Benitez International Airport",["/m/0dlqv","Santiago",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRu8XbKo--iOQm3xQMbMlH3CvyC0_8ugOijIGErV6oc-P-94_9SCS4cCukIHsMudloel-9wvxUwcEtdupw_blbMqnBZHsdfxRBlxceNOVE"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQpDde4uka4doBsXbshQy4M_6et9NZ4XeEv9aoG8YinL-iQ73D-8RN_FUnvMZnHG6E-HkyVkW8_FQyAAA"]]],[-33.394444,-70.793889],"CL",0,"Chile"],[["/m/0dlqv",4],"Santiago",["/m/0dlqv","Santiago",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRu8XbKo--iOQm3xQMbMlH3CvyC0_8ugOijIGErV6oc-P-94_9SCS4cCukIHsMudloel-9wvxUwcEtdupw_blbMqnBZHsdfxRBlxceNOVE"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQpDde4uka4doBsXbshQy4M_6et9NZ4XeEv9aoG8YinL-iQ73D-8RN_FUnvMZnHG6E-HkyVkW8_FQyAAA"]],"Plaza de Armas \u0026 Parque Metropolitano","Chilean capital, surrounded by mountains, home to the Plaza de Armas \u0026 Parque Metropolitano.","SCL"],[-33.4488897,-70.6692655],"CL",null,"Chile"]],["EAEaBAgDEAEhw/UoXI9Xk0AqA1VTRDIAUAFiGxoLCgQIAxABEAGIAQEqDBgCIgNKRksqA1BVUWgAcMib9zJw/pP2MnC9mOkycJHd1jI\u003d",0],null,0,null,null,1,null,[[null,1238]],[["LA","LATAM","https://www.latamairlines.com/us/en/help-center/faq/special-needs"]],null,null,null,[[null,1238],"CjRIb3Z2cUtjWFJNbklBQWcwcndCRy0tLS0tLS0tdnRiZXUxNkFBQUFBR3JWRHBvS1VkZUdBEhZjb21wcmVoZW5zaXZlbmVzc19sdXJlGgsIjccHEAIaA1VTRDgdcI3HBw\u003d\u003d"],1], sideChannel: {}});
```

- [ ] **Step 2: Write the failing test file `tests/sources/fixtures/real_google_page_PHL_PUQ_2027-03-05_2027-03-14.js`**

```
AF_initDataCallback({key: 'ds:1', hash: '9', data:[[null,[[1792347802215987,44786673,3910920362],null,null,null,null,[[1]]],0,"mg7VarOXDfHHrcUPqtHvyA4","H6Mhe2h70FBQAOpuFABG----------vwkz5AAAAAGrVDpoDXc8MA"],[[[[["PHL",0],"Philadelphia International Airport",["/m/0dclg","Philadelphia",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQcbg0MnkfnE9eUvuKJHou5Caj1zXMtLuK1wucPijlSVZHg0_DCECdu7dBehpeDVmqlVsZG-V2pdNwIiNJRUy3jQZDrURZJmdChItPVIzE"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcSvvZz4z_jCKaFlTmcR9EOv7ERVk2fCwtz7mkp5JOMIEQyrifb8NStFsoeGEIOCcSh8SSzlee2du3hn4A"]]],[39.8722222,-75.240833],"US",0,"United States"]],[[["PUQ",0],"Punta Arenas C.Ibanez del Campo",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]]],[-53.003611,-70.853611],"CL",0,"Chile"]]],[[[["PUQ",0],"Punta Arenas C.Ibanez del Campo",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]]],[-53.003611,-70.853611],"CL",0,"Chile"]],[[["PHL",0],"Philadelphia International Airport",["/m/0dclg","Philadelphia",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQcbg0MnkfnE9eUvuKJHou5Caj1zXMtLuK1wucPijlSVZHg0_DCECdu7dBehpeDVmqlVsZG-V2pdNwIiNJRUy3jQZDrURZJmdChItPVIzE"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcSvvZz4z_jCKaFlTmcR9EOv7ERVk2fCwtz7mkp5JOMIEQyrifb8NStFsoeGEIOCcSh8SSzlee2du3hn4A"]]],[39.8722222,-75.240833],"US",0,"United States"]]]],null,null,null,null,[[null,null,null,null,[null,[["EWR",1,[[null,1504],"CjRINk1oZTJoNzBGQlFBT3B1RkFCRy0tLS0tLS0tLS12d2t6NUFBQUFBR3JWRHBvRFhjOE1BEiRub3Jlc3VsdHN8YWdnfG5lYXJieTpkZXBhcnR1cmUtRVdSLTMaCwjrlgkQAhoDVVNEOB1w65YJ"],null,"80 mi"],["BWI",1,[[null,1148],"CjRINk1oZTJoNzBGQlFBT3B1RkFCRy0tLS0tLS0tLS12d2t6NUFBQUFBR3JWRHBvRFhjOE1BEiRub3Jlc3VsdHN8YWdnfG5lYXJieTpkZXBhcnR1cmUtQldJLTMaCwjZgAcQAhoDVVNEOB1w2YAH"],null,"89 mi"],["JFK",1,[[null,1238],"CjRINk1oZTJoNzBGQlFBT3B1RkFCRy0tLS0tLS0tLS12d2t6NUFBQUFBR3JWRHBvRFhjOE1BEiRub3Jlc3VsdHN8YWdnfG5lYXJieTpkZXBhcnR1cmUtSkZLLTEaCwiNxwcQAhoDVVNEOB1wjccH"],"/m/02_286","93 mi"],["LGA",1,[[null,1291],"CjRINk1oZTJoNzBGQlFBT3B1RkFCRy0tLS0tLS0tLS12d2t6NUFBQUFBR3JWRHBvRFhjOE1BEiRub3Jlc3VsdHN8YWdnfG5lYXJieTpkZXBhcnR1cmUtTEdBLTIaCwi88AcQAhoDVVNEOB1wvPAH"],null,"95 mi"],["DCA",1,[[null,1124],"CjRINk1oZTJoNzBGQlFBT3B1RkFCRy0tLS0tLS0tLS12d2t6NUFBQUFBR3JWRHBvRFhjOE1BEiRub3Jlc3VsdHN8YWdnfG5lYXJieTpkZXBhcnR1cmUtRENBLTIaCwjq7QYQAhoDVVNEOB1w6u0G"],null,"119 mi"],["IAD",1,[[null,1415],"CjRINk1oZTJoNzBGQlFBT3B1RkFCRy0tLS0tLS0tLS12d2t6NUFBQUFBR3JWRHBvRFhjOE1BEiRub3Jlc3VsdHN8YWdnfG5lYXJieTpkZXBhcnR1cmUtSUFELTMaCwj/0AgQAhoDVVNEOB1w/9AI"],null,"134 mi"]]]]],[null,[[["ONEWORLD","Oneworld"],["SKYTEAM","SkyTeam"],["STAR_ALLIANCE","Star Alliance"]],[["DL","Delta"],["LA","LATAM"]]],[[["ATL","Atlanta"],["BOG","Bogotá"],["EZE","Buenos Aires"],["DTW","Detroit"],["LIM","Lima"],["MIA","Miami"],["MSP","Minneapolis"],["JFK","New York"],["PMC","Puerto Montt"],["UIO","Quito"],["SCL","Santiago"]]],null,[[3]],[1,0,0,0],null,[0]],null,null,null,null,["EAEaBAgDEAEyMAoWCgNQSEwSA1BVURoKMjAyNy0wMy0wNQoWCgNQVVESA1BITBoKMjAyNy0wMy0xNFABYjkKKgoHCgNQSEwQARIHCgNQVVEQARoKMjAyNy0wMy0wNSIKMjAyNy0wMy0xNBoLCgQIAxABEAGIAQFoAHDIm/cycP2T9jJwvZjpMnCR3dYy",0],null,[[1792347802215987,44786673,3910920362],null,null,null,null,[[0]]],null,null,[[["ATL",0],"Hartsfield-Jackson Atlanta International Airport",["/m/013yq","Atlanta",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRJh6WEANkd6cril2a8Csnk2i_WTs-ZTUE-pamQ4iTfpTi0hlx5P9xhDKrUeBWRPb-4hiLgvoegdgPZ2t2R8qpkN_a7BzJjUNSnSonV664"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQYBXd-jsaFCOrq3Ftbagud_RXYRp8gK_jeDmxAfPmI5pP7SIRedYhExpUTLErX68PeHFvOzs8P_D0v_w"]]],[33.6366667,-84.427778],"US",0,"United States"],[["/m/013yq",4],"Atlanta",["/m/013yq","Atlanta",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRJh6WEANkd6cril2a8Csnk2i_WTs-ZTUE-pamQ4iTfpTi0hlx5P9xhDKrUeBWRPb-4hiLgvoegdgPZ2t2R8qpkN_a7BzJjUNSnSonV664"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQYBXd-jsaFCOrq3Ftbagud_RXYRp8gK_jeDmxAfPmI5pP7SIRedYhExpUTLErX68PeHFvOzs8P_D0v_w"]],"Coca-Cola, Buckhead \u0026 Martin Luther King","Georgia capital with Coca-Cola museum, Buckhead \u0026 Martin Luther King Jr National Historic Site.","ATL"],[33.7501275,-84.3885209],"US",null,"United States"],[["BOG",0],"El Dorado International Airport",["/m/01dzyc","Bogotá",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcSqm71KiEEpJ9v4n76TSrywWmNERejtes9mwE5yTpQM1Xp3U5aZJ5HpIaBwbTrH13E97p_h7aB4NA_WFzLykvNRqCKasUfjPwC8QniELRk"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcQbtcBsGfGa0uo75yD0qTm7U07SGebsTE16mhsldZ-Sf4fNMoLlSMxujfnmzcNxaA3YTMzw8FzgMBU-yA"]]],[4.70166667,-74.146944],"CO",0,"Colombia"],[["/m/01dzyc",4],"Bogotá",["/m/01dzyc","Bogotá",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcSqm71KiEEpJ9v4n76TSrywWmNERejtes9mwE5yTpQM1Xp3U5aZJ5HpIaBwbTrH13E97p_h7aB4NA_WFzLykvNRqCKasUfjPwC8QniELRk"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcQbtcBsGfGa0uo75yD0qTm7U07SGebsTE16mhsldZ-Sf4fNMoLlSMxujfnmzcNxaA3YTMzw8FzgMBU-yA"]],"Museo del Oro \u0026 colonial-era landmarks","Colombian capital known for the Museo del Oro (Gold Museum), colonial sites \u0026 modern nightclubs.","BOG"],[4.7109886,-74.072092],"CO",null,"Colombia"],[["BUE",0],"Metropolitan Area",["/m/01ly5m","Buenos Aires",[["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcRjPsid8HQwZLpCB-QGyp_Sv0aoHPrBnZ7h7mygjconIcppC2tUm7xktKrXHl4E6I1cxwdLTaixDzmpo6dPL7DUHAyyhtojQ0gEZOSSnu4"],["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcT-_8Wir2bWSV6c5vDI6iSYjPHXjnWEuFr-Xg33JSybgBo36nv4VTOA4K1Sl04Tl_Y4XIp-2BjVw0X7QA"]]],[-34.6036844,-58.3815591],"AR",0,"Argentina"],[["/m/01ly5m",4],"Buenos Aires",["/m/01ly5m","Buenos Aires",[["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcRjPsid8HQwZLpCB-QGyp_Sv0aoHPrBnZ7h7mygjconIcppC2tUm7xktKrXHl4E6I1cxwdLTaixDzmpo6dPL7DUHAyyhtojQ0gEZOSSnu4"],["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcT-_8Wir2bWSV6c5vDI6iSYjPHXjnWEuFr-Xg33JSybgBo36nv4VTOA4K1Sl04Tl_Y4XIp-2BjVw0X7QA"]],"Casa Rosada, Teatro Colón \u0026 MALBA museum","Argentina capital with European-style landmarks Casa Rosada \u0026 Teatro Colón, plus MALBA art museum.","BUE"],[-34.6036739,-58.3821215],"AR",null,"Argentina"],[["DTW",0],"Detroit Metropolitan Wayne County Airport",["/m/02dtg","Detroit",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcSLzktjJPbJWpjXl1ZSYRz56GZ46-c_yoPIjxNBooT6XhL3kRcO9Hgj4d61TOWWofyftp77t-Xphkog3mdEoWczq1_BbvKctQL77uK5nC0"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQ6tCKi37Y2EFKBit2BFOdzMPDMIOPD61N33bJ6TPBfGhdv-qnbRdXODK9GFZ4072j7q-CnrkO_vQFBTQ"]]],[42.2125,-83.353333],"US",0,"United States"],[["/m/02dtg",4],"Detroit",["/m/02dtg","Detroit",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcSLzktjJPbJWpjXl1ZSYRz56GZ46-c_yoPIjxNBooT6XhL3kRcO9Hgj4d61TOWWofyftp77t-Xphkog3mdEoWczq1_BbvKctQL77uK5nC0"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQ6tCKi37Y2EFKBit2BFOdzMPDMIOPD61N33bJ6TPBfGhdv-qnbRdXODK9GFZ4072j7q-CnrkO_vQFBTQ"]],"Michigan city famed for cars \u0026 Motown","Michigan city known for its auto industry, Detroit Institute of Art \u0026 as the birthplace of Motown.","DTT"],[42.3297182,-83.0424533],"US",null,"United States"],[["EZE",0],"Ezeiza International Airport",["/m/01ly5m","Buenos Aires",[["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcRjPsid8HQwZLpCB-QGyp_Sv0aoHPrBnZ7h7mygjconIcppC2tUm7xktKrXHl4E6I1cxwdLTaixDzmpo6dPL7DUHAyyhtojQ0gEZOSSnu4"],["https://encrypted-tbn0.gstatic.com/images?q\u003dtbn:ANd9GcT-_8Wir2bWSV6c5vDI6iSYjPHXjnWEuFr-Xg33JSybgBo36nv4VTOA4K1Sl04Tl_Y4XIp-2BjVw0X7QA"]]],[-34.822222,-58.535833],"AR",0,"Argentina"],[["JFK",0],"John F. Kennedy International Airport",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]]],[40.6397222,-73.778889],"US",0,"United States"],[["/m/02_286",4],"New York",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]],"Statue of Liberty, skyscrapers \u0026 culture","Influential metropolis known for the Statue of Liberty, Empire State Building \u0026 Times Square.","NYC"],[40.7127753,-74.0059728],"US",null,"United States"],[["LIM",0],"New Jorge Chávez International Airport",["/m/0lpfh","Lima",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTEtUnreFpY47ZyuGpKyyuUXxdu4-fNeyFjjAQxzmRlO-2yTAr7QR6txl0_bpdD4WNOMNnMVXsEMHOdh7iU-JhOZ3SLpg1oPfPdPyLGz5g"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcSfj6UMMOtH7UfdiBBAwDzl9eZfkmq2MSdmuiXiTlDf8DzzkasO79cO5jXlUEqfqycQTQd3-RTmn4H9FQ"]]],[-12.021944,-77.114444],"PE",0,"Peru"],[["/m/0lpfh",4],"Lima",["/m/0lpfh","Lima",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcTEtUnreFpY47ZyuGpKyyuUXxdu4-fNeyFjjAQxzmRlO-2yTAr7QR6txl0_bpdD4WNOMNnMVXsEMHOdh7iU-JhOZ3SLpg1oPfPdPyLGz5g"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcSfj6UMMOtH7UfdiBBAwDzl9eZfkmq2MSdmuiXiTlDf8DzzkasO79cO5jXlUEqfqycQTQd3-RTmn4H9FQ"]],"Museo Larco art \u0026 colonial architecture","Peru's bustling capital, with Spanish colonial buildings, Museo Larco art \u0026 a vibrant food scene.","LIM"],[-12.0466888,-77.0430886],"PE",null,"Peru"],[["MIA",0],"Miami International Airport",["/m/0f2v0","Miami",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRScvUK_JtYRXmQWoXHiT98Ajl1KTuUVO40d0Q678OpK1xyyWI8VIkHqzXE9BHfY5R35UpgbeEdcf1IhMDncXwDo29wOABY9MIUzCFLkwU"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRjsG6ybk9C2oSVnPZUal-6l7EimKLf5gtMAhOumgD16nXBwB4X0lHH3nh-178HKbonabZtnDMdZKfDEQ"]]],[25.7952778,-80.29],"US",0,"United States"],[["/m/0f2v0",4],"Miami",["/m/0f2v0","Miami",[["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRScvUK_JtYRXmQWoXHiT98Ajl1KTuUVO40d0Q678OpK1xyyWI8VIkHqzXE9BHfY5R35UpgbeEdcf1IhMDncXwDo29wOABY9MIUzCFLkwU"],["https://encrypted-tbn2.gstatic.com/images?q\u003dtbn:ANd9GcRjsG6ybk9C2oSVnPZUal-6l7EimKLf5gtMAhOumgD16nXBwB4X0lHH3nh-178HKbonabZtnDMdZKfDEQ"]],"South Beach, art deco \u0026 Little Havana","Stylish Florida city known for South Beach, art deco architecture, contemporary art \u0026 Little Havana.","MIA"],[25.7616798,-80.1917902],"US",null,"United States"],[["MSP",0],"Minneapolis-Saint Paul International Airport",["/m/0fpzwf","Minneapolis",[["https://encrypted-tbn0.gstatic.com/licensed-image?q\u003dtbn:ANd9GcS18l-MIiviXNwsa5xDBa53l0nJt9vYGCSLZulnf8-9564mvmtWTERdz3Hy4zqw2lEmTmzdgbZNvVqaNvolKy1Ic3tPvWyOqxQPaC5QZic"],["https://encrypted-tbn0.gstatic.com/licensed-image?q\u003dtbn:ANd9GcTHyTIt8YoIyGG4VbcJ8ySdQHCnNpobtF_T7fDkKgLhEEp_tm7DVlyQh6EELxcCEklGSgVes9VpGWOWCtCSRANvzUM_ep37ObvM0xeGmJE"]]],[44.8819444,-93.221667],"US",0,"United States"],[["/m/0fpzwf",4],"Minneapolis",["/m/0fpzwf","Minneapolis",[["https://encrypted-tbn0.gstatic.com/licensed-image?q\u003dtbn:ANd9GcS18l-MIiviXNwsa5xDBa53l0nJt9vYGCSLZulnf8-9564mvmtWTERdz3Hy4zqw2lEmTmzdgbZNvVqaNvolKy1Ic3tPvWyOqxQPaC5QZic"],["https://encrypted-tbn0.gstatic.com/licensed-image?q\u003dtbn:ANd9GcTHyTIt8YoIyGG4VbcJ8ySdQHCnNpobtF_T7fDkKgLhEEp_tm7DVlyQh6EELxcCEklGSgVes9VpGWOWCtCSRANvzUM_ep37ObvM0xeGmJE"]],"Twin City known for Chain of Lakes \u0026 art","Set along the Chain of Lakes, this Twin City in Minnesota offers many art museums \u0026 cultural sites.","MSP"],[44.977753,-93.2650108],"US",null,"United States"],[["NYC",0],"Metropolitan Area",["/m/02_286","New York",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQEaUa9NsdPWGpAUGkTApkZDT_4M6_6V8wTcC0v1b1wJAJX-BuMSiipXbsoznGgcI1xLOc5QiTcR_xovexgjdOz0gqQe0tRQ9h0bUkZ07Q"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcRa1dwH1NZQk4dsbPiyA9Vrq2RX75jXSZ-OkHn7NkLHl-11HercqDXoZ4p2cDxJkH6vca2degawrCzHEQ"]]],[40.7127837,-74.0059413],"US",0,"United States"],[["PHL",0],"Philadelphia International Airport",["/m/0dclg","Philadelphia",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQcbg0MnkfnE9eUvuKJHou5Caj1zXMtLuK1wucPijlSVZHg0_DCECdu7dBehpeDVmqlVsZG-V2pdNwIiNJRUy3jQZDrURZJmdChItPVIzE"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcSvvZz4z_jCKaFlTmcR9EOv7ERVk2fCwtz7mkp5JOMIEQyrifb8NStFsoeGEIOCcSh8SSzlee2du3hn4A"]]],[39.8722222,-75.240833],"US",0,"United States"],[["/m/0dclg",4],"Philadelphia",["/m/0dclg","Philadelphia",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcQcbg0MnkfnE9eUvuKJHou5Caj1zXMtLuK1wucPijlSVZHg0_DCECdu7dBehpeDVmqlVsZG-V2pdNwIiNJRUy3jQZDrURZJmdChItPVIzE"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcSvvZz4z_jCKaFlTmcR9EOv7ERVk2fCwtz7mkp5JOMIEQyrifb8NStFsoeGEIOCcSh8SSzlee2du3hn4A"]],"Liberty Bell \u0026 Independence Hall","Pennsylvania city with a Revolutionary War history on view at the Liberty Bell \u0026 Independence Hall.","PHL"],[39.9525839,-75.1652215],"US",null,"United States"],[["PMC",0],"Aeropuerto El Tepual",["/m/03fxkl","Puerto Montt",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRORwEeMxi4KrNjFXknRPgTiiipVv76ScHe5CbiWC1kTFKY2vKFG7MLWOUuyeD2rF6WaRGGC9uU3txX7glRYM-UpYw5-QYJqbBTizRB-zo"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRqwbGgcYEeQq1e-wWMkVRLV2oiaiSXvpXSTUIlJPj-7lfi1nPGV1NQKwl90T0dz5GfUQbgdWChTh6xsw"]]],[-41.438889,-73.093889],"CL",0,"Chile"],[["/m/03fxkl",4],"Puerto Montt",["/m/03fxkl","Puerto Montt",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRORwEeMxi4KrNjFXknRPgTiiipVv76ScHe5CbiWC1kTFKY2vKFG7MLWOUuyeD2rF6WaRGGC9uU3txX7glRYM-UpYw5-QYJqbBTizRB-zo"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRqwbGgcYEeQq1e-wWMkVRLV2oiaiSXvpXSTUIlJPj-7lfi1nPGV1NQKwl90T0dz5GfUQbgdWChTh6xsw"]],"Lake District town by Andes \u0026 fjords ","Port city in southern Chile’s Lake District, with access to the Andes \u0026 the Patagonian fjords.","PMC"],[-41.4693622,-72.9424405],"CL",null,"Chile"],[["PUQ",0],"Punta Arenas C.Ibanez del Campo",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]]],[-53.003611,-70.853611],"CL",0,"Chile"],[["/m/02n5vc",4],"Punta Arenas",["/m/02n5vc","Punta Arenas",[["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcS5MOHTjUyxdV_uyg_Gmgg2xzsGsGcmAoYteDUzZwZSbGk8cyY1lJ0xD64jE0dYROD1WjlBGdaTpeKN-0DC1w-09z-2nZ2JYgSxQwiq-Nc"],["https://encrypted-tbn1.gstatic.com/images?q\u003dtbn:ANd9GcTZvJWdm36VlwnfsDFDiQDwfeIoo--HEFCH2VXar7m25B4Jg7UWROTOQaTgjLfFRzRg56H7nTmsVdY6-Q"]],"Strait of Magellan city \u0026 travel base ","Chilean city on the Strait of Magellan often used as a base for exploring Patagonia or Antarctica.","PUQ"],[-53.1633778,-70.907705],"CL",null,"Chile"],[["SCL",0],"Arturo Merino Benitez International Airport",["/m/0dlqv","Santiago",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRu8XbKo--iOQm3xQMbMlH3CvyC0_8ugOijIGErV6oc-P-94_9SCS4cCukIHsMudloel-9wvxUwcEtdupw_blbMqnBZHsdfxRBlxceNOVE"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQpDde4uka4doBsXbshQy4M_6et9NZ4XeEv9aoG8YinL-iQ73D-8RN_FUnvMZnHG6E-HkyVkW8_FQyAAA"]]],[-33.394444,-70.793889],"CL",0,"Chile"],[["/m/0dlqv",4],"Santiago",["/m/0dlqv","Santiago",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcRu8XbKo--iOQm3xQMbMlH3CvyC0_8ugOijIGErV6oc-P-94_9SCS4cCukIHsMudloel-9wvxUwcEtdupw_blbMqnBZHsdfxRBlxceNOVE"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcQpDde4uka4doBsXbshQy4M_6et9NZ4XeEv9aoG8YinL-iQ73D-8RN_FUnvMZnHG6E-HkyVkW8_FQyAAA"]],"Plaza de Armas \u0026 Parque Metropolitano","Chilean capital, surrounded by mountains, home to the Plaza de Armas \u0026 Parque Metropolitano.","SCL"],[-33.4488897,-70.6692655],"CL",null,"Chile"],[["UIO",0],"Mariscal Sucre Quito International Airport",["/m/01dtq1","Quito",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcSvq2xdpNsZKOjStbk2eS1sPVDieiGwkoMJR3_1WzTnNDMRRY1oQK46KJwVsYCHIKkGtzEe-VxHKCQtkXiiH1AMQnCcelh735XK2G1fWBg"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcR7-6mnFW1sTp-c08MXAHZNJbgh_ILgIwBBWxTvzIC5ZoTY5SDaFHNpa97oEMWeVFQszaJITiil6_C-wQ"]]],[-0.1133333,-78.358611],"EC",0,"Ecuador"],[["/m/01dtq1",4],"Quito",["/m/01dtq1","Quito",[["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcSvq2xdpNsZKOjStbk2eS1sPVDieiGwkoMJR3_1WzTnNDMRRY1oQK46KJwVsYCHIKkGtzEe-VxHKCQtkXiiH1AMQnCcelh735XK2G1fWBg"],["https://encrypted-tbn3.gstatic.com/images?q\u003dtbn:ANd9GcR7-6mnFW1sTp-c08MXAHZNJbgh_ILgIwBBWxTvzIC5ZoTY5SDaFHNpa97oEMWeVFQszaJITiil6_C-wQ"]],"Colonial buildings in Ecuador's capital","Ecuador’s capital, with colonial architecture, an Andean foothills setting \u0026 an altitude of 2,850m.","UIO"],[-0.2232523,-78.5141064],"EC",null,"Ecuador"]],null,null,null,null,null,1], sideChannel: {}});
```

- [ ] **Step 3: Write the failing test file `tests/sources/test_google_flights_pages.py`**

```python
"""Real Google Flights results scripts recorded 2026-10-18 (fast-flights 3.1).

PHL->PUQ: Google returned no itineraries at all, which fast-flights' parser crashes on
(TypeError: 'NoneType' object is not subscriptable). JFK->PUQ, same dates, has flights.
"""

from datetime import date
from pathlib import Path

import pytest

from ptopilot.sources.base import ExactQuery, SourceUnavailable
from ptopilot.sources.google_flights import GoogleFlightsSource, flights_from_script, parse_flights

FIXTURES = Path(__file__).parent / "fixtures"
EMPTY = (FIXTURES / "real_google_page_PHL_PUQ_2027-03-05_2027-03-14.js").read_text(encoding="utf-8")
FULL = (FIXTURES / "real_google_page_JFK_PUQ_2027-03-05_2027-03-14.js").read_text(encoding="utf-8")
QUERY = ExactQuery("PHL", "PUQ", date(2027, 3, 5), date(2027, 3, 14))


def test_a_page_with_no_itineraries_means_no_flights():
    assert flights_from_script(EMPTY) == []


def test_a_page_with_itineraries_still_parses():
    options = parse_flights(flights_from_script(FULL))
    assert options and all(o.price > 0 for o in options)


def raising(exc):
    def search(query):
        raise exc

    return search


@pytest.mark.parametrize("exc", [TypeError("'NoneType' object"), IndexError("x"), KeyError("k")])
def test_parse_errors_are_route_specific(exc):
    with pytest.raises(SourceUnavailable) as info:
        GoogleFlightsSource(search=raising(exc)).exact_search(QUERY)
    assert info.value.route_specific is True


@pytest.mark.parametrize("exc", [TimeoutError("timeout"), ConnectionError("reset"), RuntimeError("blocked")])
def test_outages_are_not_route_specific(exc):
    with pytest.raises(SourceUnavailable) as info:
        GoogleFlightsSource(search=raising(exc)).exact_search(QUERY)
    assert info.value.route_specific is False


def test_source_unavailable_defaults_to_an_outage():
    assert SourceUnavailable("serpapi: HTTP 500").route_specific is False
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/sources/test_google_flights_pages.py`

Expected: FAIL. Verified tail: `1 error in 0.44s`

- [ ] **Step 5: Write `ptopilot/sources/base.py` (full new contents)**

```python
"""Shared types for fare sources. Pipelines depend on these, never on a specific provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class SourceUnavailable(Exception):
    """A source failed (network, auth, quota, or unparseable response). Message carries a short snippet.

    route_specific: the failure is about this one route (e.g. a page the scraper can't read), not an
    outage, so it must not count toward the source's circuit breaker.
    """

    def __init__(self, message: str = "", route_specific: bool = False):
        super().__init__(message)
        self.route_specific = route_specific


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
    # Google's daily price history for these exact dates, (day, price), when the source has it (SerpApi)
    price_history: tuple[tuple[date, float], ...] = ()

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

- [ ] **Step 6: Write `ptopilot/sources/google_flights.py` (full new contents)**

```python
"""Live Google Flights prices via the unofficial `fast-flights` library. Free but fragile."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable

SEARCH_TIMEOUT_S = 60
# Errors raised while reading Google's page for one route: that route can't be parsed, Google isn't down.
ROUTE_ERRORS = (TypeError, IndexError, KeyError)


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


def flights_from_script(js: str) -> list[Any]:
    """Google's results script -> fast-flights results. A page with no itineraries at all (results slot
    null) is "no flights": fast-flights 3.1 crashes on it instead of returning an empty list."""
    from fast_flights.exceptions import FlightsNotFound
    from fast_flights.parser import parse_js

    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if not data.endswith("errorHasStatus: true"):
        payload = json.loads(data)
        if len(payload) <= 3 or payload[3] is None:
            return []
    try:
        return list(parse_js(js))
    except FlightsNotFound:
        return []


def _default_search(query: ExactQuery) -> tuple[Sequence[Any], str]:
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights.fetcher import fetch_flights_html
    from selectolax.lexbor import LexborHTMLParser

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
    script = LexborHTMLParser(fetch_flights_html(q)).css_first(r"script.ds\:1")
    if script is None:
        raise RuntimeError("no results script in the Google Flights page")
    return flights_from_script(script.text()), q.url()


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
            message = f"google_flights: {type(exc).__name__}: {exc}"
            raise SourceUnavailable(message, route_specific=isinstance(exc, ROUTE_ERRORS)) from exc
        return ExactResult(
            source=self.name, query=query, currency=query.currency, options=options, deep_link=url
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/sources/test_google_flights_pages.py`

Expected: PASS. Verified tail: `9 passed in 0.29s`

- [ ] **Step 8: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `456 passed, 1 deselected, 1 warning in 70.34s (0:01:10)`; ruff reports nothing.

- [ ] **Step 9: Commit and push**

```bash
git add -A
git commit -m "fix(sources): no-itinerary Google pages are no flights; parse failures are route-specific

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 3: Route-specific failures don't trip the breaker

On 2026-10-18, three PHL→PUQ trips in a row tripped the Google breaker and switched Google off for every remaining route. In `live_verify`, a route-specific failure is recorded and counted as `<source>_route_failed`. It neither increments nor resets the breaker, and the fallback is still tried. The store and record helpers become public so Task 4 can reuse them.

**Files:**
- Modify: `ptopilot/pipeline/live_verify.py`
- Create: `tests/pipeline/test_route_failures.py`

**Interfaces:**
- Consumes: Task 2 `SourceUnavailable.route_specific`.
- Produces: `live_verify.store_options(ctx, rq, result) -> int` (was `_store`); `live_verify.record_check(ctx, rq, source, ok, options=0, error=None)` (was `_record`); count key `<source>_route_failed`.

- [ ] **Step 1: Write the failing test file `tests/pipeline/test_route_failures.py`**

```python
"""A route Google can't parse is that route's problem: it must not switch Google off for everyone else."""

import pytest

from ptopilot.pipeline import expand, live_verify, shortlist
from ptopilot.pipeline.context import StageFailed
from ptopilot.sources.base import SourceUnavailable
from tests.pipeline.conftest import FakeLiveSource, add_tracker, add_user, answering, option


def shortlisted(make_ctx, **ctx_fields):
    ctx = make_ctx(**ctx_fields)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)  # no history -> 6 exploration entries
    return ctx


def route_failing(query):
    raise SourceUnavailable("google_flights: TypeError: 'NoneType' object", route_specific=True)


def test_route_specific_failures_never_trip_the_breaker(make_ctx):
    google = FakeLiveSource("google_flights", route_failing)
    ctx = shortlisted(make_ctx, live_sources=[google])
    with pytest.raises(StageFailed):  # nothing priced at all is still a failed stage
        live_verify.run(ctx)
    assert len(google.calls) == 6  # but every route was tried: the breaker never tripped


def test_route_specific_failures_are_counted_separately(make_ctx):
    google = FakeLiveSource("google_flights", route_failing)
    fallback = FakeLiveSource("serpapi", answering(option(700), source="serpapi"))
    counts = live_verify.run(shortlisted(make_ctx, live_sources=[google, fallback]))
    assert counts["google_flights_route_failed"] == 6
    assert "google_flights_failed" not in counts and "google_flights_breaker_tripped" not in counts
    assert counts["serpapi_ok"] == 6  # the fallback still prices each route


def test_route_failures_neither_count_toward_nor_reset_the_breaker(make_ctx):
    outcomes = iter(["outage", "route", "outage", "outage", "ok", "ok"])

    def flaky(query):
        kind = next(outcomes)
        if kind == "outage":
            raise SourceUnavailable("google_flights: HTTP 429")
        if kind == "route":
            raise SourceUnavailable("google_flights: IndexError", route_specific=True)
        return answering(option(700))(query)

    google = FakeLiveSource("google_flights", flaky)
    with pytest.raises(StageFailed, match="'google_flights_breaker_tripped': 1"):
        live_verify.run(shortlisted(make_ctx, live_sources=[google]))
    # outage, route (ignored), outage, outage -> three outages in a row trip the breaker on call 4
    assert len(google.calls) == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_route_failures.py`

Expected: FAIL. Verified tail: `3 failed in 2.86s`

- [ ] **Step 3: Write `ptopilot/pipeline/live_verify.py` (full new contents)**

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

    def remaining_today(self, source: str) -> int | None:
        """Calls this source may still make today (None = unbudgeted)."""
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return None
        left = min(
            caps["per_day"] - self.used_today(source), caps["per_month"] - self.used_this_month(source)
        )
        return max(left, 0)

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


def store_options(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    """Store every option of a live result as a verified observation of this route query."""
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


def record_check(
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
    # Open-jaw routes can only be priced by budgeted SerpApi, so round-trip fallbacks never spend
    # the calls those routes still need.
    pending_open_jaw = sum(
        1 for rq in entries if rq.id not in checked and rq.return_airport != rq.dest_airport
    )
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
        if query.open_jaw:
            pending_open_jaw -= 1
        capable = [src for src in usable if src.supports_open_jaw or not query.open_jaw]
        if not capable:  # e.g. open-jaw with SerpApi unconfigured or out of budget for today
            counts["no_open_jaw_source"] += 1
            continue
        for src in capable:
            if not budget.allows(src.name):
                disabled.add(src.name)
                counts[f"{src.name}_budget_exhausted"] += 1
                continue
            if not query.open_jaw and src.supports_open_jaw and pending_open_jaw:
                left = budget.remaining_today(src.name)
                if left is not None and left <= pending_open_jaw:
                    counts[f"{src.name}_reserved_for_open_jaw"] += 1
                    continue
            budget.charge(src.name)
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
                record_check(ctx, rq, src.name, ok=False, error=str(exc))
                log.warning("%s failed for %s: %s", src.name, query, exc)
                if exc.route_specific:  # this route's problem, not an outage: leave the breaker alone
                    counts[f"{src.name}_route_failed"] += 1
                    continue
                counts[f"{src.name}_failed"] += 1
                consecutive_failures[src.name] += 1
                if consecutive_failures[src.name] >= config.BREAKER_THRESHOLD:
                    disabled.add(src.name)
                    counts[f"{src.name}_breaker_tripped"] += 1
                continue
            consecutive_failures[src.name] = 0
            counts[f"{src.name}_ok"] += 1
            counts["options_stored"] += store_options(ctx, rq, result)
            record_check(ctx, rq, src.name, ok=True, options=len(result.options))
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_route_failures.py`

Expected: PASS. Verified tail: `3 passed in 2.44s`

- [ ] **Step 5: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `459 passed, 1 deselected, 1 warning in 71.27s (0:01:11)`; ruff reports nothing.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "fix(pipeline): route-specific failures don't trip the breaker; share store/record helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 4: The seed_history stage

The core of this plan, spec §2:
- One SerpApi call per round-trip baseline key that isn't confident yet stores Google's ~60 daily prices as unverified `google_history` observations, each on its own day. The next `baselines` run then has a confident baseline.
- The stage runs after `shortlist` and before `live_verify`, and leaves 2 SerpApi calls a day for open-jaw routes.
- `live_verify` also keeps history from SerpApi fallbacks.
- `cached_prices` ignores history, so it never becomes a price shown to a user.

**Files:**
- Modify: `ptopilot/config.py`
- Modify: `ptopilot/pipeline/live_verify.py`
- Modify: `ptopilot/pipeline/queries.py`
- Modify: `ptopilot/pipeline/runner.py`
- Create: `ptopilot/pipeline/seed_history.py`
- Modify: `ptopilot/sources/serpapi.py`
- Modify: `tests/pipeline/test_runner.py`
- Create: `tests/pipeline/test_seed_history.py`

**Interfaces:**
- Consumes: Task 1 `ExactResult.price_history`; Task 2 `SourceUnavailable.route_specific`; Task 3 `store_options`, `record_check`; `Budget` (existing).
- Produces: `ptopilot.pipeline.seed_history.run(ctx)`; `live_verify.store_history(ctx, rq, result) -> int`; `SerpApiSource.provides_history = True`; config `HISTORY_SOURCE = "google_history"`, `SEED_RESERVE_FOR_OPEN_JAW = 2`, `SEED_RETRY_DAYS = 30`; runner stage order expand → broad_scan → shortlist → seed_history → live_verify → baselines → score, and `seed_history` is in `CONTINUE_ON_FAILURE`.

> `tests/pipeline/test_runner.py` changes because the stage list now includes `seed_history`. It's `skipped` in those tests, since no fake source provides history.

- [ ] **Step 1: Update the test file `tests/pipeline/test_runner.py` (full new contents)**

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
        ("seed_history", "skipped"),  # no history source among the fakes
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
    assert [r.status for r in results] == ["ok", "failed"] + ["not_run"] * 5
    assert runs(make_ctx().engine)["broad_scan"].error == "all month scans failed"


def test_live_verify_failure_lets_scoring_continue(make_ctx):
    ctx = make_ctx(live_sources=[FakeLiveSource("google_flights", failing())])
    add_tracker(ctx.engine, add_user(ctx.engine))
    statuses = {r.stage: r.status for r in runner.run_pipeline(ctx)}
    assert statuses == {
        "expand": "ok",
        "broad_scan": "skipped",
        "shortlist": "ok",
        "seed_history": "skipped",
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

- [ ] **Step 2: Write the failing test file `tests/pipeline/test_seed_history.py`**

```python
"""Stage `seed_history`: one SerpApi call per baseline key gives it ~60 days of Google's price history."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import LiveCheck, PriceObservation, RouteBaseline, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, expand, live_verify, seed_history, shortlist
from ptopilot.pipeline.context import StageSkipped
from ptopilot.pipeline.queries import cached_prices, rq_baseline_key, todays_route_queries
from ptopilot.sources.base import ExactResult, SourceUnavailable
from tests.pipeline.conftest import RUN, FakeLiveSource, add_tracker, add_user, answering, failing, option


def history(days=30, price=1000.0, end=RUN):
    return tuple((end - timedelta(days=i), price + (i % 5) * 10) for i in range(days))


def with_history(points):
    def respond(q):
        return ExactResult("serpapi", q, "USD", (option(990),), "https://serp.example/x", (900, 1100), points)

    return respond


def serpapi(respond):
    src = FakeLiveSource("serpapi", respond)
    src.provides_history = True
    return src


MAY_AND_JUNE = ((date(2027, 5, 1), date(2027, 5, 31)), (date(2027, 6, 1), date(2027, 6, 30)))


def expanded(make_ctx, **ctx_fields):
    """Lisbon and Madeira trackers over May and June: several baseline keys (route x month x length)."""
    ctx = make_ctx(**ctx_fields)
    user = add_user(ctx.engine, windows=MAY_AND_JUNE)
    add_tracker(ctx.engine, user)
    add_tracker(ctx.engine, user, code="MADEIRA")
    expand.run(ctx)
    return ctx


def keys(ctx):
    with session_scope(ctx.engine) as s:
        groups = defaultdict(list)
        for rq in todays_route_queries(s, ctx.run_date):
            groups[rq_baseline_key(rq)].append((rq.depart_date, rq.id))
        return {k: sorted(v) for k, v in groups.items()}


def history_rows(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(PriceObservation).where(PriceObservation.source == "google_history")))


def test_skipped_without_a_source_that_provides_history(make_ctx):
    ctx = expanded(make_ctx, live_sources=[FakeLiveSource("google_flights", answering(option(700)))])
    with pytest.raises(StageSkipped):
        seed_history.run(ctx)


def test_one_call_per_key_on_its_earliest_trip(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = expanded(make_ctx, live_sources=[src])
    wanted = keys(ctx)
    counts = seed_history.run(ctx)
    assert counts["keys_needing_seed"] == len(wanted) == counts["seeded"] == len(src.calls)
    assert {(q.depart_date) for q in src.calls} == {trips[0][0] for trips in wanted.values()}


def test_history_points_are_stored_unverified_on_their_own_dates(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 3, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history(days=5)))])
    counts = seed_history.run(ctx)  # 3 a day, 2 kept for open-jaw: one call
    assert counts["seeded"] == 1 and counts["points_stored"] == 5 and counts["options_stored"] == 1
    rows = history_rows(ctx.engine)
    assert sorted(r.observed_at for r in rows) == [
        datetime.combine(RUN - timedelta(days=i), time(12), UTC) for i in range(4, -1, -1)
    ]
    assert all(not r.verified and r.carrier is None and r.deep_link is None for r in rows)
    with session_scope(ctx.engine) as s:
        live = s.scalars(select(PriceObservation).where(PriceObservation.verified.is_(True))).all()
        checks = s.scalars(select(LiveCheck)).all()
    assert [r.price for r in live] == [990] and [(c.source, c.ok, c.options) for c in checks] == [
        ("serpapi", True, 1)
    ]


def test_points_outside_the_baseline_window_are_dropped(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 3, "per_month": 250})
    old = ((RUN - timedelta(days=config.BASELINE_WINDOW_DAYS + 1), 500.0),)
    future = ((RUN + timedelta(days=1), 500.0),)
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(old + history(days=3) + future))])
    assert seed_history.run(ctx)["points_stored"] == 3


def test_a_seeded_key_reaches_normal_confidence(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history(days=30)))])
    seed_history.run(ctx)
    baselines.run(ctx)
    with session_scope(ctx.engine) as s:
        confidences = {b.confidence for b in s.scalars(select(RouteBaseline))}
    assert confidences == {"normal"}


def test_seeding_keeps_two_calls_a_day_for_open_jaw(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 4, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = expanded(make_ctx, live_sources=[src])
    counts = seed_history.run(ctx)
    assert len(src.calls) == 2 and counts["budget_exhausted"] == counts["keys_needing_seed"] - 2


def add_confident_baseline(engine, key):
    origin, dest, ret, month, bucket = key
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin=origin, dest_airport=dest, return_airport=ret, month=month, length_bucket=bucket,
                median=1000, sigma=50, n=20, confidence="normal",
            )
        )  # fmt: skip


def add_history_point(engine, rq_id, days_ago=10):
    with session_scope(engine) as s:
        rq = s.get(RouteQuery, rq_id)
        s.add(
            PriceObservation(
                origin=rq.origin, dest_airport=rq.dest_airport, return_airport=rq.return_airport,
                depart_date=rq.depart_date, return_date=rq.return_date, month=rq.depart_date.replace(day=1),
                source="google_history", price=1000, currency="USD", verified=False,
                observed_at=datetime.combine(RUN - timedelta(days=days_ago), time(12), UTC),
            )
        )  # fmt: skip


def add_serpapi_check(engine, rq_id, days_ago):
    with session_scope(engine) as s:
        s.add(
            LiveCheck(
                run_date=RUN - timedelta(days=days_ago),
                route_query_id=rq_id,
                source="serpapi",
                ok=True,
                options=0,
            )
        )


def test_confident_seeded_and_recently_tried_keys_are_skipped(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = expanded(make_ctx, live_sources=[src])
    all_keys = list(keys(ctx).items())
    (confident, _), (_, seeded_trips), (_, tried_trips) = all_keys[:3]
    add_confident_baseline(ctx.engine, confident)
    add_history_point(ctx.engine, seeded_trips[-1][1])  # any trip of the key counts
    add_serpapi_check(ctx.engine, tried_trips[0][1], days_ago=5)
    counts = seed_history.run(ctx)
    assert counts["keys_needing_seed"] == len(all_keys) - 3 == len(src.calls)


def test_history_older_than_the_window_does_not_count_as_seeded(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history()))])
    all_keys = keys(ctx)
    for trips in all_keys.values():
        add_history_point(ctx.engine, trips[0][1], days_ago=config.BASELINE_WINDOW_DAYS + 1)
    assert seed_history.run(ctx)["keys_needing_seed"] == len(all_keys)


def test_a_key_tried_without_history_is_retried_after_30_days(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history()))])
    all_keys = keys(ctx)
    for trips in all_keys.values():
        add_serpapi_check(ctx.engine, trips[0][1], days_ago=config.SEED_RETRY_DAYS)
    assert seed_history.run(ctx)["keys_needing_seed"] == len(all_keys)


def test_open_jaw_and_far_routes_are_not_seeded(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(history()))
    ctx = make_ctx(live_sources=[src])
    far = (date(2028, 3, 1), date(2028, 3, 31))  # well past the live horizon
    user = add_user(ctx.engine, home_airport="JFK", windows=((date(2027, 6, 1), date(2027, 6, 30)), far))
    add_tracker(ctx.engine, user, code="CAMINO_PORTUGUES", min_stay=11, max_stay=14)
    add_tracker(ctx.engine, user, code="LIS")
    expand.run(ctx)
    seed_history.run(ctx)
    assert src.calls and all(q.dest_airport == "LIS" and not q.open_jaw for q in src.calls)
    assert all((q.depart_date - RUN).days <= config.LIVE_HORIZON_DAYS for q in src.calls)


def test_a_same_day_rerun_makes_no_new_calls(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(with_history(()))  # no history: keys stay unseeded, but count as tried
    ctx = expanded(make_ctx, live_sources=[src])
    first = seed_history.run(ctx)
    calls = len(src.calls)
    assert first["no_history"] == calls > 0
    assert seed_history.run(ctx)["keys_needing_seed"] == 0 and len(src.calls) == calls


def test_three_failures_in_a_row_stop_the_stage(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    src = serpapi(failing("HTTP 500"))
    counts = seed_history.run(expanded(make_ctx, live_sources=[src]))
    assert len(src.calls) == 3 and counts["serpapi_failed"] == 3 and counts["breaker_tripped"] == 1


def test_route_specific_failures_do_not_stop_the_stage(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})

    def route_failing(q):
        raise SourceUnavailable("serpapi: odd payload", route_specific=True)

    src = serpapi(route_failing)
    ctx = expanded(make_ctx, live_sources=[src])
    assert seed_history.run(ctx)["serpapi_failed"] == len(src.calls) == len(keys(ctx))


def test_history_never_becomes_a_cached_price(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    ctx = expanded(make_ctx, live_sources=[serpapi(with_history(history()))])
    seed_history.run(ctx)
    with session_scope(ctx.engine) as s:
        exact, monthly = cached_prices(s, todays_route_queries(s, RUN), RUN)
    assert exact == {} and monthly == {}


def test_live_verify_fallbacks_keep_history_too(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 50, "per_month": 250})
    google = FakeLiveSource("google_flights", failing("429"))
    ctx = expanded(make_ctx, live_sources=[google, serpapi(with_history(history(days=4)))])
    shortlist.run(ctx)
    counts = live_verify.run(ctx)
    assert counts["serpapi_ok"] > 0 and len(history_rows(ctx.engine)) == 4 * counts["serpapi_ok"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_seed_history.py tests/pipeline/test_runner.py`

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
# History seeding (V2): Google's own daily prices from SerpApi round-trip results seed baselines.
HISTORY_SOURCE = "google_history"  # observations source for those points; never a price shown to users
SEED_RESERVE_FOR_OPEN_JAW = 2  # SerpApi calls per day seeding leaves for open-jaw routes
SEED_RETRY_DAYS = 30  # a key whose SerpApi result had no history is tried again after this many days

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
MIN_TREND_POINTS = 3  # the destination page draws a price trend from this many scan days
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
```

- [ ] **Step 5: Write `ptopilot/pipeline/live_verify.py` (full new contents)**

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
from datetime import UTC, datetime, time, timedelta
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

    def remaining_today(self, source: str) -> int | None:
        """Calls this source may still make today (None = unbudgeted)."""
        caps = config.SOURCE_BUDGETS.get(source)
        if caps is None:
            return None
        left = min(
            caps["per_day"] - self.used_today(source), caps["per_month"] - self.used_this_month(source)
        )
        return max(left, 0)

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


def store_options(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    """Store every option of a live result as a verified observation of this route query."""
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


def store_history(ctx: RunContext, rq: RouteQuery, result: ExactResult) -> int:
    """Store Google's daily price history (SerpApi) for this route query, each point on its own day.

    Unverified and under HISTORY_SOURCE, so it feeds baselines but never becomes a price a user sees.
    Points outside the trailing baseline window (or after the run date) are dropped."""
    first = ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS)
    points = [(day, price) for day, price in result.price_history if first <= day <= ctx.run_date]
    with session_scope(ctx.engine) as s:
        s.add_all(
            PriceObservation(
                origin=rq.origin,
                dest_airport=rq.dest_airport,
                return_airport=rq.return_airport,
                depart_date=rq.depart_date,
                return_date=rq.return_date,
                month=month_of(rq.depart_date),
                source=config.HISTORY_SOURCE,
                price=Decimal(str(price)),
                currency=result.currency,
                verified=False,
                observed_at=datetime.combine(day, time(12), UTC),
            )
            for day, price in points
        )
    return len(points)


def record_check(
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
    # Open-jaw routes can only be priced by budgeted SerpApi, so round-trip fallbacks never spend
    # the calls those routes still need.
    pending_open_jaw = sum(
        1 for rq in entries if rq.id not in checked and rq.return_airport != rq.dest_airport
    )
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
        if query.open_jaw:
            pending_open_jaw -= 1
        capable = [src for src in usable if src.supports_open_jaw or not query.open_jaw]
        if not capable:  # e.g. open-jaw with SerpApi unconfigured or out of budget for today
            counts["no_open_jaw_source"] += 1
            continue
        for src in capable:
            if not budget.allows(src.name):
                disabled.add(src.name)
                counts[f"{src.name}_budget_exhausted"] += 1
                continue
            if not query.open_jaw and src.supports_open_jaw and pending_open_jaw:
                left = budget.remaining_today(src.name)
                if left is not None and left <= pending_open_jaw:
                    counts[f"{src.name}_reserved_for_open_jaw"] += 1
                    continue
            budget.charge(src.name)
            try:
                result = src.exact_search(query)
            except SourceUnavailable as exc:
                record_check(ctx, rq, src.name, ok=False, error=str(exc))
                log.warning("%s failed for %s: %s", src.name, query, exc)
                if exc.route_specific:  # this route's problem, not an outage: leave the breaker alone
                    counts[f"{src.name}_route_failed"] += 1
                    continue
                counts[f"{src.name}_failed"] += 1
                consecutive_failures[src.name] += 1
                if consecutive_failures[src.name] >= config.BREAKER_THRESHOLD:
                    disabled.add(src.name)
                    counts[f"{src.name}_breaker_tripped"] += 1
                continue
            consecutive_failures[src.name] = 0
            counts[f"{src.name}_ok"] += 1
            counts["options_stored"] += store_options(ctx, rq, result)
            counts["history_points_stored"] += store_history(ctx, rq, result)
            record_check(ctx, rq, src.name, ok=True, options=len(result.options))
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

- [ ] **Step 6: Write `ptopilot/pipeline/queries.py` (full new contents)**

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
            PriceObservation.source != config.HISTORY_SOURCE,  # history seeds baselines, never prices
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

- [ ] **Step 7: Write `ptopilot/pipeline/runner.py` (full new contents)**

```python
"""Runs stages in order, records each in pipeline_runs, and applies the failure rules (spec §10)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ptopilot.db.models import PipelineRun
from ptopilot.db.session import session_scope
from ptopilot.pipeline import baselines, broad_scan, expand, live_verify, score, seed_history, shortlist
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.sources.base import snippet

log = logging.getLogger(__name__)

STAGES: dict[str, Callable[[RunContext], dict[str, int]]] = {
    "expand": expand.run,
    "broad_scan": broad_scan.run,
    "shortlist": shortlist.run,
    "seed_history": seed_history.run,
    "live_verify": live_verify.run,
    "baselines": baselines.run,
    "score": score.run,
}
# A failure here still lets later stages run on whatever data exists (cached or unverified prices).
CONTINUE_ON_FAILURE = frozenset({"seed_history", "live_verify"})


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

- [ ] **Step 8: Write `ptopilot/pipeline/seed_history.py`**

```python
"""Stage `seed_history`: give baselines Google's own price history instead of weeks of waiting (V2 spec §2).

A SerpApi round-trip search returns ~60 days of Google's daily prices for the searched dates. One call per
baseline key (origin, airport, month, length bucket) that isn't confident yet stores that history, which
the `baselines` stage then uses like any other observation. Keys are skipped once seeded (history within the
baseline window), or for SEED_RETRY_DAYS after a SerpApi call on them returned no history. Open-jaw routes
(multi-city results carry no history) and departures beyond LIVE_HORIZON_DAYS are never seeded.

Runs before `live_verify` and leaves SEED_RESERVE_FOR_OPEN_JAW of the day's SerpApi calls for open-jaw
routes, which only SerpApi can price.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select

from ptopilot import config
from ptopilot.db.models import (
    LiveCheck,
    PriceObservation,
    RouteBaseline,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
)
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext, StageSkipped
from ptopilot.pipeline.live_verify import Budget, record_check, store_history, store_options
from ptopilot.pipeline.queries import (
    BaselineKey,
    baseline_key,
    rq_baseline_key,
    start_of,
    todays_route_queries,
)
from ptopilot.sources.base import ExactQuery, SourceUnavailable


def _keys_to_seed(ctx: RunContext) -> list[tuple[BaselineKey, RouteQuery]]:
    """Unseeded, not-yet-confident round-trip keys in the horizon, each with its representative trip."""
    since = start_of(ctx.run_date - timedelta(days=config.BASELINE_WINDOW_DAYS))
    with session_scope(ctx.engine) as s:
        rqs = [
            rq
            for rq in todays_route_queries(s, ctx.run_date)
            if rq.return_airport == rq.dest_airport
            and (rq.depart_date - ctx.run_date).days <= config.LIVE_HORIZON_DAYS
        ]
        confident = {
            (b.origin, b.dest_airport, b.return_airport, b.month, b.length_bucket)
            for b in s.scalars(select(RouteBaseline).where(RouteBaseline.confidence == "normal"))
        }
        seeded = {
            baseline_key(o.origin, o.dest_airport, o.return_airport, o.depart_date, o.return_date)
            for o in s.scalars(
                select(PriceObservation).where(
                    PriceObservation.source == config.HISTORY_SOURCE, PriceObservation.observed_at >= since
                )
            )
        }
        tried = set(
            s.scalars(
                select(LiveCheck.route_query_id).where(
                    LiveCheck.source == "serpapi",
                    LiveCheck.ok.is_(True),
                    LiveCheck.run_date > ctx.run_date - timedelta(days=config.SEED_RETRY_DAYS),
                )
            )
        )
        priority = dict(
            s.execute(
                select(TrackerRouteLink.route_query_id, func.min(Tracker.priority))
                .join(Tracker, Tracker.id == TrackerRouteLink.tracker_id)
                .where(TrackerRouteLink.run_date == ctx.run_date)
                .group_by(TrackerRouteLink.route_query_id)
            ).all()
        )
        s.expunge_all()
    by_key: defaultdict[BaselineKey, list[RouteQuery]] = defaultdict(list)
    for rq in rqs:
        by_key[rq_baseline_key(rq)].append(rq)
    picks = []
    for key, trips in by_key.items():
        if key in confident or key in seeded or any(rq.id in tried for rq in trips):
            continue
        rep = min(trips, key=lambda rq: (priority.get(rq.id, 2), rq.depart_date, rq.id))
        picks.append((key, rep))
    picks.sort(key=lambda kr: (priority.get(kr[1].id, 2), kr[1].depart_date, kr[0]))
    return picks


def run(ctx: RunContext) -> dict[str, int]:
    src = next((s for s in ctx.live_sources if getattr(s, "provides_history", False)), None)
    if src is None:
        raise StageSkipped("no live source provides Google price history (set SERPAPI_KEY)")
    counts: Counter[str] = Counter()
    picks = _keys_to_seed(ctx)
    counts["keys_needing_seed"] = len(picks)
    budget = Budget(ctx)
    left = budget.remaining_today(src.name)
    allowed = config.LIVE_CHECK_CAP if left is None else max(0, left - config.SEED_RESERVE_FOR_OPEN_JAW)
    failures = 0
    for i, (_, rq) in enumerate(picks):
        if allowed <= 0 or not budget.allows(src.name):
            counts["budget_exhausted"] = len(picks) - i
            break
        allowed -= 1
        budget.charge(src.name)
        query = ExactQuery(
            rq.origin, rq.dest_airport, rq.depart_date, rq.return_date, config.DEFAULT_CURRENCY
        )
        try:
            result = src.exact_search(query)
        except SourceUnavailable as exc:
            record_check(ctx, rq, src.name, ok=False, error=str(exc))
            counts[f"{src.name}_failed"] += 1
            if exc.route_specific:
                continue
            failures += 1
            if failures >= config.BREAKER_THRESHOLD:
                counts["breaker_tripped"] = 1
                break
            continue
        failures = 0
        counts["options_stored"] += store_options(ctx, rq, result)
        points = store_history(ctx, rq, result)
        counts["points_stored"] += points
        counts["seeded" if points else "no_history"] += 1
        record_check(ctx, rq, src.name, ok=True, options=len(result.options))
    return dict(counts)
```

- [ ] **Step 9: Write `ptopilot/sources/serpapi.py` (full new contents)**

```python
"""SerpApi Google Flights: quota-limited fallback that also returns Google's typical price range."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

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


def parse_price_history(insights: object) -> tuple[tuple[date, float], ...]:
    """price_insights.price_history, [[unix_ts, price], ...] -> ((UTC day, price), ...). Skips bad points."""
    raw = insights.get("price_history") if isinstance(insights, dict) else None
    if not isinstance(raw, list):
        return ()
    points = []
    for point in raw:
        if not (isinstance(point, list) and len(point) == 2):
            continue
        ts, price = point
        if isinstance(ts, bool) or isinstance(price, bool):
            continue
        if not (isinstance(ts, int | float) and isinstance(price, int | float)):
            continue
        points.append((datetime.fromtimestamp(ts, UTC).date(), float(price)))
    return tuple(points)


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
    insights = payload.get("price_insights") or {}
    typical = insights.get("typical_price_range")
    typical_range = (float(typical[0]), float(typical[1])) if typical and len(typical) == 2 else None
    url = (payload.get("search_metadata") or {}).get("google_flights_url", "")
    return ExactResult(
        source="serpapi",
        query=query,
        currency=query.currency,
        options=options,
        deep_link=url,
        typical_range=typical_range,
        price_history=parse_price_history(insights),
    )


class SerpApiSource:
    name = "serpapi"
    supports_open_jaw = True  # via type=3 multi-city searches
    provides_history = True  # round-trip results carry Google's daily price history

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

- [ ] **Step 10: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_seed_history.py tests/pipeline/test_runner.py`

Expected: PASS. Verified tail: `24 passed in 13.61s`

- [ ] **Step 11: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `474 passed, 1 deselected, 1 warning in 53.90s`; ruff reports nothing.

- [ ] **Step 12: Commit and push**

```bash
git add -A
git commit -m "feat(pipeline): seed baselines from Google's price history

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 5: Check every in-range route daily

About 28 in-range routes went unchecked each day under the 40-check cap. The cap becomes a safety ceiling of 150, and the scan job gets 75 minutes for ~140 paced checks.

**Files:**
- Modify: `.github/workflows/scan.yml`
- Modify: `ptopilot/config.py`
- Create: `tests/pipeline/test_coverage.py`

**Interfaces:**
- Consumes: `shortlist` (existing, unchanged logic).
- Produces: `config.LIVE_CHECK_CAP = 150`; `.github/workflows/scan.yml` `timeout-minutes: 75`.

- [ ] **Step 1: Write the failing test file `tests/pipeline/test_coverage.py`**

```python
"""Every in-range route gets a live check each day: the cap is a safety ceiling, not a daily ration."""

from datetime import date
from pathlib import Path

import yaml

from ptopilot import config
from ptopilot.db.models import ShortlistEntry
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, shortlist
from tests.pipeline.conftest import add_tracker, add_user

WINDOWS = tuple((date(2027, m, 1), date(2027, m, 28)) for m in (4, 5, 6, 7))
SCAN = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "scan.yml"


def test_more_than_forty_routes_are_all_shortlisted(make_ctx):
    ctx = make_ctx()
    user = add_user(ctx.engine, windows=WINDOWS)
    for code in ("LIS", "MADEIRA"):
        add_tracker(ctx.engine, user, code=code)
    expand.run(ctx)
    counts = shortlist.run(ctx)
    with session_scope(ctx.engine) as s:
        picked = s.query(ShortlistEntry).count()
    assert 40 < counts["candidates"] <= config.LIVE_CHECK_CAP
    assert picked == counts["candidates"] and counts["explore_overflow"] == 0


def test_the_cap_covers_a_full_year_of_trips():
    assert config.LIVE_CHECK_CAP >= 150


def test_the_scan_job_has_time_for_the_wider_checks():
    workflow = yaml.safe_load(SCAN.read_text(encoding="utf-8"))
    [job] = workflow["jobs"].values()
    assert job["timeout-minutes"] == 75
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_coverage.py`

Expected: FAIL. Verified tail: `3 failed in 2.35s`

- [ ] **Step 3: Write `.github/workflows/scan.yml` (full new contents)**

```
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
    timeout-minutes: 75  # ~140 paced live checks take 25-30 minutes
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
LIVE_CHECK_CAP = 150  # a safety ceiling: every in-range route is checked daily (~70-140 for one traveler)
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
# History seeding (V2): Google's own daily prices from SerpApi round-trip results seed baselines.
HISTORY_SOURCE = "google_history"  # observations source for those points; never a price shown to users
SEED_RESERVE_FOR_OPEN_JAW = 2  # SerpApi calls per day seeding leaves for open-jaw routes
SEED_RETRY_DAYS = 30  # a key whose SerpApi result had no history is tried again after this many days

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
MIN_TREND_POINTS = 3  # the destination page draws a price trend from this many scan days
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_coverage.py`

Expected: PASS. Verified tail: `3 passed in 1.86s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `477 passed, 1 deselected, 1 warning in 64.25s (0:01:04)`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(pipeline): check every in-range route daily (cap 150, scan timeout 75 min)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 6: fast-flights vs SerpApi audit

The health email compares each source's cheapest option on trips both priced the same day, for today and the last 30 days, spec §4. It needs no new table.

**Files:**
- Modify: `ptopilot/config.py`
- Modify: `ptopilot/pipeline/health.py`
- Create: `tests/pipeline/test_audit.py`

**Interfaces:**
- Consumes: `price_observations` (existing); `digest.render.date_range`.
- Produces: `ptopilot.pipeline.health.audit_lines(s, day) -> list[str]`; config `AUDIT_EQUAL_USD = 5`, `AUDIT_DAYS = 30`.

- [ ] **Step 1: Write the failing test file `tests/pipeline/test_audit.py`**

```python
"""The health email compares fast-flights with SerpApi on trips both priced the same day."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline.health import audit_lines, build_report
from ptopilot.pipeline.runner import StageResult
from tests.pipeline.conftest import RUN

TRIP = ("JFK", "PDL", date(2027, 3, 5), date(2027, 3, 14))
OTHER = ("JFK", "FNC", date(2027, 3, 12), date(2027, 3, 21))
THIRD = ("EWR", "PDL", date(2027, 3, 5), date(2027, 3, 15))


def priced(engine, trip, source, *prices, day=RUN):
    origin, dest, depart, ret = trip
    with session_scope(engine) as s:
        for price in prices:
            s.add(
                PriceObservation(
                    origin=origin, dest_airport=dest, return_airport=dest,
                    depart_date=depart, return_date=ret,
                    month=depart.replace(day=1), source=source, price=Decimal(price), currency="USD",
                    verified=True, observed_at=datetime.combine(day, time(9), UTC),
                )
            )  # fmt: skip


def lines(engine, day=RUN):
    with session_scope(engine) as s:
        return audit_lines(s, day)


def test_no_pairs_says_so(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 700)  # only one source priced it
    assert lines(clean_engine) == [
        "Audit (fast-flights vs SerpApi, today): no trips priced by both sources",
        "Audit, last 30 days: no trips priced by both sources",
    ]


def test_counts_cheaper_equal_and_pricier_using_each_sources_cheapest_option(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 760, 740)  # cheapest 740
    priced(clean_engine, TRIP, "serpapi", 603, 650)  # cheapest 603 -> fast-flights pricier by 137
    priced(clean_engine, OTHER, "google_flights", 828)
    priced(clean_engine, OTHER, "serpapi", 825)  # within $5 -> equal
    priced(clean_engine, THIRD, "google_flights", 600)
    priced(clean_engine, THIRD, "serpapi", 650)  # fast-flights cheaper
    today, month = lines(clean_engine)[:2]
    assert today == "Audit (fast-flights vs SerpApi, today): 3 trips, cheaper 1, equal 1, pricier 1"
    assert month == "  median gap +$3 (+0%), worst +$137 (+23%): JFK→PDL Mar 5–14 ($740 vs $603)"


def test_the_30_day_line_pools_earlier_days_and_ignores_older_ones(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 740, day=RUN - timedelta(days=3))
    priced(clean_engine, TRIP, "serpapi", 603, day=RUN - timedelta(days=3))
    priced(clean_engine, OTHER, "google_flights", 900, day=RUN - timedelta(days=30))  # outside the 30 days
    priced(clean_engine, OTHER, "serpapi", 800, day=RUN - timedelta(days=30))
    priced(clean_engine, TRIP, "google_flights", 700)
    priced(clean_engine, TRIP, "serpapi", 700)
    out = lines(clean_engine)
    assert out[0] == "Audit (fast-flights vs SerpApi, today): 1 trips, cheaper 0, equal 1, pricier 0"
    assert out[-1] == "Audit, last 30 days: 2 trips, cheaper 0, equal 1, pricier 1; median gap +$68 (+11%)"


def test_prices_on_different_days_are_not_paired(clean_engine):
    priced(clean_engine, TRIP, "google_flights", 740, day=RUN - timedelta(days=1))
    priced(clean_engine, TRIP, "serpapi", 603)
    assert lines(clean_engine)[-1] == "Audit, last 30 days: no trips priced by both sources"


def test_the_health_report_includes_the_audit(make_ctx):
    ctx = make_ctx()
    priced(ctx.engine, TRIP, "google_flights", 740)
    priced(ctx.engine, TRIP, "serpapi", 603)
    _, text = build_report(ctx, [StageResult("live_verify", "ok", {"google_flights_ok": 1})])
    assert "Audit (fast-flights vs SerpApi, today): 1 trips, cheaper 0, equal 0, pricier 1" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_audit.py`

Expected: FAIL. Verified tail: `1 error in 0.45s`

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
LIVE_CHECK_CAP = 150  # a safety ceiling: every in-range route is checked daily (~70-140 for one traveler)
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
# History seeding (V2): Google's own daily prices from SerpApi round-trip results seed baselines.
HISTORY_SOURCE = "google_history"  # observations source for those points; never a price shown to users
SEED_RESERVE_FOR_OPEN_JAW = 2  # SerpApi calls per day seeding leaves for open-jaw routes
SEED_RETRY_DAYS = 30
AUDIT_EQUAL_USD = 5  # fast-flights vs SerpApi prices this close count as equal in the health audit
AUDIT_DAYS = 30  # a key whose SerpApi result had no history is tried again after this many days

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
MIN_TREND_POINTS = 3  # the destination page draws a price trend from this many scan days
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
```

- [ ] **Step 4: Write `ptopilot/pipeline/health.py` (full new contents)**

```python
"""The admin health email sent after every scan (spec §10)."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Sequence
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.db.models import Candidate, PriceObservation, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.digest.render import date_range
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import month_of, start_of
from ptopilot.pipeline.runner import StageResult

AUDITED = ("google_flights", "serpapi")


def _pairs(s: Session, first: date, last: date) -> list[tuple[tuple, float, float]]:
    """(trip, fast-flights cheapest, SerpApi cheapest) for each trip both priced on the same day."""
    cheapest: dict[tuple, dict[str, float]] = {}
    rows = s.scalars(
        select(PriceObservation).where(
            PriceObservation.verified.is_(True),
            PriceObservation.source.in_(AUDITED),
            PriceObservation.observed_at >= start_of(first),
            PriceObservation.observed_at < start_of(last + timedelta(days=1)),
        )
    )
    for o in rows:
        key = (o.origin, o.dest_airport, o.depart_date, o.return_date, o.observed_at.date())
        by_source = cheapest.setdefault(key, {})
        by_source[o.source] = min(float(o.price), by_source.get(o.source, float("inf")))
    return [(key, p["google_flights"], p["serpapi"]) for key, p in cheapest.items() if len(p) == 2]


def _tally(pairs: list[tuple[tuple, float, float]]) -> str:
    gaps = [ff - serp for _, ff, serp in pairs]
    equal = sum(1 for g in gaps if abs(g) <= config.AUDIT_EQUAL_USD)
    pricier = sum(1 for g in gaps if g > config.AUDIT_EQUAL_USD)
    return f"{len(pairs)} trips, cheaper {len(pairs) - equal - pricier}, equal {equal}, pricier {pricier}"


def _signed(dollars: float, pct: float) -> str:
    """+$137 (+23%): positive means fast-flights was pricier."""
    sign = "-" if round(dollars) < 0 else "+"
    return f"{sign}${abs(dollars):,.0f} ({pct:+.0f}%)"


def _gap(pairs: list[tuple[tuple, float, float]]) -> str:
    gap = median(ff - serp for _, ff, serp in pairs)
    pct = median(100 * (ff - serp) / serp for _, ff, serp in pairs)
    return f"median gap {_signed(gap, pct)}"


def audit_lines(s: Session, day: date) -> list[str]:
    """fast-flights vs SerpApi on the same trips: today, and over the last AUDIT_DAYS days."""
    title = "Audit (fast-flights vs SerpApi, today)"
    today = _pairs(s, day, day)
    if not today:
        lines = [f"{title}: no trips priced by both sources"]
    else:
        (origin, dest, depart, ret, _), ff, serp = max(today, key=lambda p: p[1] - p[2])
        worst = _signed(ff - serp, 100 * (ff - serp) / serp)
        trip = f"{origin}→{dest} {date_range(depart, ret)} (${ff:,.0f} vs ${serp:,.0f})"
        lines = [f"{title}: {_tally(today)}", f"  {_gap(today)}, worst {worst}: {trip}"]
    recent = _pairs(s, day - timedelta(days=config.AUDIT_DAYS - 1), day)
    if recent:
        lines.append(f"Audit, last {config.AUDIT_DAYS} days: {_tally(recent)}; {_gap(recent)}")
    else:
        lines.append(f"Audit, last {config.AUDIT_DAYS} days: no trips priced by both sources")
    return lines


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
            *audit_lines(s, ctx.run_date),
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/pipeline/test_audit.py`

Expected: PASS. Verified tail: `5 passed in 1.99s`

- [ ] **Step 6: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `482 passed, 1 deselected, 1 warning in 61.03s (0:01:01)`; ruff reports nothing.

- [ ] **Step 7: Commit and push**

```bash
git add -A
git commit -m "feat(pipeline): fast-flights vs SerpApi audit in the health email

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 7: Roadmap

Close the two data-quality items with the probe results, and record history seeding as done.

**Files:**
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: —
- Produces: `ROADMAP.md`.

- [ ] **Step 1: Write `ROADMAP.md` (full new contents)**

```markdown
# ptopilot Roadmap

V1 scope and design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md)

## V2: begin once V1 runs end to end

- [ ] **Year-plan view.** Combine several deals into a single plan that fits the annual PTO budget, e.g. "Lisbon in April plus Thailand in September uses 14 of 20 PTO days." Replace the V1 manual `pto_committed` with booked trips that are tracked.
- [x] **Open-jaw itineraries.** Fly into one city and home from another (Plan 4: Camino Portugués, Porto → Santiago, priced through SerpApi). Multi-city with more than two legs is still open.
- [ ] **"Buy now or wait" advice.** Use price-trend history per route and lead time to recommend booking now or holding.
- [ ] **Related destinations.** Suggest places similar to the bucket list (Thailand → Vietnam). This is also the hook for sponsored or affiliate placements.
- [ ] **Adaptive polling.** Check stable routes weekly and check volatile routes, or departures within 90 days, daily.
- [ ] **Crowd and shoulder-season signal in go-now.** Add tourist-volume data to the score.
- [ ] **Per-user digest timezone and send-day preferences.**
- [x] **Digest visual polish.** Lead deal card and compact rows in destination colors (Plan 7).
- [x] **Web app look and feel.** Design system, landing page, destination-grid dashboard, destination pages with a 30-day price trend (Plan 7; spec `docs/superpowers/specs/2026-10-17-ptopilot-v2-look-and-feel-design.md`).
- [x] **Preferred trip length.** `ideal_trip_days` steers which trips are priced and adds a go-now bonus (Plan 7).

## Data quality: findings from real API calls (2026-10-16)

- [x] **Broad scan by city, "to anywhere" (tested 2026-10-18, not useful for niche routes).** NYC/EWR→anywhere for March 2027 returns ~100 fares to 59 destinations but none to PDL, FNC, PUQ or OPO; October 2027 returns 10 fares in total; exact NYC→PDL/FNC/PUQ returns nothing in any month. Travelpayouts only caches recently searched routes. The existing broad scan keeps running (free) for hub destinations.
- [x] **Check fast-flights for completeness.** Now measured daily: the scan health email compares fast-flights with SerpApi on trips both priced the same day (Plan 8). Revisit the source order if fast-flights proves systematically pricier.
- [x] **History seeding.** SerpApi round-trip results carry ~60 days of Google's own daily prices; one call per baseline key seeds a confident baseline (Plan 8; spec `docs/superpowers/specs/2026-10-18-ptopilot-v2-price-data-design.md`). Also: every in-range route is checked daily, and routes Google returns no itineraries for no longer trip the circuit breaker.

## Later and unsorted ideas

- [ ] Travel companions: alert only on the overlap between a partner's PTO windows and your own.
- [ ] Visa and passport requirements by nationality, including lead time.
- [ ] Points and miles: show award availability next to cash prices.
- [ ] Monetization: affiliate booking links, sponsored itineraries from airlines and hotels.
- [ ] Paid fare source upgrade (Duffel, Kiwi, a paid SerpApi tier) if the free sources prove unreliable.
```

- [ ] **Step 2: Run the full suite and lint**

Run (PowerShell): `$env:PTOPILOT_REQUIRE_DB=1; .venv/Scripts/python -m pytest -q; .venv/Scripts/python -m ruff check .; .venv/Scripts/python -m ruff format --check .`

Expected: `482 passed, 1 deselected, 1 warning in 81.56s (0:01:21)`; ruff reports nothing.

- [ ] **Step 3: Commit and push**

```bash
git add -A
git commit -m "docs: roadmap after better price data

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```


---

### Task 8: Run it on the real data and watch

Run one scan by hand now, rather than waiting for 06:00 UTC, and check that seeding, coverage and the audit behave on the real routes. Controller only, no code.

- [ ] **Step 1: Trigger the scan workflow**

```bash
"/c/Program Files/GitHub CLI/gh.exe" workflow run scan.yml
"/c/Program Files/GitHub CLI/gh.exe" run list --workflow scan.yml --limit 1
```

Wait for it to finish (`gh run watch <id>`, or check the list again). Expected: `completed success`. It reuses today's live checks for routes already checked this morning: a same-day re-run skips them.

- [ ] **Step 2: Read today's stage counts from Neon (read-only, URL never printed)**

```bash
.venv/Scripts/python - <<'EOF'
from pathlib import Path
from sqlalchemy import create_engine, text
from ptopilot.settings import normalize_database_url
url = next(l.split("=", 1)[1].strip().strip('"') for l in Path(".env.local").read_text().splitlines() if l.startswith("DATABASE_URL="))
e = create_engine(normalize_database_url(url))
with e.connect() as c:
    for r in c.execute(text("select stage, status, counts::text from pipeline_runs where run_date = current_date order by id desc limit 7")):
        print(tuple(r))
    print(c.execute(text("select count(*) from price_observations where source = 'google_history'")).scalar(), "history points")
EOF
```

Expected:
- `seed_history ok`. If this morning's scan already spent today's SerpApi calls (it usually spends all 8 on Camino), the counts show `keys_needing_seed` > 0 and `budget_exhausted`, and seeding starts with tomorrow's 06:00 scan: up to 6 keys, `points_stored` ≈ 60 per key. Otherwise `seeded` > 0 today.
- `live_verify` checks every shortlisted route, with no `google_flights_breaker_tripped` from PHL→PUQ. PHL→PUQ now shows as `no_flights`.
- The health email (to ADMIN_EMAIL) has the two `Audit` lines.

- [ ] **Step 3: Check baselines the next day**

After the next scheduled scan, count baselines by confidence. Expected: the seeded keys show `normal`, and the count rises each day by up to 6 until every in-range round-trip key is `normal` (~5 days):

```bash
.venv/Scripts/python - <<'EOF'
from pathlib import Path
from sqlalchemy import create_engine, text
from ptopilot.settings import normalize_database_url
url = next(l.split("=", 1)[1].strip().strip('"') for l in Path(".env.local").read_text().splitlines() if l.startswith("DATABASE_URL="))
with create_engine(normalize_database_url(url)).connect() as c:
    print(c.execute(text("select confidence, count(*) from route_baselines group by 1")).all())
EOF
```

Report anything unexpected; don't change code in this task.
