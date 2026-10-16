# ptopilot — V1 Design Spec

**Date:** 2026-10-16
**Status:** Draft, awaiting review
**Working name:** `ptopilot` (rename freely)
**V2 backlog:** [`ROADMAP.md`](../../../ROADMAP.md)

---

## 1. Purpose and success criteria

**Problem.** People with flexible PTO and a long bucket list of destinations can't practically track fares for every combination of destination, date window, trip length, and home airport. Good fares get missed, and PTO gets spent inefficiently.

**Product.** A user describes their PTO budget, travel windows, holiday calendar, and bucket-list destinations once. ptopilot builds realistic itineraries, tracks their prices every day, and emails a digest twice a week. The digest highlights trips that are priced well below their typical range, fit the user's PTO, and fall in a good season at the destination.

**Audience (V1).** The author plus a few invited friends, as a portfolio project. It may grow into a real product if it works well.

**V1 is successful when:**
1. A user can complete onboarding in the web app and edit or snooze trackers.
2. The daily scan runs unattended on free infrastructure and records price history.
3. The twice-weekly digest arrives with correctly scored deals: correct PTO cost, correct season filtering, a z-score against history, and a booking link.
4. The author receives a health email after each scan, and a failed day can be re-run with no side effects.
5. The total running cost is $0/month.

**Non-goals for V1:** booking or payments, hotels, mobile apps, per-user digest timezones, open-jaw itineraries, and every other item in `ROADMAP.md`.

---

## 2. Tech stack and hosting

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Web | FastAPI + Jinja2 + HTMX |
| ORM / migrations | SQLAlchemy 2.x + Alembic |
| Database | Neon Postgres (free tier); Postgres 16 via Docker locally |
| Scheduled jobs | GitHub Actions cron |
| Web hosting | Render free web service (sleeps after about 15 minutes idle) |
| Email | Resend (free tier, about 3k emails/month) |
| Holidays | `holidays` PyPI package |
| Climate data | Open-Meteo climate API (offline generation script only) |
| Email CSS | `css-inline` |
| Tests | pytest |

**Local development:** `docker compose up` starts Postgres and the web app. The pipeline CLI runs against the same database.

**Secrets** live in GitHub Actions secrets and Render environment variables, never in the repo: `DATABASE_URL`, `TRAVELPAYOUTS_TOKEN`, `SERPAPI_KEY`, `RESEND_API_KEY`, `SECRET_KEY` (used to sign tokens), `ADMIN_EMAIL`.

---

## 3. Fare data sources

All fare access goes through two small interfaces in `ptopilot/sources/base.py`, one per job, so any source can be swapped for a paid one later without touching the pipeline:

```python
class MonthScanSource(Protocol):      # broad, cached
    name: str
    def month_scan(self, origin, dest_airport, month: date, market, currency) -> list[FareQuote]: ...

class ExactSearchSource(Protocol):    # live, exact dates
    name: str
    def exact_search(self, query: ExactQuery) -> ExactResult: ...
```

Both raise `SourceUnavailable` on network, auth or quota errors and on unparseable responses. An `ExactResult` holds the round-trip options, the booking link, and Google's typical price range when the source provides one. Each option has the round-trip price plus outbound-leg details (carrier, stops, duration, departure time, flight numbers, overnight layover).

| Role | Source | Notes |
|---|---|---|
| Broad scan | **Travelpayouts / Aviasales Data API** | Free, needs a token. Cached prices built from real searches, 2–7 days old. Queried by origin, destination, and month. `market` comes from the user's home country. Implements `month_scan` only. |
| Live verification | **`fast-flights`** 3.x (Python library that scrapes Google Flights), wrapped as `GoogleFlightsSource` | Free and real-time. Unofficial and fragile, and requests from GitHub Actions IPs may get blocked. Returns no flight numbers and no price-level label. Implements `exact_search`. |
| Fallback + price insights | **SerpApi Google Flights** | Free tier of about 250 searches/month, so the daily budget is about 8. Returns Google's `price_insights` (typical range), which is used for cold-start baselines. Implements `exact_search`. |

Amadeus Self-Service is not an option: Amadeus shut it down on 2026-07-17. Duffel and Kiwi require business onboarding, so they're deferred.

---

## 4. Architecture

A **staged batch pipeline**. Every stage is its own module that reads its inputs from Postgres and writes its outputs back. Each stage can be re-run safely (it is idempotent per run date) and can be invoked on its own.

