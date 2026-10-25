# ptopilot Plan 10: The Planning Year

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A traveler plans a year on one page, `/plan/{year}`:
- a 12-month calendar with holidays and weekends, where they drag open the ranges they can travel;
- a trip list with each destination's target days away and estimated PTO;
- a bottom line of trips, days away and PTO against the year's PTO;
- a "Start planning {year}" flow that carries trips over and resets ranges.

The daily scan searches each trip only in its own year's open ranges, against that year's PTO.

**Architecture:**
- **Planning years:** a new `planning_years` table holds each user's PTO and "other time off" per year. A new `planned_trips` table says which destinations (trackers) are planned in which year.
- **Open ranges** are the existing `travel_windows` rows. A range belongs to the planning year its start date falls in.
- **The target** stays on the tracker (Plan 9), shared by every year the destination is planned in.
- **Pure logic** lives in `ptopilot/core/yearplan.py`:
  - range merging;
  - the month grid;
  - the "won't fit" allocation.
- **Database actions** live in `ptopilot/planning.py`.
- **Page context** is built in `ptopilot/web/planner_view.py`, and the routes go in `app.py` as today.
- **Drag-to-select** is one plain static JavaScript file that rewrites the same range rows the no-JavaScript form posts.

**Tech Stack:** No new dependencies. Plain JavaScript in `ptopilot/web/static/planner.js`: no framework, no build step.

**Spec:** [`docs/superpowers/specs/2026-10-25-ptopilot-year-plan-design.md`](../specs/2026-10-25-ptopilot-year-plan-design.md):
- §3.1 one trip per destination per year;
- §3.2 open ranges;
- §3.3 bottom line;
- §3.7 the "Building price history" note;
- §3.8 new year;
- §4 existing travelers and JavaScript.

**Left to Plan 11:**
- booking (booked trips counting their real PTO and leaving the watch);
- fit warnings on deals;
- combinations;
- the email banner.

Plan 11 adds its booked-trip fields to `planned_trips`.

## Global Constraints

- **Days away:** a trip qualifies at `target_days ± TARGET_TOLERANCE_DAYS` (= 2), never shorter than the route's `min_trip_days`. This was Plan 9's rule and is unchanged.
- **One trip per destination per year:** `planned_trips` is unique on `(tracker_id, year)`, and `trackers` becomes unique on `(user_id, destination_code)`.
- **Year of a range:** the year of its `start_date`. **Year of a trip:** the year of its departure date.
- **PTO available to plan a year** = `planning_years.pto_days − planning_years.other_time_off` (Plan 11 also subtracts booked trips).
- **Soft limits only:** planned trips exceeding PTO get a note. Tracking is never reduced because of it.
- **Scoping:** every new route acts only on the signed-in user's own years, ranges and trackers. Anything else is a 404.
- **Security:** state changes are POST forms under the existing session and SameSite=Lax cookie. The calendar works without JavaScript.
- **Migrations reach Neon before code that reads them deploys** (Render auto-deploys `main`).
- **Profile YAML:** `python -m ptopilot.profiles load` keeps working with its current fields.
- **Checks:** `ruff check .` and `ruff format --check .` pass. Database tests use `PTOPILOT_REQUIRE_DB=1`.
- **Workflow:** work on `main`. Every task ends with a commit and push, and the full suite stays green.
- **Commits:** messages end with a `Co-Authored-By:` line for the model that wrote them.
- **Secrets:** never print or commit them.

New config constants (exact values):
```python
PLAN_YEARS_AHEAD = 1             # a new planning year may be this year or up to 1 year ahead
PLAN_NEXT_YEAR_FROM_MONTH = 10   # from October on, "Start planning" defaults to next year
MAX_PTO_DAYS = 365
EXTRA_RANGE_ROWS = 2             # blank range rows on the no-JavaScript form
```

## Review Focus

1. **Messy ranges:** overlapping or touching ranges, a row whose end comes before its start, or a range starting outside the year (typed in the fallback rows, or a tampered POST).
   - Overlapping and touching ranges are merged.
   - Bad rows get a 400 page that names the row.
   - Never a 500.
   - *Task 2: `test_set_ranges_merges_overlaps_and_touching`, `test_set_ranges_rejects_a_range_outside_the_year`. Task 5: `test_saving_a_reversed_range_is_a_400_naming_the_row`.*
