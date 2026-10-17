# ptopilot Plan 5: The Digest Email

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A twice-weekly email per traveler that leads with the best-priced trips from the latest scan, explains each one (price vs. typical, PTO cost, flights, weather, freshness, booking link), and ends with a status table of every tracker. It also has a preview mode for tuning the layout on real data before any deals exist.

**Architecture:**
- `ptopilot/digest/select.py` builds `Digest` objects (deal cards plus tracker rows) from the database: the latest scan's candidates, the resend rule, and the caps.
- `render.py` turns a `Digest` into a subject, HTML and text with Jinja2 templates.
- `send.py` delivers each digest (or writes a preview) and records `digest_sends`.
- `__main__.py` is the CLI.
- `.github/workflows/digest.yml` runs it on Mondays and Thursdays.

**Tech Stack:** Plans 1–4 plus **Jinja2** (the only new dependency). Resend via the existing `ResendEmailer`.

**Spec:** [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](../specs/2026-10-16-ptopilot-design.md) §8, including "Implementation notes (Plan 5)".

## Global Constraints

- One new runtime dependency: `jinja2>=3.1`. No `css-inline`: styles are inline in the template.
- Thresholds live in `ptopilot/config.py`: `DIGEST_MAX_DEALS = 8`, `DIGEST_ALTERNATES_PER_TRACKER = 2`, `DIGEST_RESEND_FACTOR = 0.95`, `TREND_BAND = 0.03`, `QUIET_DIGEST_WEEKDAY = 0`.
- **Preview mode** (`--preview DIR`) never writes to the database and never sends email.
- **No snooze buttons yet**; Plan 6 adds them with the web app.
- Default `pytest` never touches the network. Run database tests with `PTOPILOT_REQUIRE_DB=1`, as below.
- `ruff check .` and `ruff format --check .` must pass.
- **Work directly on `main`; every task ends with a commit and a `git push`, and the full suite is green after each task.** Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **The workflow's `min_level` input reaches the shell only through an environment variable**, never spliced into the script.
- Commands run from `C:\Users\nickd\dev\ptopilot` with `.venv/Scripts/python`. The local Postgres must be running (port 5433).

## Review Focus

Five inputs the spec implies but doesn't spell out, each pinned by a test:

1. **A deal already emailed reappears at almost the same price** → not resent until it's at least 5% cheaper than what was sent. *Task 1: `test_already_sent_deal_is_resent_only_when_meaningfully_cheaper`.*
2. **One tracker has many good deals and another only one** → the second tracker's best deal still makes the 8-deal cut, ahead of the first tracker's alternates. *Task 1: `test_per_tracker_and_total_caps_keep_every_trackers_best`.*
3. **Text with `&` or `<` in it** (carrier names, Google URLs with query strings) → escaped in HTML, unescaped in the text version. *Task 2: `test_html_escapes_but_text_does_not`, `test_html_card_contents` (the `&amp;` in the link).*
4. **Resend refuses one recipient** (no verified domain yet) → that send is logged and counted, nothing is recorded for it, the others still go out, and the CLI exits 1. *Task 3: `test_a_failed_send_is_counted_and_others_still_go_out`.*
5. **No deals on a Thursday** → nothing is sent; the "quiet week" email goes out only on Mondays. *Task 3: `test_quiet_digest_only_goes_out_on_monday`.*

## Verified before writing (2026-10-17)

- **Real-data preview against Neon** (read-only), with `--min-level none`: 8 cards and a 4-tracker table, subject `ptopilot: Patagonia (W Trek) $1,239 (2% below typical) + 7 more`. The Camino card reads "PHL → OPO, home from SCQ · $852 both flights".
- **Rendered in Chromium at 420px wide** (`.playwright-mcp/digest-mobile.png` in the workspace): cards, badges, price lines and the tracker table all lay out cleanly.
- **All three code tasks replayed in order** on a fresh copy of `main` (`sim_plan5.sh`). Each task's tests failed for the expected reason, then passed, with the full suite green after every task: 270 → 276 → 281. The final tree matched the verified copy exactly.
- Verified files: `C:\Users\nickd\AppData\Local\Temp\claude\c--Users-nickd-dev\d2c76816-13c6-4944-9ffc-e8c407f4f94a\scratchpad\p5`.