```
scan.yml (daily, 06:00 UTC)
  expand → season_filter → broad_scan → shortlist → live_verify → baselines → score
digest.yml (Mon + Thu, 12:00 UTC ≈ 8am US Eastern)
  select → render → send
keepalive.yml (monthly)
  commit timestamp so GitHub does not disable scheduled workflows
```

The CLI is `python -m ptopilot.pipeline run [--stage NAME] [--date YYYY-MM-DD] [--dry-run]`, and `python -m ptopilot.digest send [--preview PATH] [--dry-run]`.

### Repo layout

```
ptopilot/
  core/        # pure logic, no network or DB: calendar, shapes, expansion, season filter, stats, scoring
  sources/     # travelpayouts.py, fast_flights.py, serpapi.py, base.py (FareSource, models, errors)
  pipeline/    # one module per stage + runner.py
  digest/      # select.py, render.py, send.py, templates/
  web/         # FastAPI app, routes, templates, auth, signed tokens
  db/          # models.py, session.py, alembic/
  data/        # geo.yaml (airports, destinations, travel rules), seasons.yaml, airports.csv
  config.py    # scoring weights, thresholds, caps (one place to tune)
scripts/       # generate_seasons.py (Open-Meteo → seasons.yaml draft)
tests/
.github/workflows/  scan.yml, digest.yml, keepalive.yml, ci.yml
docker-compose.yml, Dockerfile, ROADMAP.md
```

**Boundary rule:** `core/` imports nothing from `db/`, `sources/`, or `web/`. The pipeline stages connect `core/` to the outside world.

---

## 5. Data model

| Table | Key columns |
|---|---|
| `users` | id, email (unique), home_airport, nearby_airports[], country, holiday_calendar (e.g. `US`, `GB-ENG`), extra_days_off[], ignored_holidays[], pto_days_total, max_trip_days, min_trip_days, weather_tolerance (`strict`/`normal`/`relaxed`), max_stops_short, max_stops_long, allow_overnight_layover, friday_evening_departure (bool), friday_evening_min_time, created_at |
| `invites` | email, invited_at |
| `travel_windows` | id, user_id, start_date, end_date |
| `trackers` | id, user_id, destination_code, destination_kind (`city`/`region`), min_stay_days, max_stay_days, priority (1–3), max_price (nullable), snoozed_until (nullable), active |
| `tracker_exclusions` | tracker_id, depart_date, return_date (from the "Not this trip" button) |
| `route_queries` | id, origin, dest_airport, depart_date, return_date; unique on all four. Shared across users. |
| `tracker_route_links` | tracker_id, route_query_id, shape_id, pto_cost, days_away, efficiency, run_date |
| `price_observations` | id, origin, dest_airport, depart_date (nullable for month-level quotes), return_date (nullable), month, source, price, currency, carrier, stops, duration_min, outbound_dep_time, flight_numbers, deep_link, verified (bool), observed_at. **Append-only.** |
| `route_baselines` | origin, dest_airport, month, length_bucket, median, mad_sigma, n, google_typical_low, google_typical_high, computed_at |
| `candidates` | id, user_id, tracker_id, route_query_id, price_observation_id, price, z, deal_level (`none`/`good`/`great`), go_now, confidence (`normal`/`low`), verified, state (`new`/`sent`/`snoozed`/`excluded`), run_date |
| `digest_sends` | id, user_id, sent_at, candidate_ids[], price_at_send per candidate (jsonb) |
| `pipeline_runs` | id, run_date, stage, started_at, finished_at, status, counts (jsonb), error |
| `source_budget` | source, period (month), calls_used |

Trip-length buckets: `short` (≤5 days away), `week` (6–10), `long` (11+).

**Implementation notes (Plan 2):**
- `users` also stores `currency` (default USD) and `pto_committed`.
- `trackers` has no `destination_kind` column; whether a destination is a city or a region comes from `geo.yaml`.
- `tracker_route_links` stores the shape's facts directly (`evening_departure`, `pto_cost`, `days_away`, `efficiency`, `month`, `season_rating`, `days_off`) instead of a `shape_id`.
- `price_observations.month` is the first day of the departure month. It also stores `outbound_departure` and `overnight_layover`, which live checks need for filtering.
- `candidates` stores `currency` and `evening_departure`.
- `digest_sends.items` is a JSON list of `{candidate_id, price}`.

---

## 6. Itinerary generator (`core/`)