2. **A double-submitted "Start planning 2028"** (two tabs, double click) → the second submit redirects to the existing year. It is not an IntegrityError 500.
   - *Task 2: `test_starting_a_year_twice_is_a_no_op`. Task 6: `test_posting_start_twice_redirects_to_the_year`.*
3. **A trip planned only in 2027** must not be searched in 2028's ranges. Each year's search uses that year's PTO.
   - *Task 3: `test_a_trip_is_searched_only_in_its_years_ranges`, `test_each_years_pto_limits_its_own_trips`.*
4. **Existing travelers after the migration:** their trackers keep being searched (seeded into planned trips), with targets set from their stay ranges.
   - *Task 1: `test_migration_seeds_planning_years_and_trips_from_windows`. Task 2: `test_convert_targets_sets_the_midpoint_of_days_away`.*
5. **Another user's year, tracker or range** in any `/plan` URL or form → a 404. Nothing changes.
   - *Task 5: `test_plan_routes_are_scoped_to_the_signed_in_user`.*

---

## File structure

```
ptopilot/db/migrations/versions/0007_planning_years.py   # NEW: tables, unique trackers, seed from windows
ptopilot/db/models.py                    # PlanningYear, PlannedTrip; Tracker unique (user_id, destination_code)
ptopilot/core/yearplan.py                # NEW: merge_ranges, month_grid, allocate_pto (pure)
ptopilot/planning.py                     # NEW: year/range/trip actions + `convert-targets` CLI
ptopilot/core/planner.py                 # estimate_pto
ptopilot/pipeline/expand.py              # per-year windows and PTO, only planned trips
ptopilot/destinations.py                 # adding a place plans it in the open years
ptopilot/profiles.py                     # YAML load also writes planning years + planned trips
ptopilot/web/planner_view.py             # NEW: builds the planner page context
ptopilot/web/app.py                      # /plan routes, onboarding redirect, dashboard PTO bar
ptopilot/web/forms.py, templates/profile.html          # profile keeps traveler settings only
ptopilot/web/history.py                  # building_history on summaries
ptopilot/web/templates/plan.html, plan_new.html        # NEW
ptopilot/web/templates/base.html, dashboard.html, _components.html
ptopilot/web/static/planner.js, app.css               # NEW JS; calendar styles
ptopilot/config.py
```

---

### Task 1: Schema: planning years, planned trips, one tracker per destination

**Files:**
- Create: `ptopilot/db/migrations/versions/0007_planning_years.py`
- Modify: `ptopilot/db/models.py`
- Test: `tests/db/test_migrations.py`, `tests/db/test_models.py`

**Interfaces:**
- Produces: models `PlanningYear(user_id, year, pto_days, other_time_off, created_at)` with primary key `(user_id, year)`, and `PlannedTrip(id, user_id, year, tracker_id, created_at)`.
  - Constraints: unique `(tracker_id, year)` and `ck "pto_days >= 0 AND other_time_off >= 0 AND other_time_off <= pto_days"`.
  - Foreign keys: `user_id → users ON DELETE CASCADE`, `tracker_id → trackers ON DELETE CASCADE`.
  - `Tracker` gains `UniqueConstraint("user_id", "destination_code")`.

- [ ] **Step 1: Write the failing tests**
  - `test_migration_seeds_planning_years_and_trips_from_windows`:
    - Before 0007, set up a user with `pto_days_total=15`, `pto_committed=2`, windows 2027-03-01..03-21 and 2027-10-01..10-21, plus one in 2028.
    - Add two active trackers and one inactive tracker.
    - After upgrade:
      - `planning_years` has (2027, 15, 2) and (2028, 15, 2);
      - `planned_trips` has each **active** tracker in 2027 and in 2028 (4 rows);
      - the inactive tracker has none.
  - `test_migration_downgrade_drops_the_new_tables`.
  - `test_trackers_are_unique_per_user_and_destination`: a second `Tracker` with the same `(user_id, destination_code)` raises `IntegrityError`.
  - `test_planned_trip_is_unique_per_tracker_and_year`.
  - `test_other_time_off_cannot_exceed_pto_days`.
