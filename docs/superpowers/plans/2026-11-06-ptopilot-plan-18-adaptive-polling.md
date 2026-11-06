# Adaptive Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every in-horizon trip gets a fresh live price every UTC day, on free sources, across three scan runs a day, with the misses rotating and visible.

**Architecture:** A new `freshness` module answers "when was this route query last fresh" from `live_checks`. The shortlist stops picking a capped subset and instead orders every in-horizon route query (not-fresh first, longest-waiting first; then SerpApi-only audits; then a capped set of hot second checks). `live_verify` works that list inside its time budget, skips only what this run already checked, and backs off when Google pushes back. `score` updates the day's candidates in place. The runner skips once-a-day stages on a day's later runs, the workflow runs three times a day, and the health email gains a freshness block and a yesterday-misses warning.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (Postgres `insert … on conflict`), Alembic, GitHub Actions cron, pytest against local Postgres.

**Spec:** `docs/superpowers/specs/2026-11-06-ptopilot-adaptive-polling-design.md`

## Global Constraints

- Free sources only; SerpApi budgets unchanged (`SOURCE_BUDGETS = {"serpapi": {"per_day": 8, "per_month": 250}}`).
- Every tunable number lives in `ptopilot/config.py` with a one-line "why" comment.
- The repo is public: no emails, keys or personal data in code, fixtures or commits (tests use `@example.com`).
- Migration `0017` reaches Neon **before** any code that reads it is pushed: the Task 1 implementer commits but does **not** push; the controller applies the migration to Neon, then pushes.
- Alert caps unchanged and per UTC day (`ALERTS_PER_DAY = 1`, `ALERT_SAME_DESTINATION_DAYS = 7`); the digest unchanged.
- Workflows keep `permissions: contents: read`, inputs via env, and the `!success()` "Report an interrupted run" step.
- Tests in the foreground with `timeout 300` / `timeout 900`, logged to a file; never two pytest runs at once; commit as soon as focused tests pass; stage by explicit path; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Decisions this plan makes (the spec left them to the builder)

- Runs at **06:00, 14:00 and 22:00 UTC**, one shared run date (the UTC day).
- **Once-a-day stages** on later runs: `expand`, `broad_scan`, `seed_history`, `related`, `gems`, `photos`, `prune` are skipped when the full pipeline runs and that stage already finished `ok` for the run date. `shortlist`, `live_verify`, `baselines`, `score`, `alerts` run every time.
- **Second checks** are capped (`SECOND_CHECKS_PER_RUN = 40`) and only for hot trips (near a deal, departing within 30 days, or volatile), so Google volume grows modestly, not by multiples.
- **Health email:** the day's first run always emails and carries the yesterday-misses warning; later runs email only when a stage failed, back-off triggered, or trips are still not fresh after the day's last run. *(Flag for the owner: three routine emails a day would be noise.)*
- **Back-off** watches failures *and* empty answers over the last 20 checks: at ≥ 60% the pause range doubles, at ≥ 85% the run stops live checking. Normal empty share is ~25–35% (2026-11-05: 56 of ~200), so 60% is a real signal.

## Review Focus

1. A trip checked by the 06:00 run must not be checked again first by the 14:00 run while other trips are still not fresh. → Task 2 `test_fresh_today_goes_after_every_not_fresh_trip`.
2. A day's later run must not wipe the `state='sent'` the digest set, nor null `alert_sends.candidate_id`. → Task 4 `test_rescoring_keeps_ids_and_sent_state`.
3. A later run must not re-run `broad_scan` (Travelpayouts calls) or republish gems. → Task 5 `test_once_a_day_stages_skip_on_a_later_run`.
4. A day where Google refuses everything must stop early and leave the rest for the next run, not burn the window. → Task 3 `test_backoff_stops_when_google_refuses`.
5. Trips Google can never price must not fire the yesterday warning. → Task 5 `test_unpriceable_trips_are_listed_not_warned`.

---

### Task 1: Freshness model (migration 0017 + `freshness` module)

**Files:**
- Create: `ptopilot/db/migrations/versions/0017_freshness.py`, `ptopilot/pipeline/freshness.py`
- Modify: `ptopilot/db/models.py` (`ShortlistEntry` reason check; `LiveCheck.route_specific`), `ptopilot/pipeline/live_verify.py` (`record_check` stores `route_specific`)
- Test: `tests/pipeline/test_freshness.py`

