# ptopilot Plan 14: Related Destinations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each destination gets a handful of suggested related places (nearby airports and curated look-alikes) that the user accepts or dismisses. Accepted ones get a light daily watch, and a rare, stunning, fitting fare to one shows under "Also worth a look" in the digest and on the destination page.

**Architecture:**
- **Suggestions:** a pure function over the airport catalog and a bundled `related.yaml`.
- **Accept / dismiss:** stored per tracker in `related_links`. Accepting creates the place (and its season ratings) without a tracker.
- **Watch:** a new pipeline stage `related`, after `score` and before `alerts`, with two steps:
  - free Travelpayouts month scans find promising cached fares;
  - at most 5 free Google live checks a day confirm them, each recorded in `related_checks`.
- **Display:** the digest and the destination page read today's confirmed rows.

**Tech Stack:** No new dependencies. Travelpayouts (`ctx.month_source`) and fast-flights (the `google_flights` entry of `ctx.live_sources`) only; never SerpApi.

**Spec:** [`docs/superpowers/specs/2026-10-25-ptopilot-related-destinations-design.md`](../specs/2026-10-25-ptopilot-related-destinations-design.md)

## Global Constraints

- **Config (exact):**
  ```python
  RELATED_NEAR_KM = 65
  RELATED_MAX_SUGGESTIONS = 5
  RELATED_STUNNING_PCT = 25
  RELATED_LIVE_CHECKS_PER_DAY = 5
  RELATED_MAX_IN_DIGEST = 3
  ```
- **Immediate suggestions:**
  - catalog airports of size `large` or `medium`, in any country;
  - within `RELATED_NEAR_KM` great-circle km of the **nearest** of the destination's airports;
  - not already among its airports.
- **Thematic suggestions:**
  - the other members of any `related.yaml` group containing one of the destination's airports;
  - **major tourist destinations only**.
- **Order and cap:** thematic first, then immediate by distance; at most `RELATED_MAX_SUGGESTIONS` per destination.
- **Never suggested:** dismissed links, or an airport already belonging to any of the user's active trackers (my call: Azores and Madeira share a group, and the user tracks both).
- **Promising:**
  - a **round-trip** cached fare at least `RELATED_STUNNING_PCT`% below the main destination's `normal`-confidence baseline median for the fare's month and length bucket;
  - it must also pass the fit checks.
  - No such baseline → skip the pair (fail closed).
- **Fit (all required):**
  - the trip lies inside one of the user's open ranges;
  - its PTO cost is ≤ that year's PTO `remaining` (after booked trips, as deal notes use: my call);
  - its days away fall in `target_band(target, TARGET_TOLERANCE_DAYS, rule.min_trip_days)` for the main destination's target (or the user's `ideal_trip_days`), with `rule = geo.travel_rule(origin, related place)`;
  - the related place's season rating for `trip_month` is exactly `good`;
  - it overlaps no booked trip.
- **Fail closed on missing seasons:** no ratings (the climate lookup failed) → never surfaced.
- **Not watched:** links of an inactive main tracker, or of one booked for the fare's year.
- **A shared related airport** linked to several main destinations is compared against the **lowest** of their typical prices, and shown once, naming that destination.
- **Live checks:**
  - at most `RELATED_LIVE_CHECKS_PER_DAY` attempts a day, globally, counting today's `related_checks` rows, failures included;
  - ranked by the biggest discount;
  - fast-flights only.
  - Confirmed = the cheapest live option that passes the user's stop and overnight filters and isn't ruled out as miserable is ≥ 25% below the same typical.
- **Digest:**
  - an **"Also worth a look"** section after the main deals, at most `RELATED_MAX_IN_DIGEST` items;
  - each reads `{related place} instead of {main destination}`, with price, `{pct}% below {main destination}'s typical`, dates, PTO and View flights;
  - calm style, never the standout look.
  - A digest whose only content is related deals is not quiet.
- **Site:** the main destination's page has a small "Related" panel with today's confirmed related deals. Shown only from today's scan.
- **The core grid is unchanged:** related places get no route queries, baselines, seeding, candidates or instant alerts.
- **Process:**
  - migrations reach Neon before code that reads them deploys;
  - work on `main`, and every task commits and pushes with the suite green;
  - never print or commit secrets;
  - default pytest never touches the network or sends email.

## Review Focus

