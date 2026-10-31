# ptopilot Plan 16: Hidden Gems

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A magazine of hand-approved "hidden gem" places for each person, with these parts:
- **Matching:** gems are picked for their trip styles.
- **Cadence:** about one new gem a week, with an archive of earlier issues.
- **Fares:** each gem carries a live-checked fare and a fit pill.
- **Action:** one tap turns a gem into a tracked destination.

**Architecture:**
- **The catalogue** is YAML files in the repo, written and approved with the owner in sessions, so no AI runs in production.
- **A new `gems` pipeline stage** publishes due issues per person and prices their newest gems. Prices come from the free Travelpayouts cache plus a capped number of free Google live checks.
- **Pages** reuse Plan 15's design system, `cover()` photos and in-place actions.

**Tech Stack:** Python, FastAPI, Jinja, Postgres, and the existing sources. No new dependency. The safe Markdown subset is rendered by a small in-house function.

**Spec:** [`docs/superpowers/specs/2026-10-31-ptopilot-hidden-gems-design.md`](../specs/2026-10-31-ptopilot-hidden-gems-design.md). The approved mockup is `.superpowers/brainstorm/480-1793447330/content/gems.html` (git-ignored; the controller hands its path to implementers).

**Order:** this plan runs after Plan 15 completes and reuses its components.

## Global Constraints

- **Config (exact):**
  ```python
  GEM_ISSUE_DAYS = 7
  GEM_WILDCARD_EVERY = 4
  GEM_PRICED_ISSUES = 4
  GEM_LIVE_CHECKS_PER_DAY = 8
  GEM_RECHECK_DAYS = 3
  GEM_CLAIM_STALE_DAYS = 365
  ```
- **Trip-style vocabulary (exact keys and labels):**
  - `hiking_camping` "🥾 Hiking & camping"
  - `city_hopping` "🏙 City hopping"
  - `rail` "🚆 Rail trips"
  - `beach` "🏖 Beach time"
  - `islands` "🏝 Islands"
  - `adventure` "🧭 Road trips & adventure"
  - `food_wine` "🍷 Food & wine"
  - `culture` "🏛 History & culture"
- **What is shown:**
  - only `approved` gems are ever issued or shown in a feed;
  - a `retired` gem's guide page opens only for people it was issued to;
  - `draft` gems are 404 for everyone;
  - any signed-in user can open any `approved` gem's guide page.
- **Gems are never hidden for price or dates.** The fare shows whenever one is known.
- **Fit pill copy (exact):**
  - "Fits your {Month} range · {n} PTO" (green);
  - "outside your dates" (orange);
  - "Checking fares…" (grey);
  - "No fares found lately" (grey).
- **Fares:**
  - free sources only, so never SerpApi;
  - the live source is `google_flights`;
  - the person's stop filters and the miserable-flight judge apply;
  - at most `GEM_LIVE_CHECKS_PER_DAY` live checks a day globally, counting persisted rows, so re-runs get no fresh allowance;
  - each (person, gem) is re-checked at most every `GEM_RECHECK_DAYS`.
- **Exclusions:** a gem whose airports overlap any of the person's active trackers' destination airports is never issued to them.
- **Photos:** Commons only, with attribution, through Plan 15's `photos` stage and `cover()` macro. Gem photo codes are `gem-{slug}`.
- **Process:**
  - migrations reach Neon before code that reads them deploys;
  - work on `main`, and every task commits and pushes with the suite green;
  - never print or commit secrets;
  - default pytest never touches the network;
  - the repo is public, so nothing personal goes in the catalogue, style guide or fixtures.

## Review Focus