- [ ] **Step 2: Run them.** Expected: FAIL (no revision 0007, no models).
- [ ] **Step 3: Write models and migration 0007** (`down_revision = "0006"`).
  - The seed is plain SQL in the migration, with no app imports:
    - one `planning_years` row per (user, distinct `extract(year from start_date)` of their windows);
    - one `planned_trips` row per (active tracker, each of those years).
  - Before adding the trackers unique constraint, the migration counts duplicate `(user_id, destination_code)` pairs. If there are any, it raises `RuntimeError` naming the count, with nothing changed.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Migrate Neon before pushing.**
  - Run the guarded PowerShell snippet as in Plans 7 and 9: read `DATABASE_URL_UNPOOLED` from `.env.local` without printing it, throw if it's empty, run `alembic upgrade head`, then remove the variable.
  - Expected: `Running upgrade 0006 -> 0007`. If the duplicate check raises, stop and report: don't edit production data.
- [ ] **Step 6: Commit and push** (`feat: planning years and planned trips`).

---

### Task 2: Year logic and actions

**Files:**
- Create: `ptopilot/core/yearplan.py`, `ptopilot/planning.py`
- Modify: `ptopilot/config.py`
- Test: `tests/core/test_yearplan.py`, `tests/test_planning.py`

**Interfaces:**
- Consumes: Task 1 models; `ptopilot.destinations.remove_destination(s, user, tracker_id) -> bool` (Plan 9).
- Produces (pure, `core/yearplan.py`):
  - `merge_ranges(ranges: Iterable[tuple[date, date]]) -> list[tuple[date, date]]`: sorted, with overlapping **and touching** ranges (end + 1 day == next start) merged.
  - `month_grid(year: int, month: int) -> list[list[date | None]]`: weeks start on **Sunday**, `None` pads the first and last weeks.
  - `allocate_pto(trips: Sequence[tuple[int, int | None]], available: int) -> dict[int, int | None]`: takes `(key, est_pto)` pairs in planner order. It returns, for each trip that doesn't fit, `n` = the PTO left after the earlier trips (never below 0). A trip that fits has no entry. A `None` estimate never "doesn't fit".