1. **The user already tracks the suggested place** (Azores ↔ Madeira in "Atlantic islands") → not suggested. *Task 2: `test_places_the_user_tracks_are_not_suggested`.*
2. **One related airport accepted for two main destinations** → watched once, judged against the lower typical, one confirmed row naming that destination. *Task 3: `test_a_shared_related_airport_uses_the_strictest_typical`.*
3. **Same-day re-run** → no live checks beyond today's 5, and a fare already checked today isn't checked again. *Task 3: `test_a_rerun_respects_the_daily_live_checks`.*
4. **The climate lookup failed when the link was accepted** → the place is never surfaced, and the lookup is retried on the next accept or destinations-page view. *Task 2: `test_a_failed_climate_lookup_is_retried_on_view`; Task 3: `test_no_seasons_means_never_surfaced`.*
5. **A cached fare with return on the day after an open range ends, or costing one PTO day more than remaining** → not promising. *Task 3: `test_fit_needs_the_whole_trip_inside_a_range_and_pto_left`.*

---

## File structure

```
ptopilot/config.py                      # RELATED_* (Task 1)
ptopilot/data/related.yaml              # NEW curated groups (Task 1)
ptopilot/core/related.py                # NEW: groups, suggest(), fits() — pure (Tasks 1, 3)
ptopilot/core/airports.py               # AirportCatalog.within() (Task 1)
ptopilot/db/models.py, migrations/versions/0012_related.py   # RelatedLink, RelatedCheck (Task 2)
ptopilot/related_links.py               # NEW: suggestions_for, accept, dismiss (Task 2)
ptopilot/web/app.py, templates/destinations.html, destination.html, static/app.css   # (Tasks 2, 4)
ptopilot/pipeline/related.py            # NEW stage (Task 3)
ptopilot/pipeline/runner.py             # STAGES: ... score, related, alerts (Task 3)
ptopilot/digest/select.py, render.py, templates/digest.*.j2   # "Also worth a look" (Task 4)
ptopilot/web/history.py                 # related panel data (Task 4)
ROADMAP.md, README.md                   # (Task 5)
```

---

### Task 1: Suggestions (pure)

**Files:**
- Create: `ptopilot/data/related.yaml`, `ptopilot/core/related.py`.
- Modify: `ptopilot/core/airports.py`, `ptopilot/config.py`.
- Test: `tests/core/test_related_suggest.py`.

**Interfaces:**
- Produces:
  - `AirportCatalog.within(code: str, km: float, sizes: frozenset[str] = frozenset({"large", "medium"})) -> list[tuple[float, CatalogAirport]]`: any country, nearest first, excluding `code` itself.
  - `RelatedGroup(name: str, airports: tuple[str, ...])` and `load_groups() -> tuple[RelatedGroup, ...]` (cached, from `related.yaml`).
  - `Suggestion(airport: str, kind: Literal["theme", "near"], label: str, km: float | None)`:
    - label is the group name for a theme suggestion, and `"~{round(km)} km away"` for a near one.
  - `suggest(dest: Destination, catalog: AirportCatalog, groups: Sequence[RelatedGroup], exclude: Collection[str] = ()) -> list[Suggestion]`.
- **`related.yaml` format:** `groups: [{name: "...", airports: [BUD, PRG, VIE]}, ...]`.
  - About a dozen groups.
  - Must include verbatim: "Central European capitals" (BUD, PRG, VIE), "Atlantic islands" (PDL, FNC, TFS, LPA), "Patagonia" (PUQ, FTE, USH).
  - Must also include groups covering the owner's other places: LIS, OPO/SCQ, HND/NRT, BKK/HKT.
  - Major tourist destinations only: no second-tier spots (the spec's example: no Kraków).
- **Algorithm:**
  - Theme: walk the groups in file order, emitting members not in `dest.own_airports` and not in `exclude`, deduplicated.
  - Near: `within` from each of `dest.own_airports`, taking the minimum km per airport, excluding the same sets.
  - Concatenate theme then near (by km, then code), dedupe by airport (theme wins), and cut to `RELATED_MAX_SUGGESTIONS`.

- [ ] **Step 1: Write the failing tests.**
```python
def test_every_group_airport_is_a_large_or_medium_catalog_airport():  # catches typos in related.yaml
def test_thematic_suggestions_are_the_other_group_members():  # BUD → PRG, VIE (theme, label "Central European capitals")
def test_near_airports_within_65_km_any_country_nearest_first():  # London (LHR, LGW) → LTN (45 km from LHR) suggested, STN (66) and SEN (77) not; Paris (CDG, ORY) → BVA (59 km from CDG) suggested
    # Measured from the nearest of the destination's airports (spec §3.1); the spec's city-centre examples (SEN in, BVA out) don't hold under that rule.
def test_theme_comes_first_and_the_cap_is_five(): ...
def test_excluded_and_own_airports_are_never_suggested(): ...
def test_small_airports_are_not_suggested_as_near(): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(related): suggest related places for each destination`).