## File structure

```
pyproject.toml                         # + jinja2; package data for digest templates
ptopilot/config.py                     # + DIGEST_* , TREND_BAND, QUIET_DIGEST_WEEKDAY (replace whole file)
ptopilot/digest/__init__.py            # empty
ptopilot/digest/select.py              # DealCard, TrackerRow, Digest, build_digests, latest_run_date, LEVELS
ptopilot/digest/render.py              # render(digest) -> (subject, html, text); money/day/duration/clock/stops/checked_ago
ptopilot/digest/templates/digest.html.j2
ptopilot/digest/templates/digest.txt.j2
ptopilot/digest/send.py                # deliver(engine, digests, today, emailer=None, preview_dir=None) -> Counter
ptopilot/digest/__main__.py            # CLI: send [--date] [--min-level] [--preview]
.github/workflows/digest.yml           # Mon + Thu 12:00 UTC; manual dispatch with min_level
README.md                              # + Digest section (replace whole file)
tests/digest/{__init__,conftest,test_select,test_render,test_send}.py
```

---

### Task 1: Digest selection

**Files:**
- Modify (replace whole file): `ptopilot/config.py`
- Create: `ptopilot/digest/__init__.py` (empty), `ptopilot/digest/select.py`
- Create: `tests/digest/__init__.py` (empty), `tests/digest/conftest.py` (seed helpers)
- Test: `tests/digest/test_select.py`

**Interfaces:**
- Consumes: models (Plans 2–4), `queries.load_baselines/rq_baseline_key` (Plan 4), `Geo`, `SeasonTable`, `trip_month`.
- Produces: `LEVELS = {'none': 0, 'good': 1, 'great': 2}`; `DealCard` (frozen; fields as in the file, with `.open_jaw` and `.pct_below`); `TrackerRow(tracker_id, destination, best_price, typical, trend, next_good_month, snoozed_until)`; `Digest(user_id, email, run_date, deals, trackers)` with `.quiet`; `latest_run_date(engine, today)`; `build_digests(engine, geo, seasons, today, min_level='good') -> list[Digest]`. Test helpers: `RUN` (Thu 2027-03-04), `MONDAY`, `add_user`, `add_tracker`, `add_candidate`, `add_baseline`.

Selection rules (spec §8 plus the Plan 5 notes):
- It uses the latest scan on or before `today`. Each card needs `deal_level >= min_level`, a non-excluded candidate, and a tracker that's active and not snoozed past today.
- A previously sent (tracker, route, evening) is skipped unless now ≤ 95% of the price sent.
- Each tracker contributes its best card plus up to 2 alternates. Bests outrank alternates for the 8 slots, and the final cards are ordered by go-now.
- The tracker overview lists every active tracker (snoozed ones included) with its cheapest candidate at any level, a 7-day trend, and the next month rated good.

- [ ] **Step 1: Create the empty file** `tests/digest/__init__.py`

- [ ] **Step 2: Write** `tests/digest/conftest.py`