- Produces (`ptopilot/planning.py`, each takes a `Session` and acts only on the given user's rows):
  - `planning_years(s, user) -> list[PlanningYear]`, oldest first.
  - `current_year(s, user, today: date) -> PlanningYear | None`: the earliest year ≥ `today.year`.
  - `default_new_year(s, user, today) -> int`:
    - one past the user's latest year;
    - with no years, `today.year + 1` when `today.month >= PLAN_NEXT_YEAR_FROM_MONTH`, else `today.year`.
  - `start_year(s, user, year, pto_days, other_time_off, carry_tracker_ids: Iterable[int]) -> PlanningYear`:
    - creates the year and planned trips for the carried trackers that are the user's own and active;
    - is a no-op returning the existing row if the year exists;
    - raises `ValueError` if the year is outside `today.year .. today.year + PLAN_YEARS_AHEAD`, or the PTO is outside `0 ≤ other ≤ pto ≤ MAX_PTO_DAYS`. The caller passes `today`; add it as a keyword `today: date`.
  - `set_year_pto(s, user, year, pto_days, other_time_off) -> None` (same validation).
  - `year_ranges(s, user, year) -> list[tuple[date, date]]`.
  - `set_ranges(s, user, year, ranges) -> list[tuple[date, date]]`:
    - validates every range: `start <= end`, and `start.year == year`;
    - raises `ValueError(f"range {i + 1}: …")` naming the 1-based row;
    - merges, then replaces that year's `travel_windows` (rows whose `start_date` is in that year) and returns the saved list.
  - `year_trackers(s, user, year) -> list[Tracker]`: active trackers planned in that year, by `priority` then `id`.
  - `plan_trip(s, user, tracker, year) -> None`: idempotent.
  - `unplan_trip(s, user, tracker_id, year) -> bool`:
    - deletes the planned trip;
    - if the tracker is then planned in no year ≥ `today.year`, deactivates it via `remove_destination`;
    - takes `today: date`, and returns False when the tracker isn't the user's.
  - `set_target(s, user, tracker_id, target_days) -> bool`: 2..60, else `ValueError`. It updates `tracker.target_days` and the stay range the same way `add_destination` does.
- Produces (CLI): `python -m ptopilot.planning convert-targets [--dry-run]` → `convert_targets(s, geo) -> int`.
  - For every tracker with `target_days IS NULL`, it sets `target_days = clamp(floor((min_stay + max_stay) / 2 + overhead + 0.5), 2, 60)`.
  - `overhead` is `geo.travel_rule(user.home_airport, dest).overhead_days`, and trackers whose destination doesn't resolve are skipped.
  - It returns the count changed and prints `converted N trackers`.

- [ ] **Step 1: Write the failing tests**
  - `test_merge_ranges_merges_overlaps_and_touching`: `[(Mar 10, Mar 20), (Mar 1, Mar 9), (Mar 15, Mar 25), (Oct 1, Oct 5)]` → `[(Mar 1, Mar 25), (Oct 1, Oct 5)]`.
  - `test_month_grid_starts_weeks_on_sunday`: `month_grid(2027, 3)[0]` == `[None, date(2027,3,1), …, date(2027,3,6)]` (Mar 1 2027 is a Monday), and every week has 7 cells.
  - `test_allocate_pto_marks_trips_past_the_limit`: `allocate_pto([(1, 5), (2, 6), (3, 9), (4, None)], 15)` == `{3: 4}`.
  - `test_set_ranges_merges_overlaps_and_touching`, and that it leaves another year's windows alone.
  - `test_set_ranges_rejects_a_range_outside_the_year`: a 2028 start in year 2027 → `ValueError` containing `"range 1"`.
  - `test_starting_a_year_twice_is_a_no_op`.
  - `test_start_year_carries_only_the_users_active_trackers` (another user's tracker id is ignored).
  - `test_start_year_rejects_years_out_of_reach_and_bad_pto`.
  - `test_default_new_year`: one past latest; none and October → next year; none and June → this year.
  - `test_unplanning_the_last_year_deactivates_the_tracker`, `test_unplanning_one_of_two_years_keeps_tracking`.
  - `test_set_target_updates_target_and_stay`.
  - `test_convert_targets_sets_the_midpoint_of_days_away`: a stay of 7–11 on a route with overhead 2.0 → target 11; an existing target is untouched; an unknown destination is skipped.
- [ ] **Step 2: Run them.** Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** `core/yearplan.py`, `planning.py` and the config constants as specified. The CLI follows `profiles.main`'s shape (argparse, `Settings.from_env()`, `load_geo(engine)`, rollback on `--dry-run`).
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: planning-year actions and target conversion`).
- [ ] **Step 6: Convert Neon's trackers.**
  - Use the same guarded snippet with `DATABASE_URL` (pooled is fine).
  - Run `python -m ptopilot.planning convert-targets --dry-run`, then without the flag.
  - Expected: `converted N trackers` with N = the user's 4 trackers (or fewer, if some already have targets). Record N in the report.

---

### Task 3: The scan plans each trip in its own year

**Files:**
- Modify: `ptopilot/pipeline/expand.py`, `ptopilot/destinations.py`, `ptopilot/profiles.py`
- Test: `tests/pipeline/test_expand.py`, `tests/test_destinations.py`, `tests/test_profiles.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `plan_trip`.
- Produces:
  - `profile_for(user: User, pto_available: int | None = None) -> TravelerProfile`. With `None`, it uses `pto_days_total − pto_committed` as today.
  - `add_destination(..., today: date | None = None)`: after creating or reactivating the tracker, it plans it in every planning year of the user with `year >= today.year` (default `date.today()`).
  - `apply_profile`: also upserts a planning year for each distinct start year of the profile's windows, with `pto_days = pto_days_total` and `other_time_off = pto_committed`. It then plans every profile tracker in each of those years.

- [ ] **Step 1: Write the failing tests**
  - `test_a_trip_is_searched_only_in_its_years_ranges`: a tracker planned in 2027 only, with ranges in 2027 and 2028. All of its links depart in 2027.
  - `test_each_years_pto_limits_its_own_trips`:
    - 2027 has `pto_days=0`, so no links need PTO;
    - 2028 has `pto_days=20`, so links with PTO > 0 exist.
  - `test_a_tracker_with_no_planned_trip_is_not_searched` (counted as `trackers_without_windows`).
  - `test_a_range_in_a_year_without_a_planning_year_is_ignored`.
  - `test_adding_a_destination_plans_it_in_open_years`: the user has 2026 (past, with `today` in 2027), 2027 and 2028 → planned in 2027 and 2028 only.
  - `test_profile_load_writes_planning_years_and_trips`. Loading the same YAML twice changes nothing the second time.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `expand.run` loads `planning_years`, `planned_trips` and windows once.
  - For each tracker, it calls `plan_itineraries` once per planned year that has ranges. It passes that year's windows (still clamped to start tomorrow) and `profile_for(user, year.pto_days − year.other_time_off)`.
  - The link-writing loop is unchanged.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS. Existing expand tests that create windows without planning years now need a planning year and planned trips in their setup. Add a shared fixture helper; don't weaken assertions.
- [ ] **Step 5: Commit and push** (`feat: the scan searches each trip in its own year`).

---

### Task 4: Estimated PTO and the "Building price history" signal

**Files:**
- Modify: `ptopilot/core/planner.py`, `ptopilot/web/history.py`
- Test: `tests/core/test_planner.py`, `tests/web/test_history.py`

**Interfaces:**
- Produces:
  - `estimate_pto(profile: TravelerProfile, tracker: TrackerSpec, windows: Sequence[Window], geo: Geo, seasons: SeasonTable) -> int | None`.
    - It returns the fewest `pto_cost` of any shape `plan_itineraries` would accept, for any home airport, ignoring the PTO limit (treat `pto_available` as `MAX_PTO_DAYS`).
    - It applies the same days-away band, ground-day rule, Friday-evening variants and season tolerance.
    - It returns `None` when no shape qualifies (including when there are no windows).
    - Share the shape filtering with `plan_itineraries` through one private helper, not a copy.
  - `building_history(s: Session, homes: Sequence[str], dest: Destination) -> bool` in `web/history.py`: True when no `route_baselines` row with `confidence == "normal"` exists for any origin in `homes`, `dest_airport` in `dest.airports` and `return_airport` in `dest.home_from`.
  - `DestinationSummary.building_history: bool` (set by `destination_summaries`), and `DestinationSummary.target_days: int | None`.

- [ ] **Step 1: Write the failing tests**
  - `test_estimate_pto_is_the_best_case_in_the_ranges`:
    - US calendar, the 2027-05-28..06-01 range (Memorial Day is Mon May 31), a rule with `min_trip_days=3` and overhead 1.0, every month rated good;
    - target 4 → `0` (Sat May 29 → Mon May 31);
    - target 7 → `2` (Fri May 28 → Tue Jun 1, the longest shape the range allows; band 5–9).
    - These values assume `WINDOW_SLACK_DAYS = 2`. If the config differs, recompute them by hand and say so in the report.
  - `test_estimate_pto_counts_friday_evening_departures`: with `friday_evening_departure=True`, the estimate is 1 lower than without, for a range where the best shape departs on a Friday.
  - `test_estimate_pto_is_none_without_ranges_or_fitting_trips`.
  - `test_estimate_pto_respects_season_tolerance`: every month rated `avoid` with tolerance `normal` → `None`.
  - `test_building_history_until_a_normal_baseline_exists`: low-confidence rows only → True; one `normal` row for any home or airport pair → False.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: estimated PTO per trip; building-history signal`).

---

### Task 5: The planner page (works without JavaScript)

**Files:**
- Create: `ptopilot/web/planner_view.py`, `ptopilot/web/templates/plan.html`
- Modify: `ptopilot/web/app.py`, `ptopilot/web/templates/base.html`, `ptopilot/web/static/app.css`
- Test: `tests/web/test_plan_page.py`

**Interfaces:**
- Consumes: Tasks 2 and 4.
- Produces: `plan_context(engine, geo, seasons, user_id: int, year: int, today: date) -> dict | None` (`None` when the user has no such year). The dict holds:
  - `year`, `pto_days`, `other_time_off`, `available` (= `pto_days − other_time_off`);
  - `trips`: a list of dicts with
    - `tracker_id`, `name`, `palette`, `target_days`, `band` (low, high: Plan 9's `_target_band` with the smallest route minimum across the homes);
    - `est_pto: int | None`;
    - `wont_fit: int | None` (from `allocate_pto` in trip order);
    - `min_trip: int | None` (the Plan 9 too-short warning), `building_history: bool`, `snoozed_until`;
  - `totals`: `trips`, `days_away` (sum of targets), `est_pto` (sum of known estimates);
  - `months`: 12 entries of `(name, weeks)`, where each day cell is `{date, weekend, holiday: str | None, day_off, open}`. Holidays come from `WorkCalendar.holiday_name` (so ignored holidays are ordinary days), and `day_off` from `extra_days_off`.
  - `ranges`: the saved ranges plus `EXTRA_RANGE_ROWS` blank rows.
- Routes (all redirect to `/` when signed out; another user's year or tracker, or a missing year, is a 404 page):
  - `GET /plan`: redirects to `/plan/{current_year}`, or to `/plan/new` without one.
  - `GET /plan/{year}`: the page.
  - `POST /plan/{year}/ranges`:
    - fields are `range_start_{i}` and `range_end_{i}`;
    - blank rows are ignored, unparseable dates and `ValueError`s re-render with a 400 and the message;
    - success redirects to `/plan/{year}?saved=ranges`.
  - `POST /plan/{year}/pto`: `pto_days`, `other_time_off`.
  - `POST /plan/{year}/trips/{tracker_id}`: `target_days`.
  - `POST /plan/{year}/trips/{tracker_id}/remove`.
- Page layout, using the design system's components and the sketch at `.superpowers/brainstorm/240-1792930493/content/year-planner.html` as a starting point:
  1. **Trips panel:** Destination (colour dot), Days away (target, with its band in muted text and an inline number form), Est. PTO, Status, and a remove button.
     - Status is one of: "Watching", "Snoozed until …", "Building price history", "Won't fit: {n} PTO left after the others", or "Needs at least {min_trip} days away" (several may show).
     - A total row: "{trips} trips · {days_away} days away · {est_pto} PTO", then "You have {available}".
     - An "+ Add a trip" link to `/destinations`.
  2. **Year PTO form.**
  3. **Calendar panel** "When you're open to travel":
     - 12 months in a responsive grid;
     - day cells carry `data-date="YYYY-MM-DD"` and classes `we`, `hol` (with a `title` holiday name), `off`, `open`;
     - a legend.
     - Below it, the range form: rows of two date inputs each, with a "Save ranges" button.
  - The nav in `base.html` gains **Plan** (`active == "plan"`) between Dashboard and Destinations.
  - `base.html` gains an empty `{% block scripts %}{% endblock %}` before `</body>`. Only `plan.html` fills it (Task 7), so other pages stay script-free. Plan 9's `test_the_search_text_is_echoed_escaped` keeps passing unchanged.

- [ ] **Step 1: Write the failing tests**
  - `test_plan_page_lists_trips_with_band_and_estimate`.
  - `test_plan_page_marks_holidays_weekends_and_open_days`:
    - `data-date="2027-07-05"` has class `hol` (Independence Day observed);
    - `2027-07-03` has `we`;
    - a saved range's days have `open`;
    - an ignored holiday (Columbus Day) has no `hol`.
  - `test_bottom_line_totals_and_wont_fit_note` (estimates monkeypatched to 5, 6 and 9 with 15 available → "Won't fit: 4 PTO left after the others" on the third).
  - `test_saving_ranges_merges_and_redirects`.
  - `test_saving_a_reversed_range_is_a_400_naming_the_row`.
  - `test_saving_pto_validates`.
  - `test_editing_a_target_and_removing_a_trip`.
  - `test_plan_redirects_to_the_current_year_or_to_new`.
  - `test_plan_routes_are_scoped_to_the_signed_in_user`: every `/plan` route with another user's year or tracker → 404, and their rows are unchanged.
  - `test_plan_page_shows_building_history_and_too_short_notes`.
  - `test_pages_other_than_plan_have_no_script_tag` (dashboard, destinations, profile).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `planner_view.py`, the routes, the template and styles. Calendar colours come from the existing design tokens in `app.css`: holiday a warm red tint, open a blue tint, weekends neutral.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: year planner page`).

---

### Task 6: Starting a year, onboarding, and the profile and dashboard catch-up

**Files:**
- Create: `ptopilot/web/templates/plan_new.html`
- Modify: `ptopilot/web/app.py`, `ptopilot/web/forms.py`, `ptopilot/profiles.py`, `ptopilot/web/templates/profile.html`, `dashboard.html`, `_components.html`
- Test: `tests/web/test_plan_new.py`, `tests/web/test_profile_page.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: Task 2 `default_new_year`, `start_year`, `current_year`; Task 4 summary fields.
- Produces:
  - `parse_profile(data, geo, require_plan: bool = True)`: with `False`, missing `windows` and `trackers` are not errors.
  - `apply_profile(s, p, replace_plan: bool = True)`: with `False`, windows and trackers are left alone.
- Routes:
  - `GET /plan/new` shows "Start planning {year}" with:
    - a year select (this year, or `PLAN_YEARS_AHEAD` ahead, excluding years the user has; default `default_new_year`);
    - PTO days (prefilled from the latest year's `pto_days`, else `users.pto_days_total`);
    - other time off (0);
    - a checkbox per active tracker, checked, labelled with name and target;
    - copy: "Open ranges start empty. You'll drag them on the next page." and "Want somewhere new? Add destinations any time."
  - `POST /plan/new` calls `start_year` and redirects to `/plan/{year}`. If the year exists, it redirects there (no error). A `ValueError` gives a 400 re-render.

- [ ] **Step 1: Write the failing tests**
  - `test_start_planning_carries_checked_trips_and_starts_with_no_ranges`.
  - `test_posting_start_twice_redirects_to_the_year`.
  - `test_new_year_page_defaults_and_prefills`.
  - `test_profile_form_no_longer_has_windows_or_bucket_list`. It still saves home, calendar, trip length and preferences, and leaves windows, trackers and planned trips untouched. The PTO field is labelled "PTO days per year" with the hint "Used to start each new planning year."
  - `test_new_traveler_goes_from_profile_to_start_planning`: the first profile save redirects to `/plan/new`.
  - `test_dashboard_pto_bar_uses_the_current_planning_year`, falling back to the user's fields without one.
  - `test_dashboard_card_says_building_price_history` and shows "~{target} days away" as the eyebrow when a target is set (the stay range otherwise).
  - `test_empty_dashboard_points_to_destinations_and_plan`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `pto_committed` leaves the profile form: it now lives on the planner as "Other time off (not trips)". The YAML field still works through `apply_profile`.
  - `pto_bar(total, committed)` is fed `pto_days` and `other_time_off` of the current planning year.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: start a planning year; profile and dashboard follow the planner`).

