# ptopilot — V2 "Better Price Data" Design Spec

**Date:** 2026-10-18
**Status:** Draft, awaiting review
**Builds on:** [V1 spec](2026-10-16-ptopilot-design.md) §7 (pipeline) · **Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) "Data quality"

---

## 1. Purpose and success criteria

**Problem.** Deals need a confident baseline: at least `COLD_START_N` (15) observations per (origin, airport, month, length bucket). After two days of scanning, all 30 baselines are low-confidence with at most 4 observations, so no deal can be flagged for 2–3 more weeks. Coverage is also thin:
- About 28 in-range routes go unchecked each day because of the 40-check cap.
- A fast-flights parse error tripped the Google breaker on 2026-10-18.
- Travelpayouts contributes nothing for this traveler's routes: 2 fares in two days.

**Findings that shaped this design (probed 2026-10-18):**
- **Travelpayouts "to anywhere":**
  - From NYC/JFK/EWR in March 2027 it returns about 100 fares to 59 destinations, none of them PDL, FNC, PUQ or OPO.
  - October 2027 returns 10 fares in total.
  - Exact NYC→PDL/FNC/PUQ queries return 0 in every month tried.
  - The cache only holds recently searched routes, so it can't serve niche destinations 5–11 months out.
- **SerpApi round-trip results include Google's own history:** `price_insights.price_history`, about 61 daily `[unix_ts, price]` points for the exact searched dates. This is in the real recording `tests/sources/fixtures/real_serpapi_ORD_LIS_2027-06-12_2027-06-20.json`. Multi-city (open-jaw) results don't include it.

**This release delivers:**
1. **History seeding:** one SerpApi call gives a baseline about 60 data points.
2. **Full daily coverage:** every in-range route gets a Google check every day.
3. **Breaker fix:** route-specific fast-flights parse failures no longer trip the breaker.
4. **Audit:** the health email compares fast-flights against SerpApi on the same trips.
5. **Travelpayouts:** it stops scanning pairs that never return anything.

**Successful when:**
1. Within about a week of deploying, every in-range round-trip baseline key for the author's trackers reaches `normal` confidence.
2. Each daily scan live-checks every shortlisted in-range route, unless a source outage trips the breaker.
3. A parse failure on one route never disables Google for the rest of the run.
4. The health email shows the fast-flights vs SerpApi comparison, both for today and for the last 30 days.
5. There's still no paid service. SerpApi stays within 8 calls/day and 250/month.

**Non-goals:** changing the live source order, adaptive polling, "buy now or wait", paid sources.

---

## 2. History seeding

### 2.1 Source

- `ExactResult` gains `price_history: tuple[tuple[date, float], ...] = ()`.
- `serpapi.parse_google_flights` fills it from `price_insights.price_history`. Each `[ts, price]` becomes `(UTC date of ts, float(price))`. Points that aren't numeric are skipped, and any missing structure yields `()`.
- fast-flights results always have `()`.

### 2.2 Stage `seed_history`

- **Position:** runs after `shortlist` and before `live_verify`. The stage order becomes expand → broad_scan → shortlist → seed_history → live_verify → baselines → score.
- **Skipped (StageSkipped)** when no configured live source can return history (no SerpApi).

**Keys to seed:** today's route queries that meet all of these:
- round trip (`return_airport == dest_airport`);
- departure within `LIVE_HORIZON_DAYS`;
- the baseline key `rq_baseline_key(rq)` has no `route_baselines` row with confidence `normal`;
- the key isn't already *seeded* (§2.4).

**Representative trip per key:** among that key's route queries, the one linked to the highest-priority tracker (lowest `priority` value), then the earliest departure, then the lowest id.

**Order of keys:** tracker priority, then earliest departure, then key.

**Budget:**
- The stage may make `max(0, remaining_today("serpapi") − SEED_RESERVE_FOR_OPEN_JAW)` calls, where `SEED_RESERVE_FOR_OPEN_JAW = 2`.
- It uses the existing `Budget` class (`allows`, `charge`, `remaining_today`).
- Every attempted call is charged and recorded in `live_checks` (source `serpapi`), so same-day re-runs and the daily and monthly caps work exactly as they do in `live_verify`.

**Per call:**
- Run `exact_search(ExactQuery(...))` on the SerpApi source.
- On `SourceUnavailable`, record the failed check, count it, and continue. Three consecutive failures stop the stage, which is the same breaker rule.

**On success:**
1. Store `result.options` as verified observations, exactly like `live_verify._store`. Share that function rather than copying it.
2. Store each history point as a `PriceObservation`:
   - `source = "google_history"`, `verified = False`;
   - `observed_at` = noon UTC on the point's date;
   - `month = month_of(depart_date)`;
   - route and date fields from the route query;
   - `currency = result.currency`;
   - no carrier, stops, links or typical range.
   - Points outside the trailing `BASELINE_WINDOW_DAYS + 1` days are dropped.
3. Record the `live_checks` row with `ok = True` and `options = len(result.options)`.

**Same-day re-run:** a route query already checked successfully by `serpapi` today isn't called again.

**Counts:** `keys_needing_seed`, `seeded`, `no_history`, `serpapi_failed`, `budget_exhausted`, `points_stored`, `options_stored`.

### 2.3 Keeping history out of prices shown to users

- `queries.cached_prices` ignores observations with `source = "google_history"`. Cached estimates feed the shortlist and the score stage's unverified fallback; history must never become a candidate price.
- `baselines` uses history like any other observation. Its existing cheapest-per-trip-per-day rule applies.

### 2.4 "Seeded" and retries