### 6.1 Work calendar
- A day is a **workday** unless it is a weekend day (Sat/Sun), a public holiday in `holidays.country_holidays(...)` for the user's calendar/subdivision, or in the user's `extra_days_off`.
- `ignored_holidays` lists holiday names the user's office does *not* observe (e.g. US `Columbus Day`, `Veterans Day`, which are federal but often worked). Those days and their "(observed)" stand-ins count as workdays.
- PTO cost = the number of workdays in the trip's away span.

### 6.2 Trip shapes
A shape is any `[depart, return]` where both ends sit next to an off-block (a run of weekend days, holidays, or company days off):
- **Departure day:** the first day of an off-block (e.g. Saturday), or the last workday before one (e.g. Friday, or the Wednesday before Thanksgiving).
- **Return day:** the last day of an off-block (e.g. Sunday), or the first workday after one (e.g. Monday).
- A **zero-PTO shape** (a weekend or holiday block with no PTO) is also valid if it satisfies the length constraints.

This rules out odd shapes like Wed→Thu by construction, while still allowing Wednesday departures before a Thursday holiday.

**Friday-evening variant** (if `friday_evening_departure`): every shape that departs on a workday also gets a variant leaving after work that day. It costs one less PTO day and is tagged `evening_departure`. The live check enforces `friday_evening_min_time`.

### 6.3 Constraints
For each tracker × window, keep a shape only if:
- `depart` and `return` both fall within the travel window (with an allowance of ±2 days for the weekends/holidays the shape expands into).
- `days_away ≤ user.max_trip_days`
- `days_away ≥ max(user.min_trip_days, region_min_trip_days[dest_region])`
- `ground_days = days_away − travel_overhead[home_region][dest_region]` lies within `[tracker.min_stay_days, tracker.max_stay_days]`
- `pto_cost ≤ user.pto_days_total − pto_committed`. For V1, `pto_committed` is a single number the user enters by hand.

### 6.4 Ranking and pruning
- `efficiency = days_away / max(pto_cost, 0.5)`
- Keep the **top 6 shapes per (tracker, window)** by efficiency, with diversity: at most 2 per distinct `days_away` value, and at most 1 per (depart, return) pair so an evening variant never takes a second slot for the same flights. Ties are broken by fewer PTO days, then earlier date.
- The season filter (§6.5) runs **before** this pruning, so the top 6 are never spent on months that will be filtered out.

### 6.5 Season filter
- `data/seasons.yaml`: `{code: {months: [12 ratings Jan..Dec], notes: {month: text}}}`. The code is looked up as the destination code first, then its country code (so a `TH` entry covers a Bangkok city tracker).
- `scripts/generate_seasons.py` writes a first draft from Open-Meteo climate normals (precipitation days, mean max temperature, humidity). The author then corrects it by hand for monsoon, hurricane, and similar seasons. The file is committed.
- A trip's month is the calendar month containing the majority of its days.
- Tolerance: `strict` allows {good}, `normal` allows {good, shoulder}, `relaxed` allows all months. Avoid-month trips get the low weather score (§7 `score`) and an "off-season" label in the digest.
- A destination missing from `seasons.yaml` counts as `good`, and a warning is logged.

### 6.6 Destination expansion
- `data/geo.yaml` holds three things:
  - **airports**, each with a country and a coarse zone (`NA`, `EUROPE`, `SE_ASIA`, …)
  - **destinations**: a region or city code mapped to its airports (e.g. `TH: [BKK, HKT, CNX]`, `TYO: [HND, NRT]`). A destination takes its country and zone from its first airport.
  - **travel rules** per zone pair: `overhead_days` and `min_trip_days`, with a default rule for unlisted pairs
- A trip is international when the origin airport's country differs from the destination's.
- Overlapping travel windows never produce duplicate itineraries.
- Origins = `home_airport` + `nearby_airports`.

---

## 7. Scan, verification, baselines, scoring (`pipeline/`)

### Stage `expand`
Runs the generator for every active, non-snoozed tracker. Upserts `route_queries` (deduplicated across users) and writes `tracker_route_links` for the run date.

### Stage `season_filter`
Applies §6.5. Filtered-out links are dropped before any network call.

### Stage `broad_scan`
For each unique `(origin, dest_airport, month)` in today's links, calls `TravelpayoutsSource.month_scan`. Each quote is appended to `price_observations` with `verified=false`. Expected volume is about 90 calls per day per user, deduplicated across users.