---

### Task 7: Drag to open and close days

**Files:**
- Create: `ptopilot/web/static/planner.js`
- Modify: `ptopilot/web/templates/plan.html`, `ptopilot/web/static/app.css`
- Test: `tests/web/test_plan_page.py`

**Interfaces:**
- Consumes: Task 5's markup:
  - day cells `[data-date]` inside `#year-calendar`;
  - the range form `#ranges-form` with rows `range_start_{i}` and `range_end_{i}`;
  - the "Save ranges" button.
- Produces the behavior of `planner.js` (plain ES2017, no globals beyond one IIFE, `defer`-loaded):
  - **Pointer down** on a day starts a drag. The mode is "open" if that day is closed, else "close".
  - **While dragging,** every day between the anchor and the current day (in date order, across months) previews the mode (class `drag-open` / `drag-close`).
  - **Pointer up** applies the change.
  - **Keyboard:** day cells are focusable (`tabindex="0"`). Enter or Space toggles one day.
  - **Changes are unsaved until submitted:**
    - each change shows "Unsaved changes" beside the button;
    - on submit, the script replaces the form's range rows with hidden `range_start_{i}` and `range_end_{i}` inputs built from the open days (consecutive dates joined into one range);
    - the server path is the Task 5 POST, unchanged.
  - **Touch:** use pointer events with `touch-action: none` on the calendar so dragging doesn't scroll.
