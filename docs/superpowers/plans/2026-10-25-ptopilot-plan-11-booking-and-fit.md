# ptopilot Plan 11: Booking, Fit Warnings, Combinations and the Email Banner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- **"I booked this":** a traveler marks a trip as booked, from a deal on the destination page or by typing the dates on the planner.
  - The booking stops that destination's monitoring for that year.
  - It counts its real PTO, and shows on the planner and calendar.
  - It can be cancelled.
- **Fit warnings:** every remaining deal says when it overlaps a booked trip or doesn't fit the PTO left.
- **Combinations:** the planner offers a few trips that together are fantastic on every leg.
- **Email banner:** the email opens with "{booked} booked · {planned} planned · {left} PTO left".

**Architecture:**
- **Bookings** live on `planned_trips` (Plan 10): new nullable booked columns on the (tracker, year) row. A booked row means that destination is done for that year. The scan skips it, and today's candidates for it are hidden.
- **Pure logic:**
  - `ptopilot/core/fit.py`: booked-trip overlap and fit notes;
  - `ptopilot/core/combos.py`: the combination search.
- **Year totals** come from one function in a new `ptopilot/plan_totals.py`, used by the planner page, the dashboard PTO bar and the email banner. The three numbers therefore always agree.
- **Notes are computed when a page or email is built,** so "re-checking fit after a booking" needs no stored state.