---

### Task 2: Accept, dismiss, and the destinations page

**Files:**
- Create: `ptopilot/related_links.py`, `ptopilot/db/migrations/versions/0012_related.py`.
- Modify: `ptopilot/db/models.py`, `ptopilot/web/app.py`, `ptopilot/web/templates/destinations.html`, `static/app.css`.
- Test: `tests/test_related_links.py`, `tests/web/test_related_page.py`.

**Interfaces:**
- **Consumes:** Task 1's `suggest`, `load_groups`; `destinations._generate_seasons` / `prefetch_climate` / `_needs_seasons` (reuse, don't copy).
- **Migration `0012_related`:**
  - `related_links`:
    - id;
    - user_id FK users CASCADE;
    - tracker_id FK trackers CASCADE;
    - airport VARCHAR(3);
    - place_code VARCHAR(32);
    - status VARCHAR(9) with CHECK `status IN ('accepted','dismissed')`;
    - created_at;
    - unique (tracker_id, airport).
  - `related_checks` (written in Task 3):
    - id;
    - run_date DATE indexed;
    - user_id FK CASCADE;
    - tracker_id FK CASCADE (the main destination it is shown against);
    - link_id FK related_links CASCADE;
    - origin VARCHAR(3), airport VARCHAR(3);
    - depart_date, return_date;
    - cached_price NUMERIC(10,2);
    - typical_median NUMERIC(10,2);
    - live_price NUMERIC(10,2) NULL;
    - currency VARCHAR(3);
    - pto_cost SMALLINT;
    - deep_link TEXT NULL;
    - confirmed BOOLEAN NOT NULL;
    - error TEXT NULL;
    - checked_at.
  - A working downgrade.
- **Produces:**
  - `RelatedLink`, `RelatedCheck` models.
  - `suggestions_for(s: Session, user: User, tracker: Tracker, geo: Geo, catalog: AirportCatalog) -> list[Suggestion]`.
    - `exclude` = airports of the user's active trackers' destinations, plus this tracker's accepted and dismissed links.
  - `accept(s: Session, user: User, tracker_id: int, airport: str, *, climate=fetch_climate) -> RelatedLink`:
    - the place is the built-in `geo.yaml` destination whose airports include `airport`, if any;
    - otherwise a `destinations` row (code via `destination_code`, name = catalog city, kind city, `added_by` the user), with seasons generated as `add_destination` does;
    - no tracker is created;
    - re-accepting a dismissed link flips it.
  - `dismiss(s, user, tracker_id, airport) -> None`: also used to remove an accepted link.
  - `accepted_links(s: Session, user_id: int | None = None) -> list[RelatedLink]`.
  - `ensure_seasons(s, place_code, catalog, climate) -> None`: retries a missing lookup, using the prefetch pattern so the network call happens outside the saving transaction.
- **Web:**
  - On `/destinations`, each tracker shows its suggestions (place name, label) with Accept and Dismiss buttons, and its accepted related places with a Remove button.
  - Routes:
    - `POST /destinations/{tracker_id}/related` with form fields `airport` and `action` (`accept` | `dismiss`), redirecting to `/destinations`;
    - signed-in and own-tracker only, else 404 like the existing routes.
  - Viewing the page retries missing season lookups for the user's accepted places.
  - Follow the page's existing form, CSRF and style patterns; no fixed inline styles.