```python
"""Seed helpers for digest tests: a candidate plus everything it joins to."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from ptopilot.db.models import (
    Candidate,
    PriceObservation,
    RouteBaseline,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    User,
)
from ptopilot.db.session import session_scope

RUN = date(2027, 3, 4)  # a Thursday
MONDAY = date(2027, 3, 1)


def add_user(engine, email="nick@example.com") -> int:
    with session_scope(engine) as s:
        u = User(
            email=email,
            home_airport="JFK",
            country="US",
            holiday_calendar="US",
            pto_days_total=15,
            max_trip_days=16,
        )
        s.add(u)
        s.flush()
        return u.id


def add_tracker(engine, user_id, code="AZORES", **fields) -> int:
    with session_scope(engine) as s:
        t = Tracker(user_id=user_id, destination_code=code, min_stay_days=7, max_stay_days=10, **fields)
        s.add(t)
        s.flush()
        return t.id


def add_candidate(
    engine,
    tracker_id,
    price,
    depart=date(2027, 3, 5),
    ret=date(2027, 3, 14),
    level="good",
    go_now=60,
    run_date=RUN,
    dest="PDL",
    return_airport=None,
    origin="JFK",
    evening=True,
    days_off=(),
    verified=True,
) -> int:
    """A candidate with its route query, link and live observation."""
    with session_scope(engine) as s:
        user_id = s.get(Tracker, tracker_id).user_id
        rq = (
            s.query(RouteQuery)
            .filter_by(
                origin=origin,
                dest_airport=dest,
                return_airport=return_airport or dest,
                depart_date=depart,
                return_date=ret,
            )
            .one_or_none()
        )
        if rq is None:
            rq = RouteQuery(
                origin=origin,
                dest_airport=dest,
                return_airport=return_airport or dest,
                depart_date=depart,
                return_date=ret,
            )
            s.add(rq)
            s.flush()
        s.add(
            TrackerRouteLink(
                tracker_id=tracker_id,
                route_query_id=rq.id,
                run_date=run_date,
                evening_departure=evening,
                pto_cost=5,
                days_away=(ret - depart).days + 1,
                efficiency=2.0,
                month=depart.month,
                season_rating="shoulder",
                days_off=list(days_off),
            )
        )
        obs = PriceObservation(
            origin=origin,
            dest_airport=dest,
            return_airport=return_airport or dest,
            depart_date=depart,
            return_date=ret,
            month=depart.replace(day=1),
            source="google_flights",
            price=Decimal(str(price)),
            currency="USD",
            carrier="Tap Air Portugal",
            stops=1,
            duration_min=420,
            outbound_departure=datetime.combine(depart, time(22, 0)),
            flight_numbers=["TP 202"],
            deep_link="https://www.google.com/travel/flights/search?tfs=X",
            verified=verified,
            observed_at=datetime.combine(run_date, time(6), UTC),
        )
        s.add(obs)
        s.flush()
        c = Candidate(
            user_id=user_id,
            tracker_id=tracker_id,
            route_query_id=rq.id,
            price_observation_id=obs.id,
            run_date=run_date,
            evening_departure=evening,
            price=Decimal(str(price)),
            currency="USD",
            z=-1.6,
            deal_level=level,
            go_now=go_now,
            confidence="normal",
            verified=verified,
        )
        s.add(c)
        s.flush()
        return c.id


def add_baseline(engine, median, dest="PDL", month=date(2027, 3, 1), bucket="week", return_airport=None):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="JFK",
                dest_airport=dest,
                return_airport=return_airport or dest,
                month=month,
                length_bucket=bucket,
                median=Decimal(median),
                sigma=Decimal(50),
                n=20,
                confidence="normal",
            )
        )
```

- [ ] **Step 3: Write the failing test file** `tests/digest/test_select.py`

