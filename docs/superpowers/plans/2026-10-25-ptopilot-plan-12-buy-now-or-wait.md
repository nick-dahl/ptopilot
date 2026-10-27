# ptopilot Plan 12: Buy Now or Wait

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every offer carries a more rigorous go-now score (the quality index) and an expected duration ("likely gone within ~N days"). Exceptional, short-lived offers stand out on the site and in the digest, and are emailed right away, at most once a day and never the same destination twice in a week.

**Architecture:**
- **Score stage:**
  - It judges deal depth against both the route-month baseline and the trip's own price history, keeping the less extreme of the two.
  - It caps the deal part for low-confidence or cached prices.
  - It stores `expected_days` per candidate, from past dips of the same depth.
- **Standout:** a pure predicate over a candidate's fields.
- **Alerts:** a new last pipeline stage, `alerts`, sends single-trip emails under the rate limits, logged in `alert_sends`.
- **Display:** the digest and the site read the stored fields.

**Tech Stack:** No new dependencies. Data comes only from `price_observations` (live checks and seeded `google_history`) and `candidates`.

**Spec:** [`docs/superpowers/specs/2026-10-25-ptopilot-buy-now-or-wait-design.md`](../specs/2026-10-25-ptopilot-buy-now-or-wait-design.md)

**Order:** runs after Plans 9–11 (the year plan). Its migration takes the next free revision number at that time; this plan calls it `00NN_buy_now_or_wait`.

## Global Constraints

- **Go-now keeps its name, 0–100 range and weights:** deal 0.5, weather 0.2, efficiency 0.15, length 0.1, timing 0.05.
- **Conservative depth:** with at least `TRIP_HISTORY_MIN = 10` daily points for the exact trip, deal z = **max**(route-month z, trip z), the less extreme one. A low-confidence baseline or an unverified price caps the deal part at **0.5** of its range.
- **Expected duration wording:**
  - ≤ 7 days → "likely gone within ~N days";
  - more → "likely to hold for a week or more";
  - fewer than `DURATION_MIN_DIPS = 2` past dips → "not enough history yet".
- **Standout** = go-now ≥ `STANDOUT_GO_NOW = 85` **and** deal level `great` **and** confidence `normal` **and** a verified price **and** expected_days ≤ `STANDOUT_MAX_DAYS = 3`.
- **Instant alerts:**
  - at most **1 per user per UTC day**;
  - never the same destination for a user within **7 days** (rolling);
  - a re-run never resends;
  - an alert does **not** count as "sent" for the digest's resend rule.
- **Alert subject (exact):** `Rare: {destination} {price} ({pct}% below typical) — likely gone within ~{n} days`.
- **Email:** inline styles, no web fonts, the existing digest look. The dramatic treatment appears **only** on standout offers.
- **Process:** migrations reach Neon before code that reads them deploys. Work on `main`; every task commits and pushes with the suite green. Never print or commit secrets. Default pytest never touches the network or sends email.

## Review Focus

1. **A trip with gaps in its price history** (missed scans, sparse history) → the duration counts dips only across consecutive days, and a gap ends a dip. *Task 2: `test_a_gap_ends_a_dip`.*
2. **Today's price is not below its trailing median at all** → no duration claim ("not enough history yet" is not right either). The candidate gets `expected_days = None`, and the label is omitted. *Task 2: `test_no_dip_today_means_no_duration`.*
3. **Departure is sooner than the typical dip length** → the duration is capped at the days left. *Task 2: `test_duration_is_capped_by_days_to_departure`.*
4. **Two standout offers for the same user on the same day, or a standout for a destination alerted 5 days ago** → one alert (the best go-now), and none for the recently alerted destination. *Task 4: `test_one_alert_a_day_picks_the_best`, `test_same_destination_waits_a_week`.*
5. **The scan is re-run the same day** → no second alert. *Task 4: `test_a_rerun_does_not_resend`.*
6. **The return check fails, so the next standout is tried** → the failed offer is skipped without using the day's alert slot, and at most `RETURN_CHECKS_PER_DAY` checks run a day. *Task 4: `test_a_failed_return_tries_the_next_standout`, `test_return_checks_are_capped`.*

---

## File structure