**Tech Stack:** No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-10-25-ptopilot-year-plan-design.md`](../specs/2026-10-25-ptopilot-year-plan-design.md):
- §3.3 a booked trip counts its actual PTO;
- §3.4 "I booked this";
- §3.5 combinations;
- §3.6 fit warnings;
- §3.8 carry-over lists unbooked trips;
- §3.9 email banner.

Plan 10, the planning year, is done. It provides `planning_years`, `planned_trips`, `/plan/{year}`, `estimate_pto` and `allocate_pto`.

## Global Constraints

- **Booking is per destination per year.** It removes that destination's trip *for that year* from monitoring. The same destination planned in another year keeps being searched.
- **Year of a trip:** the year of its departure date. A booking's `booked_depart` year equals its planned-trip year.
- **Remaining PTO for a year** = `pto_days − other_time_off − booked PTO that year`. The deal note "Doesn't fit your remaining PTO" uses it.
- **Banner "left"** = `pto_days − other_time_off − booked − planned`, where planned is the summed estimated PTO of unbooked planned trips.
- **Soft notes only:**
  - Fit notes never hide a deal or stop a search.
  - The scan keeps searching each year with `pto_days − other_time_off` (Ruling: booked PTO is not subtracted from the search limit, so deals over the remaining PTO still appear with their note, as the spec's soft warning intends).
- **Combinations** are shown on the website only, never in the email. They need:
  - at least 2 legs;
  - every leg at `pct_below ≥ COMBO_MIN_PCT_BELOW` (20) on a `normal`-confidence candidate, in a `good` season;
  - no two legs overlapping, and no leg overlapping a booked trip;
  - total PTO ≤ remaining PTO.
- **Exact copy:**
  - "Overlaps your booked {destination} trip."
  - "Doesn't fit your remaining PTO ({n} left)." (n never below 0)
  - Banner: "{year}: {booked} booked · {planned} planned · {left} PTO left". When left < 0, it ends "· {-left} PTO over" instead.
- **Scoping:** every route acts only on the signed-in user's own trackers, candidates and years. Anything else is a 404 with nothing changed.
- **Migrations reach Neon before code that reads them deploys.**
- **Checks:** `ruff check .` and `ruff format --check .` pass. Database tests use `PTOPILOT_REQUIRE_DB=1`.
- **Workflow:** work on `main`, and every task ends with a commit and push. Commit messages end with a `Co-Authored-By:` line for the model that wrote them.
- **Secrets:** never print or commit them.

New config constants (exact values):
```python
COMBO_MIN_PCT_BELOW = 20
COMBO_MIN_LEGS = 2
COMBO_MAX_SHOWN = 3
COMBO_LEGS_PER_TRACKER = 5    # best eligible offers per destination considered by the search
MAX_BOOKED_DAYS = 60          # longest bookable trip, depart to return inclusive
```

## Review Focus

1. **Booking someone else's or a stale candidate**, or a candidate whose year isn't planned (or is already unplanned) → a 404 or 400 page, and nothing is booked.
   - *Task 1: `test_booking_from_a_candidate_is_scoped_and_checked`. Task 4: `test_booking_another_users_candidate_is_a_404`.*
2. **Booking twice** (double click, or correcting dates) → the second booking replaces the first. No IntegrityError, and no second row.
   - *Task 1: `test_booking_again_replaces_the_booking`.*
3. **Two bookings on overlapping dates** (Madeira Mar 12–21, then Azores Mar 18–25) → the second is refused with "Overlaps your booked Madeira trip." and a 400.
   - *Task 1: `test_overlapping_bookings_are_refused`. Task 3: `test_manual_booking_that_overlaps_is_a_400`.*
4. **A destination booked in 2027 and also planned in 2028** → 2028 keeps being searched. Today's 2027 candidates disappear from the dashboard, destination page and digest at once, without waiting for the next scan.
   - *Task 2: `test_a_booked_year_is_not_searched_but_other_years_are`, `test_candidates_of_a_booked_trip_are_hidden`.*
5. **Cancelling a booking** → the trip is "Watching" again with its target. The next scan searches it, and the PTO totals drop the booked PTO.
   - *Task 3: `test_cancelling_a_booking_restores_watching_and_totals`.*

---

## File structure

```
ptopilot/db/migrations/versions/0008_bookings.py    # NEW: booked columns on planned_trips
ptopilot/db/models.py                    # PlannedTrip booked fields
ptopilot/core/fit.py                     # NEW: BookedTrip, overlaps, fit_notes (pure)
ptopilot/core/combos.py                  # NEW: Leg, Combination, find_combinations (pure)
ptopilot/planning.py                     # book_trip, book_from_candidate, cancel_booking, booked_trips
ptopilot/plan_totals.py                  # NEW: trip_estimates, year_totals, remaining_pto (shared by site + email)
ptopilot/pipeline/expand.py              # skip booked (tracker, year)
ptopilot/web/history.py, ptopilot/digest/select.py   # hide booked trips' candidates; fit notes
ptopilot/web/planner_view.py, templates/plan.html, plan_new.html   # booked rows, calendar, combos, carry-over
ptopilot/web/app.py, templates/destination.html, dashboard.html, _components.html
ptopilot/digest/templates/digest.html.j2, digest.txt.j2, ptopilot/digest/render.py
ptopilot/config.py
```

---

### Task 1: Bookings: schema and actions

**Files:**
- Create: `ptopilot/db/migrations/versions/0008_bookings.py`, `ptopilot/core/fit.py`
- Modify: `ptopilot/db/models.py`, `ptopilot/planning.py`, `ptopilot/config.py`
- Test: `tests/db/test_migrations.py`, `tests/db/test_models.py`, `tests/core/test_fit.py`, `tests/test_planning.py`

**Interfaces:**
- Produces (model): `PlannedTrip` gains `booked_depart: date | None`, `booked_return: date | None`, `booked_price: Decimal | None` (Money), `booked_currency: str | None` (String(3)), `booked_pto: int | None` (SmallInteger), `booked_at: datetime | None`, and a property `booked -> bool` (`booked_depart is not None`).
  - Check constraints:
    - `booked_dates`: `(booked_depart IS NULL) = (booked_return IS NULL) AND (booked_depart IS NULL) = (booked_pto IS NULL)`;
    - `booked_order`: `booked_return >= booked_depart`;
    - `booked_year`: `booked_depart IS NULL OR extract(year from booked_depart) = year`.
- Produces (pure, `core/fit.py`):
  - `@dataclass(frozen=True) class BookedTrip: tracker_id: int; destination: str; year: int; depart: date; ret: date; pto_cost: int; price: Decimal | None; currency: str | None`.
  - `overlaps(a_start, a_end, b_start, b_end) -> bool`: inclusive dates.
  - `first_overlap(depart, ret, booked: Sequence[BookedTrip], ignore_tracker: int | None = None) -> BookedTrip | None`.
  - `fit_notes(depart, ret, pto_cost, booked, remaining: int | None, own_tracker_id: int | None = None) -> tuple[str, ...]`:
    - the overlap note (first overlap, ignoring the deal's own tracker) comes first;
    - then the PTO note when `remaining is not None and pto_cost > remaining`.
    - Exact copy is in Global Constraints.
- Produces (`planning.py`; each takes a `Session` and the user, and acts only on their rows):
  - `booked_trips(s, user, years: Iterable[int] | None = None) -> list[BookedTrip]`: destination names via `load_geo(...)`. Pass a `geo` argument; unknown codes fall back to the code.
  - `book_trip(s, user, tracker_id, year, depart, ret, *, price=None, currency=None, pto_cost=None, geo) -> PlannedTrip`. It:
    - requires the planned trip `(tracker_id, year)` to exist and be the user's (else `LookupError`);
    - raises `ValueError` when `depart.year != year`, `ret < depart`, or `(ret - depart).days + 1 > MAX_BOOKED_DAYS`;
    - raises `ValueError("Overlaps your booked {destination} trip.")` on an overlap with another of the user's booked trips;
    - computes `pto_cost` with the user's `WorkCalendar.pto_cost(depart, ret)` when it isn't given;
    - sets the booked fields and `booked_at = now`, replacing an existing booking.
  - `book_from_candidate(s, user, candidate_id, *, geo) -> PlannedTrip`. It:
    - loads the `Candidate` with its `RouteQuery` and `TrackerRouteLink`;
    - requires `candidate.user_id == user.id` (else `LookupError`);
    - calls `book_trip` with the route's dates, the candidate's price and currency, the link's `pto_cost` (which accounts for leaving after work), and `year = depart.year`.
  - `cancel_booking(s, user, tracker_id, year) -> bool`: clears every booked field; False when the trip isn't the user's.

- [ ] **Step 1: Write the failing tests**
  - `test_migration_adds_booked_columns_and_constraints`. A booked row with `booked_depart` in another year violates `booked_year`, and half-filled booked fields violate `booked_dates`.
  - `test_fit_notes`:
    - an overlapping booking gives `("Overlaps your booked Madeira trip.",)`;
    - `pto_cost=6`, `remaining=4` gives `("Doesn't fit your remaining PTO (4 left).",)`;
    - `remaining=-2` gives "(0 left)";
    - both conditions give two notes, overlap first;
    - the deal's own tracker never counts as an overlap;
    - `remaining=None` gives no PTO note.
  - `test_overlaps_is_inclusive`: Mar 12–21 and Mar 21–25 overlap; Mar 12–21 and Mar 22–25 don't.
  - `test_book_trip_computes_pto_from_the_calendar`: US calendar, Fri 2027-05-28 → Mon 2027-05-31 → `booked_pto == 1`.
  - `test_booking_again_replaces_the_booking`.
  - `test_overlapping_bookings_are_refused`.
  - `test_book_trip_validates_dates` (wrong year, reversed, longer than 60 days).
  - `test_booking_from_a_candidate_is_scoped_and_checked`:
    - another user's candidate → `LookupError`;
    - a candidate whose year has no planned trip → `LookupError`;
    - an evening-departure candidate books the link's `pto_cost`.
  - `test_cancel_booking_clears_it`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** migration 0008 (`down_revision = "0007"`, columns nullable, no data change), the models, `core/fit.py`, the `planning.py` functions and the constants.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Migrate Neon before pushing.** Use the guarded snippet with `DATABASE_URL_UNPOOLED`, then `alembic upgrade head`. Expected: `Running upgrade 0007 -> 0008`.
- [ ] **Step 6: Commit and push** (`feat: booked trips on planned trips`).

---

### Task 2: A booked trip leaves the watch

**Files:**
- Modify: `ptopilot/pipeline/expand.py`, `ptopilot/web/history.py`, `ptopilot/digest/select.py`
- Test: `tests/pipeline/test_expand.py`, `tests/web/test_history.py`, `tests/digest/test_select.py`

**Interfaces:**
- Consumes: Task 1 `PlannedTrip.booked`.
- Produces:
  - `expand.run` treats a booked `(tracker, year)` as not planned for that year.
  - `history._options`, `destination_summaries`, `trip_options` and `digest.select.build_digests` drop candidates whose `(tracker_id, depart_date.year)` is booked.
  - `DestinationSummary.booked: tuple[BookedTrip, ...]`: the tracker's bookings for years ≥ `today.year`.

- [ ] **Step 1: Write the failing tests**
  - `test_a_booked_year_is_not_searched_but_other_years_are` (planned in 2027 and 2028, booked in 2027 → links only depart in 2028).
  - `test_candidates_of_a_booked_trip_are_hidden`: today's 2027 candidates exist, booking 2027 removes them from `destination_summaries`, `trip_options` and `build_digests`, and 2028 candidates stay.
  - `test_summary_lists_current_bookings`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Load the booked `(tracker_id, year)` pairs once per call, and filter in the same loops that already skip excluded candidates.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: booked trips leave the watch`).