```python
from datetime import date, timedelta
from decimal import Decimal

from ptopilot import config
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest.select import build_digests
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user

GEO, SEASONS = load_geo(), load_seasons()


def digests(engine, today=RUN, min_level="good"):
    return build_digests(engine, GEO, SEASONS, today, min_level)


def test_nothing_scanned_means_no_digests(clean_engine):
    assert digests(clean_engine) == []


def test_only_deals_by_default_and_everything_with_min_level_none(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 600, level="great")
    add_candidate(clean_engine, t, 650, depart=date(2027, 3, 12), ret=date(2027, 3, 21), level="none")
    [d] = digests(clean_engine)
    assert [c.price for c in d.deals] == [600]
    [d] = digests(clean_engine, min_level="none")
    assert sorted(c.price for c in d.deals) == [600, 650]


def test_uses_the_latest_scan_on_or_before_today(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 700, run_date=RUN - timedelta(days=3))
    add_candidate(clean_engine, t, 600, run_date=RUN)
    assert [c.price for c in digests(clean_engine)[0].deals] == [600]
    assert [c.price for c in digests(clean_engine, today=RUN - timedelta(days=1))[0].deals] == [700]


def test_card_details_typical_price_and_open_jaw(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine), code="CAMINO_PORTUGUES")
    add_candidate(
        clean_engine,
        t,
        900,
        dest="OPO",
        return_airport="SCQ",
        ret=date(2027, 3, 20),
        days_off=("Company day off",),
    )
    add_baseline(clean_engine, 1200, dest="OPO", return_airport="SCQ", bucket="long")
    card = digests(clean_engine)[0].deals[0]
    assert card.destination.startswith("Camino Portugués")
    assert card.open_jaw and (card.dest_airport, card.return_airport) == ("OPO", "SCQ")
    assert (card.typical, card.pct_below) == (Decimal(1200), 25)
    assert card.days_off == ("Company day off",)
    assert (card.carrier, card.stops, card.flight_numbers) == ("Tap Air Portugal", 1, ("TP 202",))
    assert card.weather_note  # March note for the Camino


def test_snoozed_tracker_sends_no_deals_but_stays_in_the_overview(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine), snoozed_until=RUN + timedelta(days=10))
    add_candidate(clean_engine, t, 600)
    [d] = digests(clean_engine)
    assert d.quiet
    assert [(r.destination, r.snoozed_until) for r in d.trackers] == [("Azores", RUN + timedelta(days=10))]


def test_already_sent_deal_is_resent_only_when_meaningfully_cheaper(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    old = add_candidate(clean_engine, t, 600, run_date=RUN - timedelta(days=3))
    with session_scope(clean_engine) as s:
        s.add(DigestSend(user_id=uid, items=[{"candidate_id": old, "price": 600.0}]))
    add_candidate(clean_engine, t, 590, run_date=RUN)  # only 1.7% cheaper than what was sent
    assert digests(clean_engine)[0].deals == []
    add_candidate(
        clean_engine, t, 560, depart=date(2027, 3, 5), run_date=RUN + timedelta(days=1), evening=True
    )
    assert [c.price for c in digests(clean_engine, today=RUN + timedelta(days=1))[0].deals] == [560]


def test_per_tracker_and_total_caps_keep_every_trackers_best(clean_engine, monkeypatch):
    monkeypatch.setattr(config, "DIGEST_MAX_DEALS", 4)
    uid = add_user(clean_engine)
    azores, madeira = add_tracker(clean_engine, uid), add_tracker(clean_engine, uid, code="MADEIRA")
    for i in range(5):
        week = timedelta(days=7 * (i % 3))
        add_candidate(
            clean_engine,
            azores,
            600 + i,
            depart=date(2027, 3, 5) + week,
            ret=date(2027, 3, 14) + week,
            evening=i < 3,
            go_now=90 - i,
        )
    add_candidate(clean_engine, madeira, 800, dest="FNC", go_now=50)
    deals = digests(clean_engine)[0].deals
    assert len(deals) == 4
    assert sum(1 for d in deals if d.tracker_id == azores) == 3  # best + 2 alternates
    assert any(d.tracker_id == madeira for d in deals)  # Madeira's best beats Azores' alternates for a slot


def test_tracker_overview_trend_and_next_good_month(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    add_tracker(clean_engine, uid, code="MADEIRA")
    add_candidate(clean_engine, t, 700, run_date=RUN - timedelta(days=7))
    add_candidate(clean_engine, t, 600, run_date=RUN)
    rows = {r.destination: r for r in digests(clean_engine)[0].trackers}
    assert (rows["Azores"].best_price, rows["Azores"].trend) == (600, "down")
    assert rows["Azores"].next_good_month == "May"
    assert (rows["Madeira"].best_price, rows["Madeira"].trend, rows["Madeira"].next_good_month) == (
        None,
        "new",
        "Mar",
    )


def test_users_without_active_trackers_get_no_digest(clean_engine):
    add_user(clean_engine, "idle@example.com")
    t = add_tracker(clean_engine, add_user(clean_engine, "off@example.com"), active=False)
    add_candidate(clean_engine, t, 600)
    assert digests(clean_engine) == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest/test_select.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.digest'`.