```
ptopilot/config.py                         # TRIP_HISTORY_MIN, DURATION_MIN_DIPS, DURATION_WINDOW_DAYS, STANDOUT_*, ALERT_*
ptopilot/core/scoring.py                   # deal_component(z, capped) + go_now(..., deal_capped=False)
ptopilot/core/duration.py                  # NEW: expected_days, duration_label
ptopilot/core/standout.py                  # NEW: is_standout
ptopilot/pipeline/score.py                 # trip-history z, caps, expected_days
ptopilot/pipeline/alerts.py                # NEW stage
ptopilot/pipeline/runner.py                # STAGES += alerts (last); CONTINUE_ON_FAILURE += alerts
ptopilot/db/models.py, migrations/00NN_buy_now_or_wait.py   # Candidate.expected_days; AlertSend
ptopilot/digest/select.py, render.py, templates/*           # duration line, standout look, alert email
ptopilot/web/history.py, templates/_components.html, destination.html, static/app.css   # site display
ROADMAP.md
```

New config (exact):
```python
TRIP_HISTORY_MIN = 10
DURATION_MIN_DIPS = 2
DURATION_WINDOW_DAYS = 30        # trailing median window for dip detection
DURATION_LONG_DAYS = 7           # above this: "likely to hold for a week or more"
STANDOUT_GO_NOW = 85
STANDOUT_MAX_DAYS = 3
ALERTS_PER_DAY = 1
ALERT_SAME_DESTINATION_DAYS = 7
```

---

### Task 1: Go-now v2 (conservative, confidence-aware deal part)

**Files:** Modify `ptopilot/core/scoring.py`, `ptopilot/pipeline/score.py`, `ptopilot/config.py`. Test `tests/core/test_go_now_v2.py`, `tests/pipeline/test_score_v2.py`.

**Interfaces:**
- Produces:
  - `deal_component(z: float | None, capped: bool = False) -> float`: as today, but at most 0.5 when `capped`.
  - `go_now(..., deal_capped: bool = False)`: a new keyword that passes through to `deal_component`.
  - `conservative_z(z_route: float | None, z_trip: float | None) -> float | None`: the max of the two when both exist, else whichever exists.
- In `pipeline/score.py`: per candidate, build the exact trip's daily-minimum series over the trailing `BASELINE_WINDOW_DAYS` from `price_observations` (all sources, `google_history` included). With at least `TRIP_HISTORY_MIN` points, compute a trip baseline with `compute_baseline` and its z. Store `z = conservative_z(...)`. Then `deal_level(z)`, and `go_now(..., deal_capped = confidence == "low" or not verified)`.

- [ ] **Step 1: Write the failing tests.**
```python
def test_capped_deal_part_is_at_most_half():
    assert deal_component(-2.5, capped=True) == 0.5 and deal_component(-2.5) == 1.0
def test_conservative_z_keeps_the_less_extreme():
    assert conservative_z(-2.0, -0.8) == -0.8 and conservative_z(-2.0, None) == -2.0 and conservative_z(None, None) is None
def test_a_cheap_trip_is_judged_against_its_own_history(make_ctx):
    # route-month baseline median 1000 sigma 50; the trip's own 20-day history ~700; live price 680
    # → stored z ≈ (680-700)/sigma_trip, not -6.4; deal_level not "great"
def test_unverified_or_low_confidence_prices_cannot_max_the_deal_part(make_ctx):
    # same z=-3 offer: verified + normal → go_now X; unverified (cached) → X - 25 (half of deal weight 0.5 × 100)
def test_without_trip_history_the_route_baseline_is_used(make_ctx): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(scoring): go-now judges depth conservatively and discounts thin evidence`).

---

### Task 2: Expected duration

**Files:**
- Create: `ptopilot/core/duration.py`, migration `00NN_buy_now_or_wait.py` (`candidates.expected_days SMALLINT NULL`; the `alert_sends` table for Task 4 goes in the same migration).
- Modify: `ptopilot/db/models.py`, `ptopilot/pipeline/score.py`.
- Test: `tests/core/test_duration.py`, `tests/pipeline/test_score_duration.py`.

**Interfaces:**
- Produces:
  - `expected_days(series: list[tuple[date, float]], today: date, today_price: float, days_to_departure: int) -> int | None`.
  - `duration_label(days: int | None, dips_found: bool = True) -> str | None`.
  - `Candidate.expected_days`.
  - `AlertSend(id, user_id FK, tracker_id FK, candidate_id FK SET NULL, run_date, sent_at)` with unique `(user_id, run_date)`.