### Stage `shortlist`
- `est_price` for each route_query = the cached fare for the exact dates if one exists, otherwise the cheapest cached fare for that month on the route.
- A route_query is **eligible** if `est_price ≤ p35` of its baseline, or if its baseline has `n < 15`. The second group is limited by an **exploration quota** of 10 per day, picking the oldest-observed routes first.
- Rank by `deal_strength × urgency × priority_weight`, where:
  - `deal_strength = max(0, −z_est)` (with z_est = 0 when there is no baseline)
  - `urgency` = 1.0 if departure is 30–120 days out, 0.7 if fewer than 30, 0.5 if more than 120
  - `priority_weight` comes from the tracker priority as {1: 1.0, 2: 0.8, 3: 0.6}
- Take the top **`LIVE_CHECK_CAP = 40`**.

### Stage `live_verify`
- Calls `FastFlightsSource.exact_search` with a random 3–8 s delay between requests.
- **Circuit breaker:** after 3 consecutive `SourceUnavailable` errors, switch to `SerpApiSource` for the rest of the run, limited by `source_budget` (about 8/day, never more than 250/month).
- When both sources are unavailable, the shortlisted items stay unverified and carry their cached price.
- **Filters on live results:**
  - stops ≤ `max_stops_short` if the nonstop-equivalent duration is under 10 hours, otherwise ≤ `max_stops_long`
  - duration ≤ 1.5× the fastest option on that query
  - no overnight layover unless the user allows it
  - Friday-evening variants must depart after `friday_evening_min_time`
- The cheapest result that passes the filters is appended as `verified=true`, with carrier, flight numbers, duration, outbound departure time, and a Google Flights deep link.
- SerpApi `price_insights.typical_price_range` is stored on `route_baselines.google_typical_low/high`.

### Stage `baselines`
For each `(origin, dest_airport, month, length_bucket)`, take observations from the trailing 60 days. When there are several observations of the same route_query on the same day, keep only the cheapest so frequently checked routes don't dominate. Then:
- `median` = median price
- `mad_sigma = 1.4826 × median(|p − median|)`, with a floor of 3% of the median
- `n` = the number of observations
- **Cold start (n < 15):** if a Google typical range exists, blend `median` toward its midpoint and `sigma` toward `(high − low) / 2`, weighted by `n/15`. Otherwise use the Travelpayouts month data on its own. Mark confidence `low`.

### Stage `score`
For each user/tracker link that has a price today:
- `z = (price − median) / mad_sigma`
- `deal_level`: `great` if z ≤ −1.5, `good` if z ≤ −1.0, otherwise `none`
- `go_now` (0–100) = 100 × (0.5·deal + 0.2·weather + 0.2·efficiency + 0.1·timing), where:
  - `deal = clamp(−z / 2.5, 0, 1)`
  - `weather` = good 1.0, shoulder 0.6, avoid 0.2
  - `efficiency = clamp((efficiency − 1) / 2, 0, 1)`
  - `timing` = 1.0 if departure is in the sweet spot (30–120 days out for international, 21–90 for domestic), otherwise 0.5
- Apply the tracker's `max_price` and `tracker_exclusions`.
- Upsert into `candidates`.

All weights and thresholds live in `config.py`.

---

## 8. Digest (`digest/`)

**Schedule:** Mon and Thu at 12:00 UTC, the same time for every user.

**Selection, per user:**
- `deal_level ∈ {good, great}`, tracker not snoozed, candidate not excluded.
- Skip anything already sent, unless the current price is at least 5% below `price_at_send`.
- Per tracker: the top 1 by `go_now`, plus up to 2 alternates. No more than 8 deals per email in total, ordered by `go_now`.
- If nothing qualifies: Monday sends a short "quiet week" email with the tracker overview, and Thursday sends nothing.

**Deal card:**
- Destination and dates with day names
- Deal badge and go-now score
- Price vs. typical, with the % below
- PTO used vs. days away, naming the holiday that stretched the trip
- Carrier, stops, durations, departure times
- One-line weather note from `seasons.yaml` notes
- Confidence and verified status, plus "checked N hours ago"
- **Book on Google Flights** link
- Snooze buttons: *Not this trip*, *Snooze 30 days*, *Not this year*, *Only if under $___* (the last one opens a small web form)

**Tracker overview:** a table with one row per tracker. Columns: current best price, typical price, trend arrow (7-day median change), next good-season month, snooze state.

**Implementation:** Jinja templates, CSS inlined with `css-inline`, a plain-text alternative, and sending through the Resend API. `--preview PATH` writes the HTML to disk without sending. Every send writes a row to `digest_sends` and sets the included candidates to `state=sent`.