1. **The catalogue is empty** (the first deploy, before the owner's first session):
   - `/gems` shows a friendly "The first issue is on its way" state;
   - the `gems` stage does nothing and doesn't fail.

   *Task 4: `test_an_empty_catalogue_is_a_quiet_no_op`; Task 5: `test_gems_page_with_no_issues_says_the_first_is_coming`.*
2. **A person with no planning year or no open ranges:** the fare is still priced, in the gem's best months over the next 12 months, and the pill reads "outside your dates". *Task 4: `test_no_open_ranges_prices_the_best_months`.*
3. **The person already tracks the gem's place** (same code or a shared airport):
   - it's never issued to them;
   - on a shared guide link, the button reads "Tracking".

   *Task 3: `test_tracked_places_are_never_issued`; Task 5: `test_track_button_reads_tracking_when_already_tracked`.*
4. **A gem is retired after it was issued:**
   - it leaves the feed;
   - its guide still opens for that person;
   - it's 404 for others;
   - a draft is 404 for everyone.

   *Task 5: `test_retired_gems_leave_the_feed_but_open_for_their_readers`, `test_drafts_are_404`.*
5. **A gem body containing HTML or a `javascript:` link:** it is escaped and never rendered as markup. *Task 2: `test_markdown_escapes_html_and_unsafe_links`.*

---

## File structure

```
ptopilot/core/trip_styles.py            # NEW: STYLES vocabulary (Task 1)
ptopilot/gems.py                        # NEW: Gem model, load_catalogue(), render_markdown() (Task 2)
ptopilot/data/gems/                     # NEW: one YAML per gem (starts empty; the owner's session fills it)
docs/gems/style-guide.md, docs/gems/README.md   # NEW: the voice and the session routine (Task 2)
ptopilot/core/gem_feed.py               # NEW: next_gem() selection, pure (Task 3)
ptopilot/pipeline/gems.py               # NEW: publish + price stage (Task 4)
ptopilot/pipeline/photos.py             # gem codes join the lookups (Task 4)
ptopilot/web/gems_view.py, templates/gems.html, gem.html   # NEW (Task 5)
ptopilot/db/migrations/versions/0015_trip_styles.py (Task 1), 0016_gems.py (Task 3)
```

---

### Task 1: Trip styles on the profile and in onboarding

**Files:**
- Create: `ptopilot/core/trip_styles.py`, migration `0015_trip_styles`.
- Modify: `ptopilot/db/models.py`, `ptopilot/profiles.py` (validation), `ptopilot/web/forms.py`, `templates/profile.html` (Travel style section), the onboarding step-3 partial, `static/app.css`.
- Test: `tests/web/test_trip_styles.py`.

**Interfaces:**
- **Produces:**
  - `STYLES: dict[str, str]`, key → label, exactly the Global Constraints vocabulary, in that order.
  - `User.trip_styles: list[str]`: `ARRAY(Text)`, `server_default '{}'`.
  - Profile validation rejects unknown keys.
  - Form wire format: repeated `trip_styles` checkbox fields. The merge-section logic treats the field as "Travel style" section data, so unticking all of them clears it.
- **UI:** toggle chips (checkboxes styled as chips), titled "Trip styles you love", with the hint "Pick any; we'll match hidden gems to them." It sits in the profile's Travel style section and on onboarding step 3, and autosaves like the rest of that section.

- [ ] **Step 1: Write the failing tests.**
```python
def test_styles_vocabulary_is_exact():
    assert list(STYLES) == ["hiking_camping", "city_hopping", "rail", "beach", "islands", "adventure", "food_wine", "culture"]
def test_profile_saves_and_clears_trip_styles(client, db): ...      # tick two → saved; untick all → []
def test_unknown_styles_are_refused(client, db): ...                 # "skydiving" → 400 with a plain-words error
def test_welcome_step_three_offers_trip_styles(client, db): ...
def test_trip_styles_post_without_js(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite (drift test) and ruff. Run upgrade, downgrade -1 and upgrade on the dev DB.
- [ ] **Step 5: Migrate Neon before pushing.** **Step 6: Commit and push** (`feat: trip styles you love`).

---

### Task 2: The catalogue, its loader and the style guide

**Files:**
- Create:
  - `ptopilot/gems.py`;
  - `ptopilot/data/gems/.gitkeep`;
  - `docs/gems/style-guide.md`;
  - `docs/gems/README.md`;
  - `tests/fixtures/gems/` (two or three example gems for tests only).
- Test: `tests/test_gems_catalogue.py`.

**Interfaces:**
- **Produces:**
  - `Claim(text: str, source_url: str, checked_on: date)`.
  - `Gem(slug, name, country, airports: tuple[str, ...], return_airports: tuple[str, ...], styles: tuple[str, ...], best_months: tuple[int, ...], headline: str, body: str, budget: str, daily_cost_usd: int, claims: tuple[Claim, ...], status: Literal["draft","approved","retired"], approved_on: date | None, photo: PlacePhoto | None)`.
    - `Gem.code` returns `f"gem-{slug}"`.
  - `load_catalogue(folder: Path = DATA/"gems") -> tuple[Gem, ...]`:
    - cached, sorted by `approved_on` then `slug`;
    - raises `ValueError` naming the file on any invalid entry.
  - `approved(gems) -> tuple[Gem, ...]`.
  - `stale_claims(gems, today) -> list[tuple[Gem, Claim]]`: claims older than `GEM_CLAIM_STALE_DAYS`.
  - `render_markdown(text: str) -> Markup`:
    - **supports:** paragraphs, `**bold**`, `*italic*`, `[text](https://…)` links, `- ` bullet lists, `## ` subheadings;
    - escapes everything else;
    - only `http(s)` links are allowed, and they render with `rel="noopener"`.
- **Validation:**
  - every airport is a catalogue airport;
  - styles come from `STYLES`;
  - best months are 1–12;
  - an approved gem has `approved_on` and at least one claim;
  - each `source_url` is http(s);
  - a `photo` block follows Plan 15's built-in photo rules (Commons File page, free licence);
  - slugs are unique and match the file name.
- **`docs/gems/style-guide.md`:**
  - the voice: a friend telling you how they did it;
  - the budget-angle rule: whole-trip cost, with free or cheap lodging named when it exists;
  - per-style emphasis;
  - banned filler ("hidden gem", "nestled", "breathtaking", "bucket list");
  - the claims rule: every checkable fact listed with a source;
  - a "Notes from the owner" section that sessions append to.
- **`docs/gems/README.md`:** the session routine:
  1. run `python -m ptopilot.gems check` (lists stale claims and validates the folder);
  2. retire stale gems;
  3. draft new gems as `status: draft`;
  4. the owner approves or rejects with a note; redraft and append the note's lesson to the style guide;
  5. commit and push.
- **`python -m ptopilot.gems check`** prints the validation result and stale claims; it exits 1 on invalid files.

- [ ] **Step 1: Write the failing tests.**
```python
def test_fixture_catalogue_loads_and_sorts(): ...
def test_invalid_entries_name_their_file(): ...   # unknown style, unknown airport, approved without claims, slug ≠ filename
def test_only_approved_gems_are_approved(): ...
def test_stale_claims_are_listed(): ...            # checked_on 400 days ago → listed
def test_markdown_escapes_html_and_unsafe_links(): # "<script>", [x](javascript:alert(1)) → escaped / plain text
def test_markdown_renders_the_subset(): ...
def test_shipped_catalogue_is_valid(): ...         # load_catalogue() on the real folder passes (empty is fine)
def test_check_command_exit_codes(): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(gems): the catalogue and its style guide`).

---

### Task 3: Issues and selection

**Files:**
- Create: `ptopilot/core/gem_feed.py`, migration `0016_gems`.
- Modify: `ptopilot/db/models.py`.
- Test: `tests/core/test_gem_feed.py`, `tests/test_gem_issues.py`.

**Interfaces:**
- **Migration `0016_gems`:**
  - `gem_issues`:
    - id;
    - user_id FK CASCADE;
    - gem_slug VARCHAR(64);
    - published_on DATE;
    - unique (user_id, gem_slug).
  - `gem_fares`:
    - id;
    - user_id FK CASCADE;
    - gem_slug;
    - origin, airport, return_airport;
    - depart_date, return_date (nullable);
    - price NUMERIC(10,2) NULL, currency;
    - status VARCHAR(6), CHECK in `('found','none','failed')`;
    - fits BOOLEAN NULL;
    - fit_month SMALLINT NULL, pto_cost SMALLINT NULL;
    - deep_link TEXT NULL;
    - checked_at;
    - run_date DATE indexed.
  - A working downgrade.
- **Produces:**
  - `GemIssue` and `GemFare` models.
  - `next_gem(gems: Sequence[Gem], issued: Sequence[str], styles: Sequence[str], tracked_airports: Collection[str], issue_number: int) -> Gem | None`. Pure.
    - Candidates are approved gems not in `issued`, minus those whose airports overlap `tracked_airports`.
    - When `issue_number % GEM_WILDCARD_EVERY == 0` (1-based) or `styles` is empty, take the first candidate in catalogue order.
    - Otherwise take the candidate with the most shared styles, ties broken by catalogue order.
    - Return None when there are no candidates.
  - `publish_due(s: Session, user: User, today: date, gems: Sequence[Gem]) -> GemIssue | None`:
    - publishes when the latest issue is ≥ `GEM_ISSUE_DAYS` old, or there is none;
    - an idempotent insert (ON CONFLICT DO NOTHING).
  - `tracked_airports(s, user, geo) -> set[str]`.

- [ ] **Step 1: Write the failing tests.**
```python
def test_best_style_match_wins_ties_by_catalogue_order(): ...
def test_every_fourth_issue_is_a_wildcard(): ...
def test_no_styles_means_catalogue_order(): ...
def test_tracked_places_are_never_issued(): ...      # gem airport shared with an active tracker → skipped
def test_already_issued_and_unapproved_are_skipped(): ...
def test_publish_due_waits_seven_days(db): ...         # issue 6 days ago → None; 7 days → new issue
def test_publish_due_is_idempotent(db): ...
def test_catalogue_exhausted_publishes_nothing(db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite (drift test) and ruff; upgrade, downgrade -1 and upgrade on dev. **Step 5: Migrate Neon before pushing.** **Step 6: Commit and push** (`feat(gems): weekly issues matched to trip styles`).

---

### Task 4: The `gems` stage: publish and price

**Files:**
- Create: `ptopilot/pipeline/gems.py`.
- Modify:
  - `ptopilot/pipeline/runner.py`: `gems` after `related`, before `photos`, and in `CONTINUE_ON_FAILURE`;
  - `.github/workflows/scan.yml`: stage options;
  - `ptopilot/pipeline/photos.py`: `gem-{slug}` codes of issued gems join `_due`, with the gem's `name` and `country`; a gem's own `photo` block wins, as built-ins do;
  - `ptopilot/pipeline/health.py`: one line: gems published / priced / found.
- Test: `tests/pipeline/test_gems_stage.py`.

**Interfaces:**
- **Consumes:**
  - Task 2 `load_catalogue`, `approved`;
  - Task 3 `publish_due`, `GemFare`, `tracked_airports`;
  - Plan 14's `related` helpers where they fit: month scan, `passing_filters`, `best_option` with `typical=None`, which forgives nothing;
  - `planning.year_ranges`, `plan_totals.remaining_by_year`, `expand.profile_for(user).calendar.pto_cost`.
- **Produces:** `gems.run(ctx) -> dict[str, int]` with counts:
  - `users`, `published`;
  - `priced_due`, `scans`, `scans_failed`;
  - `checked`, `found`, `none`, `failed`;
  - `held_live_cap`.
- **Flow:**
  1. **Publish:** for each user with any active tracker or a profile, `publish_due` with today's catalogue.
  2. **Choose what to price:** for each user's newest `GEM_PRICED_ISSUES` issues whose last `gem_fares` row is older than `GEM_RECHECK_DAYS` or missing, with retired gems skipped.
  3. **Months to scan:** months of the person's open ranges from today on. With none, the gem's `best_months` in the next 12 months.
  4. **Trip length:** the person's `ideal_trip_days`, else the midpoint of min..max.
  5. **Cheapest candidate:** one month scan per (home airport, gem airport, month); keep round-trip quotes departing after today whose length is within ±2 of the trip length, and take the cheapest per (user, gem).
  6. **Live check:** with the google_flights source while today's `gem_fares` count is below `GEM_LIVE_CHECKS_PER_DAY`. Open-jaw gems search `airports[0]` in and `return_airports[0]` home.
  7. **Store one row per attempt:**
     - `found`, with price, dates, `fits` (inside an open range and PTO cost ≤ that year's remaining), `fit_month` and `pto_cost`;
     - `none`, when there was no cached candidate or no acceptable live option;
     - `failed`, on a source error.
- **Fallbacks:** a dry run makes no live checks and writes no rows (`would_check` count). No `month_source` → the pricing part is skipped; publishing still runs.

- [ ] **Step 1: Write the failing tests** (fake month source and live sources; no network):
```python
def test_an_empty_catalogue_is_a_quiet_no_op(make_ctx): ...
def test_due_issues_are_published_and_priced(make_ctx): ...
def test_no_open_ranges_prices_the_best_months(make_ctx): ...     # stored fits False
def test_no_cached_candidate_stores_none(make_ctx): ...
def test_live_checks_are_capped_and_rerun_safe(make_ctx): ...
def test_recheck_waits_three_days(make_ctx): ...
def test_serpapi_is_never_used(make_ctx): ...
def test_a_miserable_only_result_is_none(make_ctx): ...
def test_dry_run_checks_nothing(make_ctx): ...
def test_issued_gems_get_photos(make_ctx): ...                    # photos stage _due includes gem-{slug}
def test_gems_runs_after_related_and_before_photos(): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(gems): weekly publishing and live fares`).

---

### Task 5: The pages

**Files:**
- Create: `ptopilot/web/gems_view.py`, `templates/gems.html`, `templates/gem.html`.
- Modify: `ptopilot/web/app.py`, `templates/base.html` (nav "Hidden gems"), `templates/dashboard.html` (small card), `static/app.css`.
- Test: `tests/web/test_gems_pages.py`.

**Interfaces:**
- **Consumes:** Tasks 2–4, Plan 15's `cover()`, `photo_for`, in-place `data-inplace` forms, and `add_destination`.
- **Produces:**
  - `GemCard(gem, issue: GemIssue | None, fare: GemFare | None, photo, tracked: bool)`.
  - `fit_pill(fare: GemFare | None) -> tuple[str, str]`: copy and tone (`green` | `orange` | `grey`), with the exact copy from the Global Constraints.
- **`GET /gems`** (signed-in):
  - first, publishes the first issue if there is none (`publish_due`);
  - "For you: {style chips}" with an "edit" link to `/profile#travel-style`, or "For you: everything" when styles are empty;
  - the newest issue as the feature, laid out as in the approved mockup;
  - "Earlier issues" as photo cards, newest first;
  - empty state: "The first issue is on its way."
- **`GET /gems/{slug}`:**
  - the full guide: cover and credit, styles, best months, `render_markdown(body)`, the budget box with "~${daily_cost_usd}/day", the person's fare and pill, and "Facts we checked" (claims with source links);
  - buttons: "Track this place" or "Tracking";
  - access rules exactly as the Global Constraints.
- **`POST /gems/{slug}/track`:**
  - in place;
  - calls `add_destination` with the gem's `airports` (round trip only) and the person's ideal length, or 10 when none;
  - JSON `{"ok": true, "tracker_id": …}`; without JS, a redirect to `/trackers/{id}`.
- **Dashboard:** a "This week's hidden gem" card under the destination cards, shown when an issue exists.

- [ ] **Step 1: Write the failing tests.**
```python
def test_gems_page_with_no_issues_says_the_first_is_coming(client, db): ...
def test_first_visit_publishes_and_shows_the_feature(client, db): ...
def test_fit_pill_copy(): ...                                     # all four states, exact copy
def test_retired_gems_leave_the_feed_but_open_for_their_readers(client, db): ...
def test_drafts_are_404(client, db): ...
def test_any_signed_in_user_can_open_an_approved_guide(client, db): ...
def test_track_button_reads_tracking_when_already_tracked(client, db): ...
def test_track_adds_the_destination_in_place(client, db): ...
def test_guide_lists_facts_with_sources(client, db): ...
def test_dashboard_shows_this_weeks_gem(client, db): ...
def test_gems_need_sign_in(client): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check at 1280 and 390 px with two fixture gems copied into the dev catalogue (not committed).
- [ ] **Step 6: Commit and push** (`feat(gems): the hidden gems pages`).

---

### Task 6: Roadmap, then the first catalogue session

- [ ] **Step 1:**
  - In `ROADMAP.md`, move "Hidden gems" to Done, noting that the catalogue is curated in sessions.
  - The README gains a short "Hidden gems catalogue" note pointing to `docs/gems/README.md`.
  - Commit and push (`docs: roadmap after hidden gems`).
- [ ] **Step 2 (controller, with the owner — not a subagent task):**
  - run the first catalogue session per `docs/gems/README.md`;
  - write Lofoten and Ljubljana with the owner as the style guide's reference examples;
  - draft about 10 more across styles;
  - the owner approves or rejects each; push the approved ones.