---

### Task 3: Booking on the planner, real PTO in the totals

**Files:**
- Create: `ptopilot/plan_totals.py`
- Modify: `ptopilot/web/planner_view.py`, `ptopilot/web/app.py`, `ptopilot/web/templates/plan.html`, `plan_new.html`, `ptopilot/web/static/app.css`
- Test: `tests/test_plan_totals.py`, `tests/web/test_plan_page.py`, `tests/web/test_plan_new.py`

**Interfaces:**
- Consumes: Task 1 actions. Plan 10's `estimate_pto`, `allocate_pto`, `year_trackers`, `year_ranges` and `profile_for`.
- Produces (`plan_totals.py`):
  - `trip_estimates(s, user, year, geo, seasons) -> dict[int, int | None]`: an estimated PTO per **unbooked** planned tracker, moved from `planner_view` so the site and email share it.
  - `@dataclass(frozen=True) class YearTotals: year: int; pto_days: int; other_time_off: int; booked: int; planned: int`, with properties:
    - `available` = `pto_days − other_time_off`;
    - `remaining` = `available − booked` (what deal notes use);
    - `left` = `remaining − planned` (what the banner shows).
  - `year_totals(s, user, year, geo, seasons) -> YearTotals | None` (None without that planning year).
  - `remaining_by_year(s, user, years) -> dict[int, int]`: the cheap version without estimates, for deal notes.