The visual design is expected to change once real digests exist.

---

## 9. Web app (`web/`)

- **Auth:** passwordless sign-in by emailed link. The token is signed with `itsdangerous` and expires after 15 minutes. Signing in sets a session cookie. Only emails in `invites` can sign up.
- **Onboarding:** one stepped page, with HTMX for the dynamic parts:
  1. Home airport. Nearby airports within about 200 km are suggested from `airports.csv`, and the user picks which ones count.
  2. Holiday calendar, plus extra company days off.
  3. PTO total, PTO already committed, max trip length, min trip length.
  4. Travel windows.
  5. Bucket list: city or region search, a min/max stay slider, and a priority for each entry.
  6. Preferences: weather tolerance, max stops, overnight layovers, Friday-evening departure and earliest departure time.
- **Dashboard:** the tracker overview, edit/snooze/unsnooze controls, and a bar showing PTO used vs. remaining.
- **Snooze endpoints:** `GET /s/{token}` takes a signed token that contains the user, tracker or candidate, and action. It expires after 30 days and needs no login. The confirmation page says "Snoozed ✓".
- **Render cold start:** the first request after idle takes about 30–60 s. This is acceptable for V1.

---

## 10. Error handling and operations

- Each stage writes a row to `pipeline_runs` (status, counts, error). Stages are idempotent per `run_date`: before re-inserting, a stage deletes or replaces the rows it previously produced for that date. `price_observations` is the exception: it is append-only, and a re-run only adds new observations.
- **Stage isolation:** `live_verify` failing completely still lets `baselines`, `score`, and the digest run on cached or unverified data. Failures in `expand` or `broad_scan` stop the downstream stages for that run.
- **Health email** to `ADMIN_EMAIL` after every scan. It reports:
  - per-stage status and duration
  - Travelpayouts call count
  - live checks ok/failed per source
  - circuit-breaker trips
  - SerpApi searches remaining this month
  - candidate count by deal level
- **Re-runs:** the GitHub Actions `workflow_dispatch` takes `date` and `stage` inputs.
- **Keepalive:** a monthly workflow commits `.keepalive`, so GitHub doesn't disable the cron.
- **Source drift:** any adapter parsing error raises `SourceUnavailable`, the error is logged together with the raw payload snippet, and the error is counted in the health email.

---

## 11. Testing

- **`core/`:** test-driven with pytest. Required cases:
  - US Thanksgiving, Memorial Day, and July 4 falling midweek
  - UK Easter (Good Friday + Easter Monday) and the August bank holiday (England vs. Scotland)
  - zero-PTO shapes and Friday-evening variants
  - stay limits after travel overhead, region minimum trip length, and diversity pruning
  - season majority month across a month boundary
  - the MAD-sigma floor, cold-start blending, and z/deal thresholds
  - the go-now formula
- **`sources/`:** tests run against recorded JSON/HTML fixtures, with no network calls in CI. A manual `pytest -m live` smoke test exists per adapter.
- **`pipeline/`:** integration tests against a disposable Postgres (Docker in CI), with fake `FareSource` implementations. They run the full chain from user inputs to candidates and check dedup, the circuit breaker, budget enforcement, and idempotent re-runs.
- **`digest/`:** snapshot tests of the rendered HTML and text, plus selection-rule tests (re-send on a 5% drop, the cap of 8, quiet-week behavior).
- **`web/`:** FastAPI TestClient tests for the auth flow, the invite gate, onboarding persistence, and snooze tokens (valid, expired, tampered).
- **CI:** `ci.yml` runs ruff and pytest (excluding `live`) on every push.

---

## 12. Known risks

| Risk | Mitigation |
|---|---|
| Google blocks `fast-flights` from GitHub Actions IPs | Circuit breaker → SerpApi budget → "unverified" labeling. If live checks fail persistently, revisit with a paid source (the `FareSource` swap point). |
| Travelpayouts cache is sparse for niche routes | Region-level month scans; the exploration quota sends some sparse routes to live checks. |
| Free-tier changes (Neon, Render, Resend, SerpApi) | Every external service sits behind config. A Docker Compose deployment on a $5 VPS is the fallback. |
| Cold-start baselines produce noisy deals | `low` confidence label plus Google typical-range blending. |
| GitHub Actions cron is delayed or disabled | Delay is acceptable. The keepalive workflow prevents disabling. |

---

## 13. V2

V2 items are tracked in [`ROADMAP.md`](../../../ROADMAP.md) and come up for consideration once V1 runs end to end.