- The page includes it with `{% block scripts %}<script src="/static/planner.js" defer></script>{% endblock %}`.

- [ ] **Step 1: Write the failing tests**
  - `test_plan_page_loads_the_planner_script` (the script tag, plus `#year-calendar`, `#ranges-form` and `tabindex="0"` on day cells).
  - `test_the_planner_script_is_served` (`GET /static/planner.js` → 200, `application/javascript` or `text/javascript`).
  - `test_rows_as_the_script_posts_them_are_accepted`: hidden rows in the exact shape the script builds (`range_start_0..n`, no blanks) save correctly.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `planner.js` and the drag styles.
- [ ] **Step 4: Check it in a real browser** with the Playwright MCP tools against a local `uvicorn` run (test database, a signed-in session from the test helper or a sign-in link logged by the app with no emailer):
  - drag March 1–21, save, reload: those days are `open`;
  - drag back across March 10–12, save: two ranges;
  - press Enter on one day: it toggles.
  - Take one screenshot and note the result in the report. The browser check is a manual gate, not a CI test.
- [ ] **Step 5: Run the full suite and ruff.** Expected: PASS.
- [ ] **Step 6: Commit and push** (`feat: drag to open travel days`).
- [ ] **Step 7: Live check** after Render deploys:
  - `/plan` on https://ptopilot.onrender.com redirects to the user's 2027 plan;
  - the calendar shows March and October open;
  - the trips list shows the converted targets.