**Interfaces:**
- Produces:
  - `LiveCheck.route_specific: Mapped[bool]` (server default false); `record_check(..., route_specific: bool = False)`.
  - `ShortlistEntry.reason` allowed values `('deal', 'explore', 'audit', 'second')`.
  - In `ptopilot/pipeline/freshness.py`:
    - `last_fresh(s: Session, rq_ids: Iterable[int], before: datetime | None = None) -> dict[int, datetime]` — latest `checked_at` of an `ok` `purpose='trip'` live check per route query (any source), optionally only checks before `before`.
    - `fresh_on(s: Session, day: date) -> set[int]` — route query ids with an `ok` trip check on that run date (any source).
    - `google_fresh_on(s: Session, day: date) -> set[int]` — the same, counting only unbudgeted sources (not in `config.SOURCE_BUDGETS`).
    - `@dataclass(frozen=True) class DayFreshness: in_horizon: int; fresh: int; not_fresh: list[int]; unpriceable: list[int]; open_jaw_no_budget: list[int]; longest_wait_days: int`
    - `day_freshness(s: Session, day: date) -> DayFreshness` — over the day's in-horizon route queries (linked to an active tracker on that run date, departing within `LIVE_HORIZON_DAYS`): `unpriceable` = not fresh, ≥ 1 attempt that day, and every attempt `route_specific`; `open_jaw_no_budget` = not fresh open-jaw with no attempt; `not_fresh` = the rest not fresh; `longest_wait_days` = max over `not_fresh` of days since `last_fresh` (never fresh = days since the route query's first link, at least 1).

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_freshness.py` (fixtures from `tests/pipeline/conftest.py`; day `2026-11-05`):
  - `test_ok_no_flights_and_serpapi_count_as_fresh`: route A ok Google with 0 options, route B ok SerpApi, route C failed → `fresh_on == {A, B}`, `google_fresh_on == {A}`.
  - `test_last_fresh_ignores_failures_and_respects_before`.
  - `test_day_freshness_splits_unpriceable_and_open_jaw`: one fresh, one with two `route_specific` failures (unpriceable), one open-jaw never attempted, one round trip failed with an outage error (not_fresh) → counts 4 / 1 / `[stale]` / `[unpriceable]` / `[open_jaw]`.
  - `test_longest_wait_counts_days_since_last_fresh`: last fresh 2026-11-02 → `longest_wait_days == 3`.
  - `test_route_specific_failures_are_recorded` (live_verify): a fake source raising `SourceUnavailable(..., route_specific=True)` leaves a `LiveCheck` with `route_specific is True`.
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_freshness.py -q` — Expected: FAIL (`No module named ptopilot.pipeline.freshness`).
- [ ] **Step 3: Implement.** Migration `0017_freshness` (revises `0016_gems`): drop and recreate the `shortlist_entries` reason check with the four values; add `live_checks.route_specific BOOLEAN NOT NULL DEFAULT false`; downgrade reverses both. Model edits to match. The module's docstring states the spec's definition of fresh.
- [ ] **Step 4: Run** the test file, then `alembic upgrade head` locally and `tests/pipeline -q` — Expected: PASS.
- [ ] **Step 5: Commit, do not push** — `git add` the five files; message `freshness: what counts as a fresh live price (migration 0017)`. Report that the migration awaits Neon.

### Task 2: The shortlist orders every in-horizon trip

**Files:**
- Modify: `ptopilot/pipeline/shortlist.py`, `ptopilot/config.py`
- Test: `tests/pipeline/test_shortlist.py` (update tests whose cap/selection behavior intentionally changes; say which in the report)