- [ ] **Step 1: Write the failing tests.**
```python
def test_places_the_user_tracks_are_not_suggested(db): ...      # user tracks AZORES and MADEIRA → FNC not suggested for AZORES
def test_accept_creates_the_place_without_a_tracker(db): ...    # BUD accepted for a PRG tracker → destinations row + seasons, no new Tracker
def test_accept_uses_a_built_in_place_when_one_exists(db): ...  # PDL accepted → place_code "AZORES", no destinations row
def test_dismissed_links_are_not_suggested_again(db): ...
def test_re_accepting_a_dismissed_link_flips_it(db): ...
def test_a_failed_climate_lookup_is_retried_on_view(client, db): ...  # accept with a failing climate stub → no seasons; GET /destinations with a working stub → seasons saved
def test_the_page_lists_suggestions_and_accepted_places(client, db): ...
def test_another_users_tracker_gets_404(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite (the migration drift test included) and ruff. Run `alembic upgrade head`, `downgrade -1` and `upgrade head` on the local dev DB.
- [ ] **Step 5: Migrate Neon before pushing** (the guarded snippet: `DATABASE_URL_UNPOOLED` from `.env.local`, never printed, throw if empty, `alembic upgrade head`, unset). **Step 6: Commit and push** (`feat(related): accept or dismiss related places`).

---

### Task 3: The light watch (`related` stage)

**Files:**
- Create: `ptopilot/pipeline/related.py`.
- Modify: `ptopilot/core/related.py` (`fits`), `ptopilot/pipeline/runner.py`, `ptopilot/pipeline/health.py` (one line: related promising / checked / confirmed).
- Test: `tests/core/test_related_fit.py`, `tests/pipeline/test_related_stage.py`.

**Interfaces:**
- **Consumes:**
  - `accepted_links`, `RelatedCheck`;
  - `pipeline.queries.baseline_key` and `load_baselines`;
  - `core.planner.target_band`;
  - `WorkCalendar.pto_cost` via `expand.profile_for(user).calendar`;
  - `planning.year_ranges`, `plan_totals.remaining_by_year`, `planning.booked_trips` with `core.fit.first_overlap`;
  - `SeasonTable.rating` from `load_seasons(engine)`;
  - `core.misery.problems`/`assess` (judge like `return_check` does, with ground time 0 at the related airport);
  - `score.pick_option`'s stop and overnight rules, which should be factored into a helper both use, not copied.
- **Produces:**
  - `fits(depart: date, ret: date, *, ranges: Sequence[tuple[date, date]], pto_cost: int, pto_remaining: int, band: tuple[int, int], rating: Rating | None, booked: Sequence[BookedTrip]) -> bool` in `core/related.py`. Pure.
  - `related.run(ctx) -> dict[str, int]` with counts:
    - `links_watched`, `scans`, `scans_failed`, `quotes`;
    - `promising`, `checked`, `confirmed`;
    - `held_live_cap`, `skipped_no_typical`.
  - `STAGES` order `... score, related, alerts`; `related` is added to `CONTINUE_ON_FAILURE`.
- **Flow (the spec fixes the rules; this pins the order):**
  1. For each accepted link whose main tracker is active, and for each of the user's home airports and each month touched by the user's open ranges from `run_date` on, run `ctx.month_source.month_scan(origin, airport, month, market=geo.airport(origin).country, currency=DEFAULT_CURRENCY)`.
     - Scans are shared across users with the same (origin, airport, month).
     - No `month_source` → the stage is skipped.
  2. Keep round-trip quotes departing after `run_date` whose trip `fits`. Skip quotes in a year when the main tracker is booked.
  3. The typical is the min, over the main destination's airports, of the `normal`-confidence baseline median for `baseline_key(origin, main_airport, main_return_airport, depart, ret)`.
     - For a related airport linked to several main destinations, take the lowest over all of them, and name that destination.
  4. Promising when price ≤ (1 − RELATED_STUNNING_PCT/100) × typical. Keep the cheapest per (user, airport, dates).
  5. Rank all promising fares by discount. Skip any (user, airport, dates) already in today's `related_checks`. Check while today's `related_checks` count < RELATED_LIVE_CHECKS_PER_DAY.
  6. Live-check with the `google_flights` source only, using `ExactQuery(origin, airport, depart, ret)`. Write one `RelatedCheck` per attempt:
     - `confirmed` when the best acceptable option is ≤ the same threshold;
     - failures stored with `error` and `confirmed = False`.

- [ ] **Step 1: Write the failing tests** (fake month source and live source in `ctx`; no network):
```python
def test_fit_needs_the_whole_trip_inside_a_range_and_pto_left():  # return = range end + 1 → False; pto_cost = remaining + 1 → False; both at the edge → True
def test_fit_needs_a_good_season_and_no_booked_overlap(): ...     # rating "ok" or None → False
def test_a_stunning_fitting_fare_is_confirmed(make_ctx): ...      # cached 600 vs typical 1000 → promising; live 640 → confirmed row
def test_a_live_price_that_is_not_stunning_is_not_confirmed(make_ctx): ...  # live 800 → row, confirmed False
def test_no_normal_baseline_skips_the_pair(make_ctx): ...         # low-confidence only → skipped_no_typical 1, no check
def test_no_seasons_means_never_surfaced(make_ctx): ...           # place without ratings → no promising
def test_a_shared_related_airport_uses_the_strictest_typical(make_ctx): ...  # linked to mains with typical 1000 and 800; cached 700 → not promising (needs ≤ 600)
def test_live_checks_are_capped_at_five_and_ranked_by_discount(make_ctx): ...
def test_a_rerun_respects_the_daily_live_checks(make_ctx): ...
def test_one_way_quotes_are_ignored(make_ctx): ...
def test_serpapi_is_never_used(make_ctx): ...
def test_inactive_or_booked_main_destinations_are_not_watched(make_ctx): ...
def test_a_miserable_live_itinerary_is_not_confirmed(make_ctx): ...  # only option has a 10h layover → confirmed False
def test_related_runs_between_score_and_alerts():
    names = list(runner.STAGES); assert names.index("score") < names.index("related") < names.index("alerts")
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(related): a light daily watch of accepted related places`).

---

### Task 4: "Also worth a look" and the Related panel

**Files:**
- Modify:
  - `ptopilot/digest/select.py` (`RelatedCard`, `Digest.related`, `Digest.quiet`);
  - `ptopilot/digest/render.py` and `templates/digest.html.j2`, `digest.txt.j2`;
  - `ptopilot/web/history.py`, `ptopilot/web/app.py` (destination page), `templates/destination.html`, `static/app.css`.
- Test: `tests/digest/test_related_digest.py`, `tests/web/test_related_panel.py`.

**Interfaces:**
- **Consumes:** Task 3's `RelatedCheck` rows (confirmed, `run_date` = the digest's run date).
- **Produces:**
  - `RelatedCard(place: str, instead_of: str, tracker_id: int, price: Decimal, currency: str, pct_below: int, depart_date: date, return_date: date, pto_cost: int, deep_link: str | None)`.
    - pct_below = round((1 − live_price / typical_median) × 100).
    - The place name comes from `geo.destination(place_code).name`, using the geo with added places.
  - `Digest.related: list[RelatedCard]`: at most RELATED_MAX_IN_DIGEST, biggest discount first.
  - `Digest.quiet` is True only when there are neither deals nor related cards.
  - `related_deals(s: Session, tracker_id: int, run_date: date, geo: Geo) -> list[RelatedCard]` in `web/history.py`, for the panel.
- **Copy (exact):**
  - section heading "Also worth a look";
  - card title `{place} instead of {instead_of}`;
  - discount line `{pct}% below {instead_of}'s typical`;
  - panel heading "Related".