- Planner page changes (`plan_context` uses `trip_estimates` and `year_totals`):
  - **A booked trip row:**
    - Days away shows the booked trip's real days; Est. PTO shows its real PTO.
    - Status is "Booked · {dates} · {price}" (price omitted when unknown).
    - A "Cancel booking" button.
  - **An unbooked trip row:** a small "I booked this" disclosure (`<details>`) with depart and return date inputs, an optional price and a "Mark booked" button.
  - **Won't-fit allocation:** booked trips first (their real PTO), then planned trips in `year_trackers` order.
  - **Bottom line:** "{trips} trips · {days_away} days away · {booked + planned} PTO", then "You have {available} · {booked} booked · {left} free" (or "{-left} over").
  - **Calendar:** days inside a booked trip get class `booked`, with `title="{destination} (booked)"`, and a legend entry. Booked beats open in the styling, and the `.hol` ring stays visible.
- Routes:
  - `POST /plan/{year}/trips/{tracker_id}/book` takes `depart`, `return`, `price` (optional, `$` and `,` allowed). A `ValueError` re-renders with a 400 and the message; success redirects to `/plan/{year}?saved=booked`.
  - `POST /plan/{year}/trips/{tracker_id}/cancel`.
  - Both 404 for another user's or an unplanned trip.