**Interfaces:**
- Consumes: `last_fresh`, `fresh_on`, `google_fresh_on` (Task 1).
- Produces: shortlist rows for every in-horizon route query in check order, `reason` ∈ `deal|explore` (not fresh today), `audit` (fresh today only via SerpApi, round trip), `second` (fresh today, hot, at most `SECOND_CHECKS_PER_RUN`). Config: `SECOND_CHECKS_PER_RUN = 40`, `NEAR_DEAL_Z_MARGIN = 0.5`, `SOON_DAYS = 30`, `VOLATILE_CV = 0.15` (coefficient of variation of the trip's live prices over `BASELINE_WINDOW_DAYS`). `LIVE_CHECK_CAP` and `EXPLORATION_QUOTA` are removed (grep for other uses; `open_jaw_capacity` returns a large sentinel instead of the cap).

- [ ] **Step 1: Write the failing tests:**
  - `test_every_in_horizon_trip_is_shortlisted`: 200 in-horizon route queries → 200 non-`second` entries (no cap); beyond-horizon still excluded.
  - `test_longest_waiting_goes_first`: three not-fresh trips last fresh 3, 1 and never days ago → ranks never, 3, 1.
  - `test_promise_breaks_ties_within_the_same_wait`: two trips both last fresh yesterday, one with a cached deal (z ≤ `SHORTLIST_Z`) → the deal ranks first.
  - `test_fresh_today_goes_after_every_not_fresh_trip`: trip fresh at 06:00 today ranks after all not-fresh trips (Review Focus 1).
  - `test_serpapi_only_round_trips_are_audited_before_second_checks`.
  - `test_second_checks_are_hot_and_capped`: 60 fresh trips, 50 hot (last live price's route z ≤ `GOOD_DEAL_Z + NEAR_DEAL_Z_MARGIN`, i.e. a deal or close to one, or departing ≤ `SOON_DAYS`, or CV ≥ `VOLATILE_CV`) → exactly 40 `second` entries, near-deal first, then soonest, then most volatile; cold fresh trips get none.
  - Keep the existing open-jaw tests' intent: open-jaw trips nobody can price today are counted `open_jaw_unpriceable`, not queued.
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_shortlist.py -q` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** Keep `urgency`, priority weights and the deal z-score as the promise score; sort first-check entries by `(last_fresh or datetime.min, -promise, depart_date, id)` (`datetime.min` = never fresh, first). Volatility and near-deal use the trip's own verified observations in `BASELINE_WINDOW_DAYS` against its route baseline. Update the module docstring to the new rules.
- [ ] **Step 4: Run** the file plus `tests/pipeline -q` — Expected: PASS (other pipeline tests updated only where the cap was assumed; list them).
- [ ] **Step 5: Commit** — message `shortlist: every in-horizon trip, longest-waiting first`.

### Task 3: `live_verify` works the whole list, politely

**Files:**
- Modify: `ptopilot/pipeline/live_verify.py`, `ptopilot/config.py`
- Test: `tests/pipeline/test_live_verify.py`

**Interfaces:**
- Consumes: Task 2's ordered shortlist and reasons.
- Produces: counts keys `first_checks`, `second_checks`, `audits`, `already_fresh` (skipped first-check entries fresh by now), `checked_this_run` (skipped), `backoff_slowed` (0/1), `backoff_stopped` (remaining entries), plus the existing keys. Config: `BACKOFF_WINDOW = 20`, `BACKOFF_SLOW_SHARE = 0.6`, `BACKOFF_STOP_SHARE = 0.85`, `BACKOFF_PAUSE_FACTOR = 2.0`.

- [ ] **Step 1: Write the failing tests** (the file's fake sources and injected clock/sleep):
  - `test_skips_only_what_this_run_checked`: a `second` entry for a route checked ok at 06:00 is checked at 14:00; the same route listed twice in one run is checked once.
  - `test_a_deal_or_explore_entry_fresh_by_now_is_skipped`: fresh earlier today (any source) → counted `already_fresh`, not checked.
  - `test_backoff_slows_then_stops_when_google_refuses`: a source failing/empty on 13 of the last 20 → pauses use `LIVE_DELAY_S × 2`; at 18 of 20 → the run stops, `backoff_stopped` = remaining entries, and the stage is **not** failed if any check succeeded (Review Focus 4).
  - `test_no_success_at_all_still_fails_the_stage` (existing rule kept).
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_live_verify.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** Replace the same-day `checked` skip with: skip a route checked (any outcome) since this stage started in this run; for `deal`/`explore` also skip when `fresh_on(today)` contains it (re-read once at stage start, then updated as checks succeed). `audit` and `second` entries are always attempted when reached. A rolling window of the last `BACKOFF_WINDOW` attempts' outcomes (failed or empty = bad) drives back-off; route-specific failures count as bad but never trip the breaker (existing rule). Pass `route_specific=exc.route_specific` to `record_check`.
- [ ] **Step 4: Run** the file plus `tests/pipeline -q` — Expected: PASS.
- [ ] **Step 5: Commit** — message `live_verify: whole list, this-run skips, back-off`.

### Task 4: `score` updates the day's candidates in place

**Files:**
- Modify: `ptopilot/pipeline/score.py`
- Test: `tests/pipeline/test_score.py`

**Interfaces:**
- Produces: candidates keyed on `(tracker_id, route_query_id, run_date, evening_departure)` keep their `id` and `state` across a day's runs; rows the latest scoring no longer produces are deleted.

- [ ] **Step 1: Write the failing tests:**
  - `test_rescoring_keeps_ids_and_sent_state`: score, mark one candidate `state='sent'` and add an `AlertSend` pointing at another, add a cheaper verified observation, score again → same ids, `sent` kept, new price and z stored, `AlertSend.candidate_id` unchanged (Review Focus 2).
  - `test_rescoring_drops_candidates_no_longer_produced`: a candidate whose tracker is deactivated between runs is deleted.
  - `test_rescoring_uses_every_live_price_of_the_day`: the 06:00 price is cheaper than the 14:00 one → the candidate keeps the cheaper (the existing pick over the day's verified observations).
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_score.py -q` — Expected: the first test FAILS (ids change today).
- [ ] **Step 3: Implement.** Replace the initial `delete(Candidate)` with collecting rows and one `postgresql.insert(Candidate).on_conflict_do_update` on the unique constraint, updating every scored column but never `id` or `state` (`excluded`/`snoozed`/`sent` survive); then delete the run date's candidates whose key wasn't produced. Keep the existing counts.
- [ ] **Step 4: Run** the file plus `tests/pipeline tests/digest -q` — Expected: PASS.
- [ ] **Step 5: Commit** — message `score: update the day's candidates in place`.

### Task 5: Three runs a day, once-a-day stages, and the health email

**Files:**
- Modify: `ptopilot/pipeline/runner.py`, `ptopilot/pipeline/health.py`, `ptopilot/pipeline/__main__.py`, `.github/workflows/scan.yml`, `README.md` (the scan schedule line), `ROADMAP.md` (feature idea "Adaptive polling" → Done entry; §4 gets an "Adaptive polling (Plan 18)" polish block only if the review leaves minors)
- Test: `tests/pipeline/test_runner.py`, `tests/test_workflows.py`

**Interfaces:**
- Consumes: `day_freshness` (Task 1); Task 3's counts keys.
- Produces: `runner.ONCE_A_DAY = frozenset({"expand", "broad_scan", "seed_history", "related", "gems", "photos", "prune"})`; `run_pipeline(ctx, stages=None)` skips (status `skipped`, reason `already ran today`) an `ONCE_A_DAY` stage that has an `ok` `PipelineRun` for `ctx.run_date`, only when `stages is None`; `health.is_first_run(results) -> bool` (True when `expand` ran `ok` this run); `build_report` gains a "Freshness:" block; `send_report` emails per the rule below.

- [ ] **Step 1: Write the failing tests:**
  - `test_once_a_day_stages_skip_on_a_later_run` (Review Focus 3): run the full pipeline twice for one date with fake stages → the second run's `broad_scan`/`gems` results are `skipped` / `already ran today`; `score` ran both times. With `stages=["broad_scan"]` it runs again.
  - `test_health_report_shows_freshness`: lines `Fresh today: 250 of 260 in horizon (10 not yet)`, `Checks this run: 120 first, 30 second, 2 audit`, `Google: 4% failed, 27% empty` (and `back-off: slowed` when set).
  - `test_first_run_warns_about_yesterday`: yesterday had 12 not-fresh trips, longest wait 2 days → body `12 trips had no live price yesterday (longest: 2 days)` and subject ends `— 12 trips stale`.
  - `test_unpriceable_trips_are_listed_not_warned` (Review Focus 5): yesterday's only misses are unpriceable → line `Google can't price 3 trips`, no warning, subject `OK`.
  - `test_later_runs_email_only_on_trouble`: a later run with nothing failed, no back-off and before 22:00 → no email sent; with a failed stage → email sent; the 22:00 run with trips still not fresh → email sent. (The "last run" rule is `now.hour >= LAST_RUN_HOUR_UTC`, a config constant `= 22`, with `now: datetime | None = None` injected into `send_report` for tests; default `datetime.now(UTC)`.)
  - `test_scan_runs_three_times_a_day` (workflows): `on.schedule` crons equal `["0 6 * * *", "0 14 * * *", "0 22 * * *"]` (note PyYAML reads `on` as `True`).
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_runner.py tests/test_workflows.py -q` — Expected: new tests FAIL.
- [ ] **Step 3: Implement** the runner skip, the report block and email rule (the first run's subject keeps today's `OK`/`FAILED (...)` wording and appends the stale suffix), the three crons (keep `timeout-minutes: 75`, `concurrency` unchanged), the README schedule line, and the ROADMAP Done entry: "**Adaptive polling:** every in-horizon trip gets a live price every day across three scan runs (06:00, 14:00, 22:00 UTC), longest-waiting first, hot trips get a second check, Google back-off, and freshness in the health email (Plan 18)." — and remove the "Adaptive polling" feature-idea line.
- [ ] **Step 4: Run** the two files, then the full suite `timeout 900 .venv/Scripts/python -m pytest -q -p no:randomly` — Expected: PASS.
- [ ] **Step 5: Commit** — message `scan: three runs a day, once-a-day stages, freshness in the health email`.

**Deploy note (controller):** after Task 1, apply migration 0017 to Neon with the guarded `DATABASE_URL_UNPOOLED` snippet, then push. After Task 5, watch the next three runs' health emails (or `pipeline_runs`) for freshness, back-off and run durations, and report them to the owner.