- **Algorithm (the spec fixes the rules; this pins the edge cases):**
  - Depth today = `today_price / trailing_median − 1`, where the trailing median comes from the `DURATION_WINDOW_DAYS` before today. If today isn't below that median, return None.
  - A past dip is a maximal run of **consecutive calendar days** whose price is at least as far below its own trailing median as today's depth.
  - Its length is the number of days in the run. A missing day ends the run.
  - Return `min(median(dip lengths), days_to_departure)` when there are at least `DURATION_MIN_DIPS` past dips (excluding the current run). Otherwise return None, with the caller using `dips_found=False` for the "not enough history yet" label.

- [ ] **Step 1: Write the failing tests.**
```python
def test_typical_dip_length_is_the_estimate():  # history with dips of 2, 3, 4 days at today's depth → 3
def test_a_gap_ends_a_dip(): ...                # a dip interrupted by a missing day counts as two short dips
def test_no_dip_today_means_no_duration(): ...  # today's price at/above trailing median → None
def test_fewer_than_two_past_dips_is_not_enough_history(): ...  # → None; label "not enough history yet"
def test_duration_is_capped_by_days_to_departure(): ...         # typical 6, departure in 2 → 2
def test_labels():
    assert duration_label(1) == "likely gone within ~1 day" and duration_label(3) == "likely gone within ~3 days"
    assert duration_label(9) == "likely to hold for a week or more"
    assert duration_label(None, dips_found=False) == "not enough history yet" and duration_label(None) is None
def test_score_stores_expected_days(make_ctx): ...  # seeded google_history with clear dips → candidate.expected_days set
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** The score stage reuses Task 1's trip series and passes `(rq.depart_date - run_date).days`.
- [ ] **Step 4: Run the tests**, the full suite (the migration test included) and ruff.
- [ ] **Step 5: Migrate Neon before pushing** (the guarded snippet: `DATABASE_URL_UNPOOLED` from `.env.local` without printing it, throw if empty, `alembic upgrade head`, unset). **Step 6: Commit and push** (`feat(scoring): expected duration of each deal`).

---

### Task 3: Standout offers on the site and in the digest

**Files:**
- Create: `ptopilot/core/standout.py`.
- Modify: `ptopilot/digest/select.py` (`DealCard.expected_days`, `DealCard.standout`), `ptopilot/digest/render.py` and templates, `ptopilot/web/history.py` (`TripOption.expected_days`, `.standout`), `templates/_components.html`, `destination.html`, `static/app.css`.
- Test: `tests/core/test_standout.py`, `tests/digest/test_standout_digest.py`, `tests/web/test_standout_site.py`.

**Interfaces:**
- Produces: `is_standout(go_now: int, deal_level: str, confidence: str, verified: bool, expected_days: int | None) -> bool`.
- Every deal (digest) and trip option (site) shows its duration label under the price. Standout ones get a "Rare: likely gone within ~N days" tag and the standout accent.
- The digest's lead card is the best standout deal when there is one.

- [ ] **Step 1: Write the failing tests.**
```python
def test_standout_needs_every_condition():
    assert is_standout(90, "great", "normal", True, 2)
    for args in [(84, "great", "normal", True, 2), (90, "good", "normal", True, 2), (90, "great", "low", True, 2),
                 (90, "great", "normal", False, 2), (90, "great", "normal", True, 4), (90, "great", "normal", True, None)]:
        assert not is_standout(*args)