- **Look:** a calm, distinct card style using existing design tokens. Never the standout accent, and no "Rare" tag. Email inline styles, no web fonts. Web templates take no fixed inline styles.
- **Where:** in the digest, after the main deals and before the tracker table. On the site, the destination page shows the panel only when today's latest scan has confirmed rows for that tracker.

- [ ] **Step 1: Write the failing tests.**
```python
def test_digest_has_an_also_worth_a_look_section(clean_engine): ...  # "Budapest instead of Prague", "36% below Prague's typical"
def test_at_most_three_related_cards_biggest_discount_first(clean_engine): ...
def test_unconfirmed_or_old_checks_are_not_shown(clean_engine): ...  # confirmed False, or yesterday's run → absent
def test_a_digest_with_only_related_deals_is_not_quiet(clean_engine): ...
def test_related_cards_never_get_the_standout_look(clean_engine): ...  # no "Rare:"
def test_destination_page_shows_the_related_panel(client, db): ...
def test_no_panel_without_todays_confirmed_rows(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(related): also worth a look`).

---

### Task 5: Roadmap, README and a live check

- [ ] **Step 1:**
  - In `ROADMAP.md`, move "Plan 14: related destinations" from the queue to Done, with a one-line description (Plan 14; spec link).
  - In the README's pipeline stage list, name `related`.
  - Commit and push (`docs: roadmap after related destinations`).
- [ ] **Step 2 (controller):** after the next 06:00 UTC scan, read from Neon (read-only, URL never printed):
  - today's `related` stage counts from the run's log;
  - the row count in `related_links` and `related_checks`.
  - Expected: the stage ran ok. With no accepted links it reports `links_watched 0`.
  - Report to the user: the suggestions shown for their destinations (from `/destinations`) and any confirmed related deals.
