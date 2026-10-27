# ptopilot Plan 12: Skip Miserable Flights

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every live-priced itinerary is judged on its longest layover, total travel time against the fastest option, and ground time from the landing airport.
- **Ruled out:** a severe problem, or two moderate ones. These itineraries never become deals: no email, no dashboard "best", no combination leg. The destination page shows them greyed out, with the reason.
- **Forgiven:** one moderate problem is shown only when the fare is at least 40% below typical, with a trade-off note.
- **Before an instant alert:** a ready-made function checks the flights home.

**Architecture:**
- **Pure judging** lives in `ptopilot/core/misery.py`: problems, the verdict and its copy.
- **Ground time** comes from `Geo`, using catalog coordinates and the destination's "own" airports.
- **The live sources** record each option's longest layover and its connection airport.
- **The score stage** picks the cheapest non-ruled-out option per trip, and stores the verdict and note on the candidate.
- **The return check** is a pipeline function, `check_return`, built on a one-way search that both sources gain. The buy-now-or-wait plan's alerts stage calls it.

**Tech Stack:** No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-10-26-ptopilot-skip-miserable-flights-design.md`](../specs/2026-10-26-ptopilot-skip-miserable-flights-design.md). It builds on Plans 9–11 (done). The buy-now-or-wait plan (`2026-10-25-ptopilot-plan-12-buy-now-or-wait.md`, now queued as Plan 13) is edited in Task 5 to call the return check.

## Global Constraints

- **Lines (exact), in one config block:**
  ```python
  MISERY_LAYOVER_MODERATE_MIN = 300   # longest layover > 5h is moderate
  MISERY_LAYOVER_SEVERE_MIN = 540     # > 9h is severe
  MISERY_DURATION_MODERATE = 1.4      # total travel >= 1.4x the fastest is moderate
  MISERY_DURATION_SEVERE = 2.0        # >= 2x is severe
  MISERY_GROUND_MODERATE_MIN = 60     # ground time >= 1h is moderate
  MISERY_GROUND_SEVERE_MIN = 120      # >= 2h is severe
  GROUND_KM_PER_HOUR = 65
  MISERY_FORGIVE_PCT = 40             # price <= 0.6 x the normal-confidence baseline median forgives ONE moderate problem
  RETURN_CHECKS_PER_DAY = 3
  ```
  - `MAX_DURATION_RATIO` (the old hard 1.5× rule) is removed; the duration problem replaces it.
- **Verdicts:**
  - `ok`: no problems.
  - `forgiven`: exactly one moderate problem, and the price qualifies.
  - `ruled_out`: anything else with a problem, including one moderate problem without a qualifying price, or without a `normal`-confidence baseline.
- **Unchanged and applied first:** stop caps, the overnight-layover preference and the Friday-evening rule.
- **"Fastest":** the fastest option among *all* of that day's live options for the same route and dates, before any filter.
- **Ground time:**
  - 0 for a destination's own airports;
  - otherwise the great-circle distance to the nearest own airport ÷ `GROUND_KM_PER_HOUR`, in minutes.
  - **Own airports:** every airport of a `geo.yaml` place; for a database place, the airports whose catalog city equals its first airport's city.
- **Copy (exact patterns):**

  | Problem | Pattern | Example |
  |---|---|---|
  | Layover | "{dur} layover in {city}" | "9h layover in Madrid", "6h 30m layover in Madrid" |
  | Layover, unknown city | "{dur} layover" | "9h layover" |
  | Total travel | "{h}h journey, {ratio:.1f}× the fastest" | "38h journey, 2.1× the fastest" |
  | Ground time | "Lands ~{dur} from {destination}" | "Lands ~1h 15m from Tokyo" |

  - `{dur}` is whole hours, or hours and minutes; ground minutes are rounded to the nearest 5.
  - Two problems are joined with " · ".
  - A forgiven note is the problem text plus " (worth it at {pct}% below typical)".
- **Ruled-out trips** appear only in the destination page's date list, greyed out with their reason. Every other reader ignores them: the digest, the dashboard "best", the price trend, the typical band, combinations and counts.
- **Searches:** the only new searches are return checks, at most `RETURN_CHECKS_PER_DAY` a day, and only from the alerts stage.
- **Migrations reach Neon before code that reads them deploys.**
- **Checks:** `ruff check .` and `ruff format --check .` pass. Database tests use `PTOPILOT_REQUIRE_DB=1`.
- **Workflow:** work on `main`, and every task ends with a commit and push. Commit messages end with a `Co-Authored-By:` line for the model that wrote them.
- **Secrets:** never print or commit them.

## Review Focus

1. **A trip whose every option is miserable:** it must never reach the email, dashboard or combinations. It still shows, greyed out with a reason, on the destination page.
   - *Task 3: `test_a_trip_with_only_miserable_options_is_recorded_ruled_out`. Task 4: `test_ruled_out_trips_reach_no_email_card_or_combination`.*
2. **A pricier acceptable option on the same dates:** a cheaper miserable option exists alongside a pricier acceptable one. The deal is the acceptable one, priced and scored at its own price.
   - *Task 3: `test_the_cheapest_acceptable_option_wins_over_a_cheaper_miserable_one`.*
3. **One moderate problem around the 40% line:**
   - 41% below typical (normal baseline) → forgiven, with a note;
   - 39% → ruled out;
   - 50% on a low-confidence baseline → ruled out.
   - *Task 2: `test_forgiveness_needs_forty_percent_on_a_normal_baseline`.*
4. **Missing data:** an option missing layover data, an unknown connection airport, or a destination airport missing from the catalog. Each is judged on what's known, never crashes, and never invents a problem.
   - *Task 2: `test_missing_details_never_count_as_problems`. Task 1: `test_sources_tolerate_missing_layover_fields`.*
5. **A built-in multi-airport place** (Tokyo HND+NRT): never penalized for landing at either. A user-added Rome with FCO+CIA: neither penalized. A ticked nearby airport 90 km out: about 1h 25m, so moderate.
   - *Task 2: `test_own_airports_have_no_ground_time`.*

---

## File structure

```
ptopilot/db/migrations/versions/0009_misery.py      # NEW: observation layover columns; candidate verdict + note
ptopilot/db/models.py
ptopilot/sources/base.py, google_flights.py, serpapi.py   # longest layover + airport; one-way search
ptopilot/pipeline/live_verify.py         # store the new fields
ptopilot/core/geo.py, ptopilot/data/__init__.py      # Destination.own_airports; Geo.ground_minutes
ptopilot/core/misery.py                  # NEW: Problem, Assessment, assess, copy
ptopilot/pipeline/score.py               # pick with misery; record ruled-out trips
ptopilot/web/history.py, ptopilot/web/planner_view.py, ptopilot/digest/select.py   # readers
ptopilot/web/templates/destination.html, _components.html; ptopilot/digest/templates/*
ptopilot/pipeline/return_check.py        # NEW: check_return
docs/superpowers/plans/2026-10-25-ptopilot-plan-12-buy-now-or-wait.md   # alerts call check_return
ptopilot/config.py
```

---

### Task 1: Record the longest layover

**Files:**
- Create: `ptopilot/db/migrations/versions/0009_misery.py`
- Modify: `ptopilot/db/models.py`, `ptopilot/sources/base.py`, `ptopilot/sources/google_flights.py`, `ptopilot/sources/serpapi.py`, `ptopilot/pipeline/live_verify.py`
- Test: `tests/db/test_migrations.py`, `tests/sources/test_google_flights.py`, `tests/sources/test_serpapi.py`, `tests/pipeline/test_live_verify.py`

**Interfaces:**
- Produces:
  - `FlightOption.longest_layover_min: int | None = None` and `FlightOption.longest_layover_airport: str | None = None`. These describe the longest single connection on the outbound journey; both are None for a nonstop or when unknown.
  - `PriceObservation.longest_layover_min` (SmallInteger, null) and `.longest_layover_airport` (String(3), null), stored by `live_verify.store_options`.
  - `Candidate.verdict` (String(9), server default `'ok'`, check `verdict IN ('ok', 'forgiven', 'ruled_out')`) and `Candidate.misery_note` (Text, null). They are added now so that one migration covers the plan; Task 3 fills them.
- Parsing:
  - **fast-flights:** for each consecutive segment pair, the gap is `next.departure − prev.arrival`, and its airport is `prev`'s arrival airport code.
  - **SerpApi:** use the item's `layovers` list (`duration` in minutes, `id` the airport code). When that's missing, compute the gaps from leg times.

- [ ] **Step 1: Write the failing tests**
  - `test_google_flights_records_the_longest_layover` (a 3-segment fixture with gaps of 2h and 7h → 420 and the second connection's airport).
  - `test_serpapi_records_the_longest_layover`, from `layovers`.
  - `test_sources_tolerate_missing_layover_fields`: a nonstop → None/None; a SerpApi item without `layovers` → computed from legs; malformed times → None, never an exception.
  - `test_live_verify_stores_layover_fields`.
  - `test_migration_0009_adds_columns`: the verdict check rejects `'meh'`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Migrate Neon before pushing.** Use the guarded `DATABASE_URL_UNPOOLED` snippet, then `alembic upgrade head`. Expected: `Running upgrade 0008 -> 0009`.
- [ ] **Step 6: Commit and push** (`feat: record each option's longest layover`).

---

### Task 2: Judge an itinerary

**Files:**
- Create: `ptopilot/core/misery.py`
- Modify: `ptopilot/core/geo.py`, `ptopilot/data/__init__.py`, `ptopilot/config.py`
- Test: `tests/core/test_misery.py`, `tests/core/test_geo.py`, `tests/test_data_loaders.py` (or wherever `load_geo` is tested)

**Interfaces:**
- Produces (`geo.py`):
  - `Destination.own_airports: tuple[str, ...]`. It defaults to `airports + return_airports`; `load_geo` sets it for database places per Global Constraints.
  - `Geo.ground_minutes(dest: Destination, airport: str) -> int | None`: 0 for own airports, None when either airport lacks catalog coordinates, else rounded minutes.
- Produces (`core/misery.py`):
  - `Severity = Literal["moderate", "severe"]`.
  - `@dataclass(frozen=True) class Problem: kind: Literal["layover", "duration", "ground"]; severity: Severity; text: str`.
  - `@dataclass(frozen=True) class Assessment: verdict: Literal["ok", "forgiven", "ruled_out"]; problems: tuple[Problem, ...]; note: str | None`. The note is the joined problem text, plus the forgiven suffix when forgiven.
  - `problems(*, longest_layover_min, layover_city: str | None, duration_min, fastest_min, ground_min, destination_name) -> tuple[Problem, ...]`: any `None` input gives no problem of that kind.
  - `assess(found: tuple[Problem, ...], *, price, typical_median: float | None, typical_confident: bool) -> Assessment`.
  - `format_duration(minutes: int) -> str`: "9h", or "6h 30m".

- [ ] **Step 1: Write the failing tests**
  - `test_layover_lines`: 300 → none, 301 → moderate, 541 → severe.
  - `test_duration_lines`: 1.39× → none, 1.4× → moderate, 2.0× → severe.
  - `test_ground_lines`: 59 → none, 60 → moderate, 120 → severe.
  - `test_verdicts`: no problems → `ok`; one severe → `ruled_out`; two moderate → `ruled_out` even at 60% below.
  - `test_forgiveness_needs_forty_percent_on_a_normal_baseline`: 41% → `forgiven` with "(worth it at 41% below typical)"; 39% → `ruled_out`; 50% unconfident → `ruled_out`; no typical → `ruled_out`.
  - `test_copy_patterns`: each exact example string from Global Constraints, and two problems joined with " · ".
  - `test_missing_details_never_count_as_problems`.
  - `test_own_airports_have_no_ground_time`:
    - TYO from HND or NRT → 0;
    - a database Rome with `airports=[FCO, CIA]` → both own;
    - a database place with a ticked airport 90 km away → 85 (90/65 h ≈ 83 min, rounded to the nearest 5);
    - an airport missing from the catalog → None.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement**, including the constants. Remove `MAX_DURATION_RATIO` only in Task 3, where its user goes.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: judge miserable itineraries`).

---

### Task 3: Score with the verdict

**Files:**
- Modify: `ptopilot/pipeline/score.py`, `ptopilot/config.py`
- Test: `tests/pipeline/test_score.py`

**Interfaces:**
- Consumes: Task 1 fields; Task 2 `problems`, `assess` and `Geo.ground_minutes`; the existing baselines lookup in `score.run`.
- Produces: `pick_option(options, user, evening_departure, *, judge: Callable[[PriceObservation], Assessment]) -> tuple[PriceObservation, Assessment] | None`.
  - It applies the existing stop, overnight and Friday-evening filters (with no duration ratio any more).
  - It returns the cheapest option whose verdict isn't `ruled_out`.
  - When every filtered option is ruled out, it returns the cheapest filtered option with its `ruled_out` assessment.
  - `None` only when no option passes the existing filters.
- `score.run`:
  - builds `judge` per link. Fastest is taken over all the route's live options for the run; the layover city comes from the catalog; ground time is to the link's destination; typical comes from the same baseline used for the deal.
  - stores `Candidate.verdict` and `Candidate.misery_note`.
  - A `ruled_out` candidate gets `deal_level='none'` and `go_now=0`.

- [ ] **Step 1: Write the failing tests**
  - `test_the_cheapest_acceptable_option_wins_over_a_cheaper_miserable_one`.
  - `test_a_trip_with_only_miserable_options_is_recorded_ruled_out`: verdict, note, `deal_level 'none'`.
  - `test_a_forgiven_option_keeps_its_deal_level_and_note`.
  - `test_a_slow_option_is_now_judged_not_dropped`: 1.6× at 45% below a normal baseline → forgiven; at 20% → ruled out.
  - `test_existing_filters_still_apply_first`: stops, overnight and Friday evening.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement**, and remove `MAX_DURATION_RATIO`.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: score with the miserable-flight verdict`).

---

### Task 4: Show it, and keep ruled-out trips out of deals

**Files:**
- Modify: `ptopilot/web/history.py`, `ptopilot/web/planner_view.py`, `ptopilot/digest/select.py`, `ptopilot/web/templates/destination.html`, `_components.html`, `ptopilot/digest/templates/digest.html.j2`, `digest.txt.j2`
- Test: `tests/web/test_destination_page.py`, `tests/web/test_history.py`, `tests/web/test_plan_page.py`, `tests/digest/test_select.py`, `tests/digest/test_render.py`

**Interfaces:**
- `TripOption` gains `verdict: str` and `misery_note: str | None`. `DealCard` gains `misery_note: str | None`.
- **The destination page's date list** keeps ruled-out rows, dimmed, with the note in place of "I booked this". Forgiven rows show the note in the fit-note style.
- **Everything else drops ruled-out candidates:**
  - `destination_summaries` "best";
  - the trend and typical band;
  - `build_digests` (deals and the tracker table's "best today");
  - the planner's combination legs.
- **Email cards** show a forgiven note under the PTO line, like fit notes, in HTML and text.

- [ ] **Step 1: Write the failing tests**
  - `test_destination_page_greys_out_ruled_out_rows_with_their_reason`.
  - `test_forgiven_rows_show_their_trade_off`.
  - `test_ruled_out_trips_reach_no_email_card_or_combination`: digest deals, the tracker-row best, dashboard best and combination legs.
  - `test_trend_and_typical_band_ignore_ruled_out_prices`.
  - `test_forgiven_note_renders_in_html_and_text_email`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: grey out miserable trips; notes for forgiven ones`).

---

### Task 5: The return check, ready for instant alerts

**Files:**
- Create: `ptopilot/pipeline/return_check.py`
- Modify: `ptopilot/sources/base.py`, `ptopilot/sources/google_flights.py`, `ptopilot/sources/serpapi.py`, `docs/superpowers/plans/2026-10-25-ptopilot-plan-12-buy-now-or-wait.md`, `ROADMAP.md`
- Test: `tests/pipeline/test_return_check.py`, `tests/sources/test_google_flights.py`, `tests/sources/test_serpapi.py`

**Interfaces:**
- `ExactQuery.one_way: bool = False`.
  - With it, the sources search only `origin → dest_airport` on `depart_date` (fast-flights `trip="one-way"` with one leg; SerpApi `type=2`).
  - `return_date` is then ignored. Pass the same date to keep the dataclass valid, or make it optional: the builder's choice, and either is fine.
- `ReturnVerdict = Literal["pass", "fail", "unknown"]`.
- `check_return(sources: Sequence[ExactSearchSource], *, home: str, from_airport: str, depart: date, destination: Destination, geo: Geo, catalog, price: float, typical_median: float | None, confident: bool) -> tuple[ReturnVerdict, str | None]`. It:
  - searches `from_airport → home` one-way on `depart`, with fast-flights first and SerpApi only as the fallback the caller supplies;
  - judges every option with `misery.problems`, where ground time is from the departure airport and fastest is among the return options;
  - forgives with the alert's round-trip `price` against `typical_median` and its confidence (changed in the final-review fix from a rounded pct);
  - returns `("pass", None)` if any option is `ok` or `forgiven`, `("fail", note of the cheapest option)` if all are ruled out, and `("unknown", None)` if every source raised `SourceUnavailable` or returned nothing.
  - Exactly one search is attempted per source.
- **Plan doc edit (buy-now-or-wait, Task 4 "Instant alerts"):** add these steps and tests, in that plan's own step style:
  - before sending, call `check_return` for the chosen candidate;
  - on `"fail"`, skip it without using the day's alert slot, and try the next standout, with at most `RETURN_CHECKS_PER_DAY` checks a day, counted in that stage's counts;
  - on `"unknown"`, send as before;
  - the dry-run output lists the return verdicts.
- **ROADMAP:** mark Plan 12 done, and note that buy-now-or-wait (Plan 13) now includes the return check.

- [ ] **Step 1: Write the failing tests**
  - `test_one_way_queries_reach_the_sources` (injected search fakes see one leg or `type=2`).
  - `test_return_passes_when_any_option_is_fine`.
  - `test_return_fails_with_the_cheapest_options_reason`.
  - `test_return_uses_the_round_trip_discount_to_forgive`.
  - `test_return_is_unknown_when_sources_fail`.
  - `test_return_check_makes_one_search_per_source`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement**, then edit the buy-now-or-wait plan and ROADMAP as above.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: return-flight check for instant alerts`).