- `/plan/new` carry-over (§3.8: last year's unbooked trips): a tracker whose trip in the latest existing year is booked is listed **unchecked**, labelled "booked in {year}". The others stay checked.

- [ ] **Step 1: Write the failing tests**
  - `test_year_totals_counts_booked_and_planned`: 15 PTO, 0 other, one booked at 5 PTO, planned estimates 6 and 9 → booked 5, planned 15, remaining 10, left −5.
  - `test_trip_estimates_skip_booked_trips`.
  - `test_planner_shows_a_booked_row_with_real_days_and_pto`.
  - `test_manual_booking_from_the_planner`.
  - `test_manual_booking_that_overlaps_is_a_400`.
  - `test_cancelling_a_booking_restores_watching_and_totals`.
  - `test_wont_fit_counts_booked_trips_first`.
  - `test_calendar_marks_booked_days`.
  - `test_carry_over_unchecks_trips_booked_last_year`.
  - `test_book_and_cancel_routes_are_scoped`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: book and cancel trips on the planner`).

---

### Task 4: "I booked this" on a deal, and fit notes everywhere

**Files:**
- Modify: `ptopilot/web/app.py`, `ptopilot/web/history.py`, `ptopilot/web/templates/destination.html`, `_components.html`, `dashboard.html`; `ptopilot/digest/select.py`, `ptopilot/digest/templates/digest.html.j2`, `digest.txt.j2`
- Test: `tests/web/test_destination_page.py`, `tests/web/test_dashboard.py`, `tests/digest/test_select.py`, `tests/digest/test_render.py`

**Interfaces:**
- Consumes: Task 1 `book_from_candidate`, `booked_trips`, `fit_notes`. Task 3 `remaining_by_year`.
- Produces:
  - `TripOption.fit_notes: tuple[str, ...]` and `DealCard.fit_notes: tuple[str, ...]`. Each is computed with `fit_notes(depart, ret, pto_cost, booked, remaining_by_year.get(depart.year), own_tracker_id)`, where booked is the user's bookings.
  - `POST /trackers/{tracker_id}/book` takes `candidate_id`. It calls `book_from_candidate` (the candidate must be this tracker's and the user's, else 404) and redirects to `/plan/{year}?saved=booked`.
- Display:
  - **Destination page:** every non-dimmed option row gets an "I booked this" button (POST form), and its fit notes in a muted warning style.
  - **Dashboard card:** the best option's fit notes, plus "Booked {dates}" for each current booking (`DestinationSummary.booked`).
  - **Email:** each deal card's fit notes under its PTO line, in the HTML and text versions, with inline styles as the existing cards use.

- [ ] **Step 1: Write the failing tests**
  - `test_booking_from_the_destination_page`: the row's dates, price and the link's PTO are recorded, and the response redirects to the planner.
  - `test_booking_another_users_candidate_is_a_404`.
  - `test_option_rows_show_fit_notes` (overlap and PTO).
  - `test_dashboard_card_shows_fit_notes_and_bookings`.
  - `test_digest_cards_carry_fit_notes`, and they render in both the HTML and text versions.
  - `test_a_deal_in_a_year_without_a_planning_year_has_no_pto_note`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: book from a deal; fit notes on site and email`).

---

### Task 5: Combinations on the planner

**Files:**
- Create: `ptopilot/core/combos.py`
- Modify: `ptopilot/web/planner_view.py`, `ptopilot/web/templates/plan.html`, `ptopilot/web/static/app.css`
- Test: `tests/core/test_combos.py`, `tests/web/test_plan_page.py`

**Interfaces:**
- Consumes: Task 1 `BookedTrip`, `overlaps`. Task 3 `YearTotals.remaining`.
- Produces (pure, `core/combos.py`):
  - `@dataclass(frozen=True) class Leg: tracker_id: int; destination: str; candidate_id: int; depart: date; ret: date; pto_cost: int; price: Decimal; typical: Decimal; currency: str; confidence: str; season_rating: str; deep_link: str | None`, with properties `pct_below` (int, rounded like `DealCard.pct_below`) and `savings` (`typical − price`).
  - `eligible(leg) -> bool`: `pct_below ≥ COMBO_MIN_PCT_BELOW`, `confidence == "normal"`, `season_rating == "good"`.
  - `@dataclass(frozen=True) class Combination: legs: tuple[Leg, ...]`, with properties `pto` (sum), `price` (sum) and `savings` (sum).
  - `find_combinations(legs: Iterable[Leg], booked: Sequence[BookedTrip], remaining: int, max_shown: int = COMBO_MAX_SHOWN) -> list[Combination]`:
    1. Keep eligible legs that overlap no booked trip.
    2. Keep the best `COMBO_LEGS_PER_TRACKER` per tracker by `(-pct_below, price)`.
    3. Search every set of at least `COMBO_MIN_LEGS` distinct trackers with one leg each: no two legs overlap, and total PTO ≤ `remaining`.
    4. Rank by `(-len(legs), -savings, pto)`.
    5. Return at most `max_shown`, with at most one combination per set of trackers.
    - Use a depth-first search with PTO pruning. Ten trackers with five legs each must finish under 1 s.