- [ ] **Step 5: Write** `ptopilot/config.py`

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

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
```

- [ ] **Step 6: Create the empty file** `ptopilot/digest/__init__.py`

- [ ] **Step 7: Write** `ptopilot/digest/select.py`

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
    engine: Engine, geo: Geo, seasons: SeasonTable, today: date, min_level: str = "good"
) -> list[Digest]:
    """One digest per user with active trackers, from the latest scan on or before `today`."""
    run_date = latest_run_date(engine, today)
    if run_date is None:
        return []
    floor = LEVELS[min_level]
    with session_scope(engine) as s:
        baselines = load_baselines(s)
        users = list(s.scalars(select(User).order_by(User.id)))
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
        # Lowest price already sent per (tracker, route, evening); resent only when meaningfully cheaper.
        sent_price: dict[tuple, Decimal] = {}
        sent_ids: dict[int, Decimal] = {}
        for send in s.scalars(select(DigestSend)):
            for item in send.items or []:
                cid, price = int(item["candidate_id"]), Decimal(str(item["price"]))
                sent_ids[cid] = min(price, sent_ids.get(cid, price))
        if sent_ids:
            for c in s.scalars(select(Candidate).where(Candidate.id.in_(sent_ids))):
                key = (c.tracker_id, c.route_query_id, c.evening_departure)
                sent_price[key] = min(sent_ids[c.id], sent_price.get(key, sent_ids[c.id]))

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

- [ ] **Step 8: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest/test_select.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **270 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 9: Commit and push**

```bash
git add ptopilot/config.py ptopilot/digest tests/digest
git commit -m "feat(digest): select deals and tracker overview per traveler" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Digest rendering (HTML + text)

**Files:**
- Modify (replace whole file): `pyproject.toml` (+ `jinja2>=3.1`, package data `ptopilot.digest: templates/*.j2`)
- Create: `ptopilot/digest/render.py`, `ptopilot/digest/templates/digest.html.j2`, `ptopilot/digest/templates/digest.txt.j2`
- Test: `tests/digest/test_render.py`

**Interfaces:**
- Consumes: `Digest`, `DealCard`, `TrackerRow` (Task 1).
- Produces: `render(digest, now=None) -> (subject, html, text)`; `subject(digest)`; helpers `money`, `day`, `duration`, `clock`, `stops`, `checked_ago(observed, now)`.