def test_digest_marks_standout_deals_and_leads_with_one(): ...  # "Rare: likely gone within ~2 days" present once; lead card is it
def test_ordinary_deals_get_the_duration_line_but_no_standout_look(): ...  # "likely gone within ~6 days", no "Rare:"
def test_site_shows_duration_and_the_standout_tag(client, ...): ...  # dashboard card + destination row
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** Keep within the design system and add no fixed inline styles to web templates (the polish test enforces this). The email uses inline styles as today. **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat: standout offers stand out`).

---

### Task 4: Instant alerts

**Files:**
- Create: `ptopilot/pipeline/alerts.py`, `ptopilot/digest/templates/alert.html.j2`, `alert.txt.j2`.
- Modify: `ptopilot/pipeline/runner.py` (`STAGES["alerts"]` last; add to `CONTINUE_ON_FAILURE`), `ptopilot/pipeline/health.py` (one line: alerts sent today), `ptopilot/pipeline/__main__.py` (`--dry-run` already skips the health email; it must also make `alerts` write the would-send list into its counts without emailing).
- Test: `tests/pipeline/test_alerts.py`.

**Interfaces:**
- Consumes: Task 3 `is_standout`; `pipeline.return_check.check_return` and `config.RETURN_CHECKS_PER_DAY` (from the skip-miserable-flights plan); `digest.select.build_digests(..., min_level="great", skip_sent=False)`, filtered to standout deals, or an equivalent query; `digest.render` helpers; `links.action_links`; `ctx.emailer`; `config.SOURCE_BUDGETS` untouched.
- Produces:
  - `alerts.run(ctx) -> dict[str, int]` with counts `standout`, `sent`, `held_daily_cap`, `held_same_destination`, `return_checks`, `return_failed`, `would_send` (dry run).
  - `render_alert(card: DealCard, links) -> (subject, html, text)` in `ptopilot/digest/render.py`.

- [ ] **Step 1: Write the failing tests** (a capturing fake emailer in `ctx`):
```python
def test_a_standout_offer_is_emailed_right_away(make_ctx): ...
    # one standout candidate today → one email; subject exactly
    # "Rare: Azores $520 (31% below typical) — likely gone within ~2 days"; an AlertSend row recorded
def test_one_alert_a_day_picks_the_best(make_ctx): ...      # two standouts → one email (higher go-now); held_daily_cap 1
def test_same_destination_waits_a_week(make_ctx): ...       # AlertSend for AZORES 5 days ago → none; 7 days ago → sent
def test_a_rerun_does_not_resend(make_ctx): ...             # run twice the same day → one email
def test_ordinary_great_deals_are_not_alerted(make_ctx): ... # go-now 80 or expected_days 5 → none
def test_dry_run_sends_nothing(make_ctx): ...               # ctx.dry_run → would_send 1, no email, no AlertSend
def test_alerted_offers_still_appear_in_the_next_digest(clean_engine): ...  # build_digests keeps it; not held back as sent
def test_alerts_stage_runs_last(): assert list(runner.STAGES)[-1] == "alerts"
def test_a_failed_return_tries_the_next_standout(make_ctx): ...  # fake check_return: "fail" for the best, "pass" for the next → the next is emailed; AlertSend is for it; return_failed 1
def test_an_unknown_return_still_sends(make_ctx): ...           # check_return → ("unknown", None) → emailed as before
def test_return_checks_are_capped(make_ctx): ...                # four standouts, all "fail" → exactly RETURN_CHECKS_PER_DAY checks, nothing sent, no AlertSend
def test_dry_run_lists_return_verdicts(make_ctx): ...           # ctx.dry_run → the would-send list carries each checked offer's verdict; still no email
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.**
  - Before sending, call `check_return` for the chosen candidate: `home` is the user's home airport, `from_airport` is the airport the return departs, `depart` is the return date, and `pct_below` and `confident` come from the offer's baseline.
  - On `"fail"`, skip the offer without using the day's alert slot, and try the next standout. Run at most `RETURN_CHECKS_PER_DAY` checks a day; count them in `return_checks` and the failures in `return_failed`.
  - On `"unknown"`, send as before.
  - In a dry run, list each checked offer's return verdict in the would-send output.
  - Emails go only to users who have active trackers.
  - Email addresses never appear in logs. Keep the digest's scrubbing pattern.
- [ ] **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5: Commit and push** (`feat(alerts): instant emails for rare, short-lived offers`).

---

### Task 5: Roadmap and a live check

- [ ] **Step 1:** In `ROADMAP.md`, mark "Buy now or wait" done (Plan 12), with a one-line description. Commit and push (`docs: roadmap after buy now or wait`).
- [ ] **Step 2 (controller):** Run the scan once by hand (`gh workflow run scan.yml`) with `--dry-run`, or check the next 06:00 run.
  - Read today's `score` and `alerts` counts from Neon (read-only, URL never printed).
  - Expected: candidates have `expected_days` where history allows, and `alerts` reports `standout` / `would_send` or `sent`.
  - Report the standout offers found, if any, to the user.