- Planner page:
  - A "Fantastic on every leg" panel, shown only when `find_combinations` returns something.
  - It is built from the latest run's candidates for the year's **unbooked** planned trackers (not snoozed or excluded), with typical prices from `load_baselines`.
  - Each combination lists its legs ("{destination} · {dates} · {price} ({pct}% below)" with View flights), then "{pto} PTO of {remaining} left · saves ~{savings} against typical".

- [ ] **Step 1: Write the failing tests**
  - `test_a_combination_needs_every_leg_fantastic`: one leg at 15% below → none; both at ≥ 20% in good season → one.
  - `test_shoulder_season_or_low_confidence_legs_never_count`.
  - `test_legs_never_overlap_each_other_or_a_booking`.
  - `test_total_pto_must_fit_the_remaining_pto`.
  - `test_single_fantastic_trip_is_not_a_combination`.
  - `test_ranking_prefers_more_legs_then_savings_and_one_per_tracker_set`.
  - `test_search_is_fast_enough`: 10 trackers × 5 eligible legs, assert under 1 s.
  - `test_planner_shows_combinations_only_when_fantastic`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: fantastic-on-every-leg combinations`).

---

### Task 6: The email banner and the dashboard PTO bar

**Files:**
- Modify: `ptopilot/digest/select.py`, `ptopilot/digest/render.py`, `ptopilot/digest/templates/digest.html.j2`, `digest.txt.j2`, `ptopilot/web/app.py`, `ptopilot/web/templates/dashboard.html`, `_components.html`
- Test: `tests/digest/test_select.py`, `tests/digest/test_render.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: Task 3 `year_totals`, `YearTotals`.
- Produces:
  - `Digest.banner: YearTotals | None`. Its year is the planning year of the earliest deal's departure. With no deals it is `current_year`, and None when the user has no planning year for it.
  - `banner_text(t: YearTotals) -> str` in `render.py`, with the exact copy from Global Constraints. Banner examples:
    - left ≥ 0: "2027: 5 booked · 15 planned · 4 PTO left";
    - left < 0: "2027: 5 booked · 15 planned · 5 PTO over".
  - The banner is a slim line at the top of the HTML email (inline styles, above the lead deal) and the first line of the text version. It is never larger than the lead deal's heading.
  - The dashboard `pto_bar` macro takes a `YearTotals`. It shows the same three numbers, with booked and planned as two segments of the bar, and falls back to the old total/committed view when there is no planning year.

- [ ] **Step 1: Write the failing tests**
  - `test_banner_uses_the_earliest_deals_year`.
  - `test_quiet_digest_banner_uses_the_current_planning_year`.
  - `test_no_banner_without_a_planning_year`.
  - `test_banner_text_left_and_over` (both exact strings above).
  - `test_banner_renders_in_html_and_text`.
  - `test_dashboard_bar_matches_the_banner_numbers`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `build_digests` calls `year_totals` once per user per banner year.
- [ ] **Step 4: Run the tests**, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit and push** (`feat: email banner; dashboard bar shows booked, planned, left`).
- [ ] **Step 6: Preview the email.** Render a digest for the local dev user with the existing preview command (`python -m ptopilot.digest --dry-run` or whatever `digest/__main__.py` offers) against the **local** database. Check that the banner, the fit notes and the deal cards read well, and note the result in the report.