Install the new dependency after writing `pyproject.toml`: `.venv/Scripts/python -m pip install -e ".[dev]"`. Expected: `Successfully installed … jinja2 …` (or "already satisfied"). Autoescaping applies only to `*.html.j2`. The HTML uses table layout with inline styles, which mail clients render most reliably.

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest/test_render.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'ptopilot.digest.render'`.

- [ ] **Step 4: Write** `ptopilot/digest/render.py`

```python
"""Render a Digest as an email: subject, HTML (inline styles, table layout for mail clients), plain text."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ptopilot.digest.select import Digest

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


def render(digest: Digest, now: datetime | None = None) -> tuple[str, str, str]:
    """(subject, html, text)."""
    now = now or datetime.now(UTC)
    context = {
        "digest": digest,
        "levels": LEVEL_LABEL,
        "arrows": TREND_ARROW,
        "checked": {d.candidate_id: checked_ago(d.observed_at, now) for d in digest.deals},
    }
    html = _env.get_template("digest.html.j2").render(**context)
    text = _env.get_template("digest.txt.j2").render(**context)
    return subject(digest), html, text
```

- [ ] **Step 5: Write** `ptopilot/digest/templates/digest.html.j2`

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

- [ ] **Step 6: Write** `ptopilot/digest/templates/digest.txt.j2`

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
{% endfor %}

Your trackers
{% for t in digest.trackers %}
- {{ t.destination }}: best {{ t.best_price | money }}, typical {{ t.typical | money }}, 7-day {{ arrows[t.trend] }}, next good month {{ t.next_good_month or "-" }}{% if t.snoozed_until %} (snoozed to {{ t.snoozed_until | day }}){% endif %}

{% endfor %}

Prices change constantly; always confirm before booking.
```

- [ ] **Step 7: Run tests, the full suite, and lint**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest/test_render.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **276 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 8: Commit and push**

```bash
git add pyproject.toml ptopilot/digest/render.py ptopilot/digest/templates tests/digest/test_render.py
git commit -m "feat(digest): HTML and text rendering" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Sending, CLI, scheduled workflow

**Files:**
- Create: `ptopilot/digest/send.py`, `ptopilot/digest/__main__.py`, `.github/workflows/digest.yml`
- Modify (replace whole file): `README.md` (+ Digest section)
- Test: `tests/digest/test_send.py`

**Interfaces:**
- Consumes: `build_digests` (Task 1), `render` (Task 2), `ResendEmailer`, `EmailError`, `Settings`.
- Produces: `deliver(engine, digests, today, emailer=None, preview_dir=None) -> Counter` (keys: `sent`, `deals_sent`, `failed`, `quiet_skipped`, `previewed`); CLI `python -m ptopilot.digest send [--date D] [--min-level good|great|none] [--preview DIR]` (exit 2 without `RESEND_API_KEY` unless previewing, exit 1 if any send failed).

- [ ] **Step 1: Write the failing test file** `tests/digest/test_send.py`

```python
from sqlalchemy import select

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Candidate, DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest import __main__ as cli
from ptopilot.digest.select import build_digests
from ptopilot.digest.send import deliver
from ptopilot.notify.email import EmailError
from tests.conftest import TEST_URL
from tests.digest.conftest import MONDAY, RUN, add_candidate, add_tracker, add_user


class FakeEmailer:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, to, subject, html, text):
        if to in self.fail_for:
            raise EmailError("resend: HTTP 403: You can only send testing emails to your own email address")
        self.sent.append((to, subject))
        return "msg"


def built(engine, today=RUN):
    return build_digests(engine, load_geo(), load_seasons(), today, "good")


def sends(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(DigestSend)))


def test_send_records_the_digest_and_marks_candidates_sent(clean_engine):
    uid = add_user(clean_engine)
    cid = add_candidate(clean_engine, add_tracker(clean_engine, uid), 600)
    emailer = FakeEmailer()
    counts = deliver(clean_engine, built(clean_engine), RUN, emailer=emailer)
    assert (counts["sent"], counts["deals_sent"]) == (1, 1)
    assert emailer.sent == [("nick@example.com", "ptopilot: Azores $600")]
    [record] = sends(clean_engine)
    assert record.items == [{"candidate_id": cid, "price": 600.0}]
    with session_scope(clean_engine) as s:
        assert s.get(Candidate, cid).state == "sent"


def test_quiet_digest_only_goes_out_on_monday(clean_engine):
    add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, add_tracker(clean_engine, 1, code="MADEIRA"), 900, level="none", dest="FNC")
    emailer = FakeEmailer()
    assert deliver(clean_engine, built(clean_engine), RUN, emailer=emailer)["quiet_skipped"] == 1  # Thursday
    assert deliver(clean_engine, built(clean_engine), MONDAY, emailer=emailer)["sent"] == 1
    assert emailer.sent[0][1] == "ptopilot: a quiet week for your trips"


def test_a_failed_send_is_counted_and_others_still_go_out(clean_engine):
    for email in ("nick@example.com", "friend@example.com"):
        add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine, email)), 600)
    emailer = FakeEmailer(fail_for={"friend@example.com"})
    counts = deliver(clean_engine, built(clean_engine), RUN, emailer=emailer)
    assert (counts["sent"], counts["failed"]) == (1, 1)
    assert [to for to, _ in emailer.sent] == ["nick@example.com"]
    assert len(sends(clean_engine)) == 1  # nothing recorded for the failed one


def test_preview_writes_files_and_touches_nothing(clean_engine, tmp_path):
    add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    counts = deliver(clean_engine, built(clean_engine), RUN, preview_dir=tmp_path)
    assert counts["previewed"] == 1
    html = (tmp_path / f"digest-1-{RUN}.html").read_text(encoding="utf-8")
    text = (tmp_path / f"digest-1-{RUN}.txt").read_text(encoding="utf-8")
    assert "Azores" in html and text.startswith("Subject: ptopilot: Azores $600")
    assert sends(clean_engine) == []


def test_cli_requires_an_emailer_unless_previewing(clean_engine, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert cli.main(["send"]) == 2
    add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    assert cli.main(["send", "--date", str(RUN), "--preview", str(tmp_path)]) == 0
    assert "previewed=1" in capsys.readouterr().out
    assert (tmp_path / f"digest-1-{RUN}.html").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest/test_send.py -q`
Expected: collection ERROR, `ImportError: cannot import name '__main__' from 'ptopilot.digest'`.

- [ ] **Step 3: Write** `ptopilot/digest/send.py`

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
from ptopilot.digest.render import render
from ptopilot.digest.select import Digest
from ptopilot.notify.email import Emailer, EmailError

log = logging.getLogger(__name__)


def deliver(
    engine: Engine,
    digests: Sequence[Digest],
    today: date,
    emailer: Emailer | None = None,
    preview_dir: Path | None = None,
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
        subject, html, text = render(digest)
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
        with session_scope(engine) as s:
            s.add(
                DigestSend(
                    user_id=digest.user_id,
                    items=[{"candidate_id": d.candidate_id, "price": float(d.price)} for d in digest.deals],
                )
            )
            ids = [d.candidate_id for d in digest.deals]
            if ids:
                s.execute(update(Candidate).where(Candidate.id.in_(ids)).values(state="sent"))
        counts["sent"] += 1
        counts["deals_sent"] += len(digest.deals)
    return counts
```

- [ ] **Step 4: Write** `ptopilot/digest/__main__.py`

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
    emailer = None if args.preview else ResendEmailer(settings.resend_api_key, settings.email_from)
    counts = deliver(engine, digests, today, emailer=emailer, preview_dir=args.preview)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to send"
    print(f"digests for {today}: {len(digests)} built; {summary}")
    if args.preview:
        print(f"preview written to {args.preview.resolve()}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Write** `.github/workflows/digest.yml`

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
      MIN_LEVEL: ${{ inputs.min_level || 'good' }}  # passed via env, never spliced into the shell script
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install -e .
      - run: python -m ptopilot.digest send --min-level "$MIN_LEVEL"
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

## Digest

```powershell
.venv/Scripts/python -m ptopilot.digest send --preview out/                 # write each digest to out/*.html + .txt
.venv/Scripts/python -m ptopilot.digest send --preview out/ --min-level none # include trips that aren't deals yet (tuning)
.venv/Scripts/python -m ptopilot.digest send                                 # email them (needs RESEND_API_KEY)
```

`.github/workflows/digest.yml` sends on Mondays and Thursdays at 12:00 UTC, after the morning scan. A digest with no deals ("quiet week") only goes out on Mondays. Run it by hand from the Actions tab with `min_level: none` to get a tuning email built from every priced trip. Without a verified sending domain, Resend only delivers to the Resend account's own address; a send to anyone else fails, is logged, and the run exits red while the other digests still go out.

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

Run: `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest tests/digest/test_send.py -q`, then `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q`, then `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`
Expected: target tests all pass; full suite **281 passed, 1 deselected**; `All checks passed!`; nothing to reformat.

- [ ] **Step 8: Commit and push**

```bash
git add ptopilot/digest/send.py ptopilot/digest/__main__.py .github/workflows/digest.yml README.md tests/digest/test_send.py
git commit -m "feat(digest): send/preview CLI and Mon/Thu workflow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Then: `& "C:\Program Files\GitHub CLI\gh.exe" run watch --exit-status` on the `ci` run → green.

---

### Task 4: First real digests (no code)

- [ ] **Step 1: Preview from production data, read-only.** Run, with `DATABASE_URL` taken from `.env.local` (pooled) and never printed: `.venv/Scripts/python -m ptopilot.digest send --preview out/digest --min-level none`. Expected: `1 built; previewed=1`. Give the user the absolute path of `out/digest/digest-<id>-<date>.html` to open in a browser. `out/` must be git-ignored; add `out/` to `.gitignore` in this step's commit if it isn't.
- [ ] **Step 2: Send a real tuning email to the user's own inbox:** `& "C:\Program Files\GitHub CLI\gh.exe" workflow run digest.yml -f min_level=none`, then watch the run. Expected: green, with `sent=1` in the log. The email goes to `ADMIN_EMAIL`'s address, which owns the Resend account (Resend's shared sender only delivers there). If the address on the user's profile differs from the Resend account's, expect `failed=1`, a red run, and a 403 error naming the restriction. Report it rather than retrying.
- [ ] **Step 3:** Record in the ledger the digest headline (subject line, deal count, tracker rows) and the run URL.

### Final check

- [ ] `PTOPILOT_REQUIRE_DB=1 .venv/Scripts/python -m pytest -q` → **281 passed, 1 deselected**. `git status` clean. Nothing unpushed. Latest `ci` and `digest` runs green.

## After this plan

- **Tuning:** iterate on `digest.html.j2` and `digest.txt.j2` against `--preview` output. The real deal flags start once routes have about 15 observations, roughly two weeks of daily scans.
- **Plan 6, the web app:** sign-in, onboarding (replacing the YAML loader), dashboard, snooze buttons in the digest, and a verified sending domain before friends are invited.