- **Seeded:** a key counts as seeded when any `google_history` observation exists for a trip in that key, with `observed_at` in the last `BASELINE_WINDOW_DAYS`.
- **Seed returned no history:** the key is *tried*, and its route query has a successful `serpapi` `live_checks` row. It's skipped until `SEED_RETRY_DAYS = 30` days after that check.
- **History ages out:** a key seeded more than `BASELINE_WINDOW_DAYS` ago whose baseline is still low-confidence has had its history expire, and qualifies again.

### 2.5 Budget interplay with `live_verify`

- `live_verify` keeps its open-jaw reservation logic unchanged. After seeding has used its share, the remaining calls (at least 2) go to open-jaw routes, as today.
- When nothing needs seeding, the stage makes no calls and Camino gets the full 8.

---

## 3. Coverage and the crash

### 3.1 Cap

- `LIVE_CHECK_CAP = 150`, a safety ceiling well above today's ~69 in-range routes (~138 once October is in range).
- Shortlist ordering and `EXPLORATION_QUOTA` are unchanged.
- `.github/workflows/scan.yml` `timeout-minutes` goes from 45 to 75. Pacing (`LIVE_DELAY_S`) is unchanged.

### 3.2 Route-type vs outage-type failures

- `SourceUnavailable` gains `route_specific: bool = False`.
- `google_flights` raises it with `route_specific=True` when fast-flights' result parsing raises `TypeError`, `IndexError` or `KeyError`.
  - Those are the errors seen in production: `'NoneType' object is not subscriptable`, `list index out of range`.
  - Timeouts, HTTP and network errors stay `route_specific=False`.
- In `live_verify`, a route-specific failure is recorded in `live_checks` as today, but it doesn't increment `consecutive_failures`, and it doesn't reset it either. The next source (SerpApi) is still tried, subject to the budget and open-jaw reservation.
- **Count:** `google_flights_route_failed`, distinct from `google_flights_failed`.
- **Before implementing:** the plan captures a real failing PHL→PUQ fast-flights response.
  - If the failure means Google simply has no itineraries, `google_flights` returns an empty `ExactResult` (no flights) instead.
  - Otherwise the route-specific error above applies.

---

## 4. Fast-flights vs SerpApi audit

- A health-report section built from `price_observations`. It needs no new table.
- **Pairs:** for each (trip, run date) where both `google_flights` and `serpapi` stored verified observations, compare the minimum price of each.
  - The trip is (origin, dest_airport, return_airport, depart_date, return_date).
  - The run date is the UTC date of `observed_at`.
- **Today's section:**
  ```
  Audit (fast-flights vs SerpApi, today): N trips — cheaper X, equal Y, pricier Z
    median gap +$G (+P%), worst +$W (+Q%): JFK→PDL Mar 5–14 ($740 vs $603)
  ```
  - "Equal" means within `AUDIT_EQUAL_USD = 5`.
  - A positive gap means fast-flights was pricier.
  - With no pairs, it says `Audit: no trips priced by both sources today`.
- **A 30-day line:** the same counts and median gap over the last 30 run dates.

---

## 5. Travelpayouts pruning

- `broad_scan` skips an (origin, dest_airport) pair when that pair's month scans returned zero fares on each of the last `TP_EMPTY_DAYS = 7` distinct scan days. Every 7th day it scans anyway, as a re-probe.
- **Recording:** a scan currently stores nothing when it returns nothing. Each scan now records `live_checks`-style evidence in a minimal new table `month_scans`:

  | Column | |
  |---|---|
  | `run_date` | date |
  | `origin`, `dest_airport` | char(3) |
  | `month` | date |
  | `quotes` | int |

  - Primary key: (`run_date`, `origin`, `dest_airport`, `month`). Migration 0006.
- **Re-probe rule:** a pair is re-probed when `(run_date − first empty day).days % 7 == 0`, or when it has fewer than 7 recorded scan days.
- **Count:** `skipped_empty_pair`.

---

## 6. Testing

- **Source:**
  - parse `price_history` from the real recording (61 points, dates ascending, last price 1098);
  - malformed or missing structure gives `()`;
  - multi-city gives `()`.
- **Seeding:**
  - Key selection: skips seeded keys, out-of-horizon trips, open-jaw trips, normal-confidence keys, and keys tried within 30 days.
  - The representative trip follows tracker priority.
  - The budget leaves 2 for open-jaw.
  - Observations are stamped with each point's date, and points outside the window are dropped.
  - After seeding plus the baseline stage, the key reaches normal confidence.
  - `cached_prices` ignores history, and score never uses history as a candidate price.
  - A same-day re-run makes no new calls.
  - Failures stop the stage after 3 in a row.
- **Coverage:**
  - The shortlist takes about 140 routes when the cap allows.
  - Route-specific errors don't trip the breaker, outage errors still do, and SerpApi fallback still happens after a route-specific Google failure.
  - Includes the captured fixture.
- **Audit:** report lines for cheaper, equal and pricier, a worst-gap line, the empty state, and the 30-day line.
- **Travelpayouts:** pairs empty for 7 days are skipped, the re-probe happens on the 7th day, and a non-empty scan resets the count. Migration 0006 upgrades and downgrades cleanly.
- **Workflow test:** `scan.yml` timeout-minutes is 75.

---

## 7. Rollout

- Commit and push to `main` at each step.
- Migration 0006 (`month_scans`) runs from `scan.yml` (`alembic upgrade head`). The web app doesn't read it, so deployment order doesn't matter.
- After deploying:
  - watch two scan health emails: the seed counts, the audit section, and `google_flights_route_failed`;
  - check on Neon that baselines move to `normal`.
- ROADMAP:
  - close "Broad scan by city, 'to anywhere'" as tested and not useful for niche routes, with the numbers above;
  - close "Check fast-flights for completeness", which this audit replaces;
  - add "History seeding" as done.
