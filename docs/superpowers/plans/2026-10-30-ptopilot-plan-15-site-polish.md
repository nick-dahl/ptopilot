# ptopilot Plan 15: Site Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the site feel like a polished travel product, with the calm, data-first polish of Google Flights. It gets:
- guided onboarding;
- one Google-Flights-style input pattern everywhere;
- a "reason you came" dashboard hero;
- cover photos;
- a livelier destination page;
- a landing page that sells it.

**Architecture:**
- **Pages:** server-rendered Jinja pages stay the source of truth.
- **Scripts:** small vanilla JS modules in `ptopilot/web/static/` enhance them:
  - chips;
  - sliders;
  - in-place saves via `fetch`;
  - the hero sheet;
  - chart hover.
- **No-JS fallback:** every form still posts and works without JS. Enhanced requests get JSON from the same routes.
- **Photos:** fetched by a small pipeline step and stored per place.

**Tech Stack:** FastAPI, Jinja, the existing `app.css` design tokens, and vanilla ES modules. No framework, bundler or new Python dependency; `httpx` is already present.

**Spec:** [`docs/superpowers/specs/2026-10-30-ptopilot-site-polish-design.md`](../specs/2026-10-30-ptopilot-site-polish-design.md). Approved mockups: `.superpowers/brainstorm/1641-1793395817/content/inputs.html` and `dashboard.html` (git-ignored; the controller hands paths to implementers).

## Global Constraints

- **No front-end framework, bundler, npm build, or new Python dependency.** Scripts are small, readable vanilla JS, loaded with `<script type="module" src="/static/...">`.
- **Progressive enhancement:**
  - every form works as a plain HTML POST without JS.
  - **JSON on request:** with JS, the same route answers JSON when the request carries `Accept: application/json`. It returns `{"ok": true, ...}` on success, or a 4xx with `{"ok": false, "errors": [...]}`.
- **No fixed inline styles in web templates** (`tests/web/test_web_polish.py` enforces this). Data-driven values such as colours, positions and image URLs may be inline.
- **Design tokens:** use the existing ones in `app.css` (Fraunces + Inter, `--dest`, `--rare`, …). New tokens go in `:root`.
- **Motion:**
  - state changes ease over 150–200 ms;
  - `@media (prefers-reduced-motion: reduce)` disables transitions and animation.
- **Accessibility:**
  - everything is keyboard operable, with visible focus;
  - chips are a list with remove buttons labelled "Remove {code}";
  - sliders are `input[type=range]`;
  - the dialog has `role="dialog"`, `aria-modal`, and Esc to close;
  - colour is never the only signal.
- **Layout:** works at 360 px wide and up, with no horizontal scroll.
- **Field mapping (exact):**
  - weather:
    - "Only the best months" = `strict`;
    - "Shoulder season is fine" = `normal`;
    - "Any time if it's cheap" = `relaxed`.
  - "Shorter flights":
    - Nonstop only / Up to 1 stop / Up to 2 stops;
    - writes `max_stops_short` 0 / 1 / 2.
  - "Long-haul":
    - Up to 1 stop / Up to 2 stops;
    - writes `max_stops_long` 1 / 2.
  - trip length:
    - slider handles write `min_trip_days` and `max_trip_days`;
    - the ★ writes `ideal_trip_days`;
    - "No preference" clears it to null;
    - the ★ always lies between the handles.
- **Auth:**
  - `/welcome`, `/api/*` and every in-place endpoint are signed-in only: a signed-out request gets a redirect to `/` for HTML and 401 for JSON.
  - The landing page's sign-in box is the only signed-out form.
- **URLs that must keep working:**
  - `/`;
  - `/trackers/{id}`;
  - `/plan`, `/plan/{year}`, `/plan/new`;
  - `/destinations`;
  - `/profile`;
  - `/s/{token}` (digest snooze links);
  - `/login`, `/auth`.
- **Photos:**
  - only Wikimedia Commons images, used with attribution;
  - requests send `User-Agent: ptopilot/1.0 (https://github.com/nick-dahl/ptopilot)`;
  - never fetched inside a web request.
- **Process:**
  - migrations reach Neon before code that reads them deploys;
  - work on `main`, and every task commits and pushes with the suite green;
  - never print or commit secrets;
  - default pytest never touches the network;
  - the repo is public, so no personal data goes in fixtures or committed screenshots.

## Review Focus

1. **JS disabled or a script fails to load:** every form still submits and saves through its normal POST. Chips render as server-side chips with a text field fallback, and the slider falls back to number fields. *Task 2: `test_profile_form_posts_without_js`; Task 4: `test_welcome_steps_post_without_js`.*
2. **A new user leaves onboarding after step 2 and signs in again next day:** they resume at step 3 with steps 1–2 saved. An existing user (backfilled `onboarded_at`) is never redirected to `/welcome`. *Task 4: `test_onboarding_resumes_at_the_next_step`, `test_existing_users_are_never_sent_to_welcome`.*
3. **Type-ahead gets one character, junk, or an unknown code submitted with Enter:**
   - fewer than 2 characters → `[]`;
   - junk → `[]`;
   - an unknown code is refused with an inline message, never saved.

   *Task 2: `test_airport_search_needs_two_characters`, `test_unknown_airport_codes_are_refused`.*
4. **The photo lookup returns an SVG map, a tiny image, a 404, or times out:** the place is stored with `status none`, the card keeps its gradient, and the scan continues. *Task 5: `test_maps_flags_small_and_missing_images_are_rejected`, `test_a_photo_failure_never_fails_the_scan`.*
5. **A destination with no trips today, or only ruled-out trips:**
   - the date grid shows an empty state, not an error;
   - the dashboard shows no hero for it.

   *Task 6: `test_quiet_day_has_no_hero`; Task 7: `test_date_grid_with_no_trips_shows_an_empty_state`.*

---

## File structure

```
ptopilot/web/static/app.css             # tightened tokens + new component styles (Task 1, then each task)
ptopilot/web/static/ui.js               # NEW: fetch helper, in-place forms, Saved tick, toasts (Task 1)
ptopilot/web/static/chips.js            # NEW: airport/place chip input with type-ahead (Task 2)
ptopilot/web/static/range.js            # NEW: dual slider + ★ (Task 2)
ptopilot/web/static/hero.js             # NEW: standout arrival dialog / sheet (Task 6)
ptopilot/web/static/chart.js            # NEW: trend chart hover, date-grid selection (Task 7)
ptopilot/web/templates/_inputs.html     # NEW: Jinja macros chips(), segmented(), stepper(), trip_range(), switch() (Task 2)
ptopilot/web/api.py                     # NEW: /api/airports, /api/places (Task 2)
ptopilot/web/onboarding.py, templates/welcome.html   # NEW (Task 4)
ptopilot/photos.py, pipeline/photos.py  # NEW (Task 5)
ptopilot/web/grid.py                    # NEW: date grid (Task 7)
ptopilot/web/app.py, templates/*.html   # each task
ptopilot/db/migrations/versions/0013_onboarded.py (Task 4), 0014_place_photos.py (Task 5)
```

---

### Task 1: Design-system tightening and in-place actions

**Files:**
- Modify: `static/app.css`, `templates/base.html`, `_components.html`, `ptopilot/web/app.py`.
- Create: `static/ui.js`.
- Test: `tests/web/test_in_place.py`.

**Interfaces:**
- **Produces:**
  - `wants_json(request: Request) -> bool` in `ptopilot/web/app.py`: true when `Accept` contains `application/json`.
  - `json_or_redirect(request, url: str, **payload) -> Response`:
    - JSON `{"ok": true, **payload}` when `wants_json`;
    - otherwise the existing 303 redirect.
  - **`ui.js`:**
    - any `<form data-inplace>` submits with `fetch` and `Accept: application/json`;
    - on `ok` it runs `form.dataset.after`: `reload-section`, `remove`, or `none`;
    - it shows a "Saved" tick next to the submit control, or inline errors from `errors`;
    - also `toast(message)`.
  - **`reload-section`:** `ui.js` re-fetches the current page and swaps the element with the same `id` as the form's `data-section`.
- **Applied to:**
  - snooze and unsnooze;
  - book and cancel (planner and tracker page);
  - plan and unplan trip;
  - related accept and dismiss;
  - destination remove.
- **Visual tightening, toward the approved mockups:**
  - top nav with active state;
  - cards with 14 px radius and a soft shadow;
  - more white space;
  - a slim PTO bar;
  - consistent buttons: primary, secondary and quiet.
  - No change to page structure beyond that.

- [ ] **Step 1: Write the failing tests.**
```python
def test_snooze_answers_json_when_asked(client, db): ...      # Accept: application/json → 200 {"ok": true}
def test_snooze_still_redirects_without_json(client, db): ... # → 303 as today
def test_json_errors_are_4xx_with_messages(client, db): ...    # e.g. booking an overlapping trip → 409/400 {"ok": false, "errors": [...]}
def test_in_place_endpoints_need_sign_in(client): ...         # JSON → 401
def test_pages_load_ui_js_as_a_module(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check at 1280 and 390 px of `/`, `/trackers/{id}`, `/plan/{year}` and `/destinations` on a local run against the dev DB. Snooze and book work without reload; with JS disabled they still work.
- [ ] **Step 6: Commit and push** (`feat(web): tighter look and in-place actions`).

---

### Task 2: The input components and the profile page

**Files:**
- Create: `static/chips.js`, `static/range.js`, `templates/_inputs.html`, `ptopilot/web/api.py`.
- Modify: `templates/profile.html`, `ptopilot/web/app.py`, `ptopilot/web/forms.py`, `static/app.css`.
- Test: `tests/web/test_inputs.py`, `tests/web/test_api.py`.

**Interfaces:**
- **Produces:**
  - **`GET /api/airports?q=&near=`** returns `[{"code","name","city","country","km"}]`:
    - at most 6 results;
    - only `large` and `medium` airports;
    - `km` is measured from `near` when given;
    - ordered by match kind as `AirportCatalog.search` does, then by km.
    - Fewer than 2 characters → `[]`.
  - **`GET /api/places?q=`** returns the destination search as `[{"code","name","country","airports":[...]}]`, reusing whatever `/destinations` search uses.
  - **Macros in `_inputs.html`:**
    - **`chips(name, items, placeholder, source)`:**
      - server-renders each chip;
      - writes a hidden input `name` holding a comma list, which `form_to_profile` already parses;
      - also writes a visible text input for no-JS edits;
      - `source` is `airports` or `places`.
    - **`segmented(name, options, value)`:** radio inputs styled as cards, so it works without JS.
    - **`stepper(name, value, min, max)`:** a number input with − and + buttons.
    - **`trip_range(min_value, max_value, ideal, lo, hi)`:**
      - two range inputs plus the ★ and a "No preference" chip;
      - without JS it falls back to three number fields with the same names.
    - **`switch(name, checked, label)`.**
  - **`chips.js`:**
    - type-ahead from `source`, up to 6 rows;
    - keys ↑ ↓ Enter Esc, and Backspace on an empty field removes the last chip;
    - a duplicate shakes and is refused;
    - **an unknown code isn't added.** Only rows from the API become chips; plain text on Enter with no match shows "No airport matches '…'".
  - **`range.js`:** keeps the ★ between the handles and live-updates the "5 to 14 days away · ideally 10" line.
- **Profile page rebuilt in sections**, each a `<form data-inplace>` that posts to `POST /profile`:
  - Airports;
  - Time off: PTO stepper, calendar country, holidays-you-work chips, company days off as dates;
  - Travel style: trip range, weather segmented, two stops segmented, overnight switch, leave-after-work switch plus a time shown only when on.
- **Partial saves:**
  - `POST /profile` keeps working as a full form, as today.
  - A JSON request may carry only one section's fields. The server merges them over `profile_to_form(current user)` and then runs the existing `parse_profile` validation.
  - The merge happens in `forms.py`: `merge_section(current: dict[str, str], submitted: Mapping[str, str]) -> dict[str, str]`.
  - The holidays-you-work chips use the selected calendar's holiday names, from `WorkCalendar` holiday names for the coming year.

- [ ] **Step 1: Write the failing tests.**
```python
def test_airport_search_needs_two_characters(client, db): ...   # "p" → []
def test_airport_search_finds_city_and_code_nearest_first(client, db): ...  # q="new", near="PHL" → EWR before LGA; only large/medium
def test_unknown_airport_codes_are_refused(client, db): ...       # POST nearby_airports="ZZZ" → 400 with a message naming ZZZ
def test_profile_form_posts_without_js(client, db): ...           # the rendered form's hidden/visible fields round-trip a full save
def test_a_section_saves_on_its_own(client, db): ...              # JSON with only weather_tolerance="strict" → saved, other fields unchanged
def test_section_errors_come_back_as_json(client, db): ...        # min_trip_days > max → 400 {"ok": false, "errors": [...]}
def test_weather_and_stops_map_to_the_existing_values(client, db): ...  # labels → strict/normal/relaxed, 0/1/2, 1/2
def test_no_preference_clears_the_ideal_length(client, db): ...
def test_api_needs_sign_in(client): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check of `/profile` at 1280 and 390 px:
  - typing "new" suggests EWR and LGA;
  - Enter adds a chip;
  - × removes it;
  - the slider and ★ behave;
  - each section shows "Saved";
  - with JS off the page still saves.
- [ ] **Step 6: Commit and push** (`feat(web): Google-Flights-style inputs on the profile page`).

---

### Task 3: The inputs everywhere else

**Files:**
- Modify: `templates/destinations.html`, `plan.html`, `plan_new.html`, `destination.html`, `ptopilot/web/app.py`.
- Test: `tests/web/test_inputs_elsewhere.py`.

**Interfaces:**
- **Consumes:** Task 2's macros and scripts, and Task 1's `data-inplace`.
- **Destinations page:**
  - **Search:** a single type-ahead using `/api/places`. Picking a place opens an inline "add" card with the place's airports as pre-selected chips, nearby ones offered as add-chips, and a target-length stepper.
  - **Adding** goes through the existing `POST /destinations`, in place: the new card appears without a reload.
  - **Related suggestions** show as small cards with Accept and Dismiss, in place.
- **Planner:**
  - the PTO and other-time-off fields become steppers saving in place;
  - target lengths become steppers;
  - the calendar is unchanged except for styling.
- **`/plan/new`:** the destination checkboxes become selectable cards, still checkboxes underneath.

- [ ] **Step 1: Write the failing tests.**
```python
def test_adding_a_place_returns_its_card_as_json(client, db): ...  # JSON add → {"ok": true, "tracker_id": ..}; the page then lists it
def test_destinations_page_works_without_js(client, db): ...       # the plain form still adds a place
def test_planner_pto_saves_in_place(client, db): ...
def test_plan_new_cards_are_still_checkboxes(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check of `/destinations` (search "lisb" → Lisbon → add), `/plan/{year}` and `/plan/new`.
- [ ] **Step 6: Commit and push** (`feat(web): the same inputs on destinations and the planner`).

---

### Task 4: Guided onboarding

**Files:**
- Create: `ptopilot/web/onboarding.py`, `templates/welcome.html`, migration `0013_onboarded.py`.
- Modify: `ptopilot/db/models.py`, `ptopilot/web/app.py`.
- Test: `tests/web/test_welcome.py`.

**Interfaces:**
- **Migration:**
  - `users.onboarded_at TIMESTAMPTZ NULL`;
  - **upgrade backfills `now()` for every existing row**;
  - a working downgrade.
- **Routes:**
  - `GET /welcome` redirects to `/welcome/{n}`, the first unfinished step;
  - `GET /welcome/{n}` and `POST /welcome/{n}` for n in 1–4.
  - Each step reuses Task 2's and Task 3's macros. A 4-segment progress bar, Back, and Next.
  - "Skip for now" appears on steps 2–4. It sets `onboarded_at` and lands on `/`.
- **Step 1, airports:**
  - creates the User if missing, with the first chip as `home_airport` and the rest as `nearby_airports`;
  - `country` and `holiday_calendar` = the home airport's catalog country;
  - `pto_days_total` 15, `max_trip_days` 14;
  - everything else takes the model's server defaults.
- **Step 2, time off:** PTO, calendar, holidays worked, company days off.
- **Step 3, travel style:** the travel-style section from Task 2.
- **Step 4, destinations:**
  - add 1–5 places, as on the destinations page;
  - "Start planning" sets `onboarded_at` and creates the current planning year with the same function `/plan/new` uses (`planning.start_year`, with the added destinations);
  - it then redirects to `/plan/{year}`.
- **Step completion** is stored on the user, so it survives a new browser:
  - the migration also adds `users.welcome_step SMALLINT NOT NULL DEFAULT 0`, the furthest finished step;
  - each successful step POST sets it to `max(current, n)`;
  - `/welcome` opens step `welcome_step + 1`, capped at 4.
- **Redirects:**
  - `/` and `/profile` send a signed-in email with no user row, or a user with `onboarded_at` null, to `/welcome`;
  - every other signed-in user is untouched;
  - `/profile` stays reachable from the onboarding pages via "Skip".
- **Copy:**
  - each step has one heading and one sentence of why, friendly and short.
  - Step headings (exact):
    - "Where do you fly from?"
    - "Your time off"
    - "How you like to travel"
    - "Where would you love to go?"

- [ ] **Step 1: Write the failing tests.**
```python
def test_a_new_sign_in_lands_on_welcome(client, db): ...
def test_step_one_creates_the_user_from_airport_chips(client, db): ...  # PHL,JFK → home PHL, nearby [JFK], country US, calendar US
def test_onboarding_resumes_at_the_next_step(client, db): ...           # finish step 2, new client with same sign-in → /welcome → step 3
def test_existing_users_are_never_sent_to_welcome(client, db): ...      # onboarded_at set → / renders the dashboard
def test_start_planning_creates_the_year_and_opens_the_planner(client, db): ...
def test_skip_for_now_finishes_onboarding(client, db): ...
def test_welcome_steps_post_without_js(client, db): ...
def test_welcome_needs_sign_in(client): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite (the drift test included) and ruff. Run upgrade, downgrade -1 and upgrade on the local dev DB.
- [ ] **Step 5: Migrate Neon before pushing** (guarded snippet; URL never printed). **Step 6 (controller):** a browser walk-through of a brand-new user on a local run at 390 px.
- [ ] **Step 7: Commit and push** (`feat(web): guided onboarding`).

---

### Task 5: Cover photos

**Files:**
- Create: `ptopilot/photos.py`, `ptopilot/pipeline/photos.py`, migration `0014_place_photos.py`, `templates/credits.html`.
- Modify: `ptopilot/data/geo.yaml` (a `photo:` block per built-in place), `ptopilot/pipeline/runner.py`, `ptopilot/web/app.py`, `templates/_components.html`.
- Test: `tests/test_photos.py`, `tests/pipeline/test_photos_stage.py`, `tests/web/test_photo_display.py`.

**Interfaces:**
- **Migration:** a `place_photos` table:
  - `code VARCHAR(32) PK`;
  - `image_url TEXT NULL`, `width INT NULL`, `height INT NULL`;
  - `author TEXT NULL`, `licence TEXT NULL`, `source_url TEXT NULL`;
  - `status VARCHAR(4)` CHECK in `('ok','none')`;
  - `fetched_at TIMESTAMPTZ`.
- **Produces:**
  - `PlacePhoto(code, image_url, width, height, author, licence, source_url)`.
  - **`lookup_photo(name: str, country_name: str, client: httpx.Client) -> PlacePhoto | None`** in `ptopilot/photos.py`:
    - calls the Wikipedia REST summary for `name`, falling back to `"{name}, {country_name}"`;
    - takes `originalimage`, accepting only a JPEG at least 800 px wide;
    - gets the attribution from the Commons `imageinfo` `extmetadata` (Artist, LicenseShortName, DescriptionUrl), with HTML stripped from the artist;
    - builds `image_url` as a 1280-px thumbnail URL;
    - None when no acceptable image exists.
  - **`photo_for(code: str, s: Session) -> PlacePhoto | None`**:
    - a built-in place's `geo.yaml` `photo:` block wins;
    - otherwise the `place_photos` row with `status ok`;
    - otherwise None.
  - **Pipeline stage `photos`**, placed after `related` and before `alerts`, in `CONTINUE_ON_FAILURE`:
    - for each place code used by an active tracker or an accepted related link, with no row, or a `none` row older than 30 days, it looks the place up;
    - it stores `ok` or `none`;
    - at most 20 lookups per run;
    - counts `looked_up`, `found`, `none`, `failed`.
  - **Built-in photos:**
    - the implementer picks Commons files for TH, LIS, TYO, PATAGONIA, AZORES, MADEIRA and CAMINO_PORTUGUES;
    - each entry records `image_url`, `author`, `licence` and `source_url`;
    - free licences only (CC0, CC BY, CC BY-SA, PD);
    - each `source_url` must be a commons.wikimedia.org file page.
  - **Display:**
    - `_components.html` gets `cover(dest, photo)`: a background image with a darkening gradient and the destination-colour gradient underneath, so a failed load shows the gradient;
    - `loading="lazy"` for `<img>` uses;
    - "Photo: {author} · {licence}" credit on hover or focus;
    - **`GET /credits`** lists every photo shown with its attribution, and is public;
    - `/api/places` results gain `"photo"` (the thumbnail URL or null), and the place dropdown shows it as a small square image.

- [ ] **Step 1: Write the failing tests** (a fake `httpx` transport; no network):
```python
def test_a_jpeg_lead_image_is_accepted_with_attribution(): ...
def test_maps_flags_small_and_missing_images_are_rejected(): ...  # SVG → None; 640px JPEG → None; 404 → None; timeout → None
def test_name_then_name_and_country_are_tried(): ...
def test_built_in_photos_have_free_licences_and_commons_sources(): ...  # every geo.yaml photo block
def test_the_stage_fills_missing_places_and_retries_none_after_30_days(make_ctx): ...
def test_a_photo_failure_never_fails_the_scan(make_ctx): ...
def test_cards_fall_back_to_the_gradient_without_a_photo(client, db): ...
def test_credits_lists_shown_photos(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite (drift test) and ruff; also upgrade, downgrade -1 and upgrade on dev. **Step 5: Migrate Neon before pushing.**
- [ ] **Step 6: Commit and push** (`feat: cover photos for every destination`).

---

### Task 6: Dashboard hero and photo cards

**Files:**
- Create: `static/hero.js`.
- Modify: `templates/dashboard.html`, `_components.html`, `ptopilot/web/history.py`, `ptopilot/web/app.py`, `static/app.css`.
- Test: `tests/web/test_hero.py`.

**Interfaces:**
- **Consumes:**
  - Task 5's `photo_for`/`cover`;
  - `destination_summaries`, `trend`, `viz.trend_chart`;
  - `TripOption.expected_days`/`standout`/`duration_note`.
- **Produces:**
  - **`hero_deal(summaries: list[DestinationSummary]) -> DestinationSummary | None`**:
    - the best standout by go-now; else the best `great` deal; else None;
    - snoozed, booked and ruled-out summaries are never the hero.
  - **`sparkline(points: list[TrendPoint], width=230, height=60) -> str | None`**: an SVG polyline `points` string, with None under MIN_TREND_POINTS.
  - **`last_scan(s, user) -> tuple[datetime | None, int]`**: the time of today's latest scan, and how many trips were checked for the user.
- **Hero** (the approved `dashboard.html` mockup):
  - the cover photo;
  - the pill: "Rare · {duration}" for a standout, else the duration label, else "Great deal";
  - "{destination}, {Month YYYY}";
  - the price and "{pct}% below typical ({typical})";
  - "{origin} → {arrival} · {dates} · {days} days for {pto} PTO · {stops}";
  - the sparkline;
  - View flights, I booked this (in place), and Snooze.
  - **Countdown chip** "~{n} days / before it's likely gone", only when `expected_days ≤ 7`.
- **Quiet day:**
  - no hero;
  - one line: "No standout fares today · checked {n} trips at {HH:MM}".
- **Arrival dialog** (`hero.js`):
  - only when the hero is a standout;
  - shows once per candidate id, remembered in `localStorage` under `ptopilot:seen:{candidate_id}`, with try/catch;
  - a centred dialog at ≥ 768 px, a bottom sheet below that;
  - Esc, ×, or a click outside closes it.
- **Photo cards:**
  - cover, name, best price and level, dates and PTO, and a trend arrow;
  - badges for Snoozed and Booked;
  - the whole card links to `/trackers/{id}`.
- **The PTO banner** is a slim bar.

- [ ] **Step 1: Write the failing tests.**
```python
def test_hero_prefers_a_standout_then_a_great_deal(): ...
def test_snoozed_booked_or_ruled_out_are_never_the_hero(): ...
def test_quiet_day_has_no_hero(client, db): ...                 # and shows "No standout fares today · checked"
def test_hero_shows_the_countdown_only_within_a_week(client, db): ...
def test_standout_hero_carries_the_dialog_hook(client, db): ...  # data-candidate-id present only for a standout
def test_cards_link_to_the_destination_page(client, db): ...
def test_sparkline_needs_enough_points(): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check at 1280 and 390 px with the dev DB seeded with a standout and with a quiet day:
  - the dialog appears once and not on reload;
  - the sheet on a phone.
- [ ] **Step 6: Commit and push** (`feat(web): the deal that brought you here`).

---

### Task 7: Destination page

**Files:**
- Create: `ptopilot/web/grid.py`, `static/chart.js`.
- Modify: `templates/destination.html`, `ptopilot/web/app.py`, `static/app.css`.
- Test: `tests/web/test_grid.py`, `tests/web/test_destination_v2.py`.

**Interfaces:**
- **Produces:**
  - **`DateGrid(weeks: list[date], lengths: list[int], cells: dict[tuple[date, int], GridCell])`** and **`GridCell(price: Decimal, level: str, dimmed: bool, option_key: str)`**.
  - **`date_grid(options: list[TripOption], band: tuple[int, int]) -> DateGrid`** in `grid.py`:
    - rows are the Monday of each departure week;
    - columns are days away within `band`, the target ± `TARGET_TOLERANCE_DAYS`;
    - each cell holds the cheapest option for that week and length, preferring non-dimmed ones;
    - `dimmed` when every option there is ruled out, snoozed or excluded;
    - open-jaw trips use the same axes;
    - at most 12 weeks shown, the earliest first.
- **Page:**
  - **Photo header:** name, the season rating for the shown month, and the target length.
  - **The interactive trend chart:**
    - the existing SVG gains `data-date`/`data-price` per point;
    - `chart.js` shows a tooltip on hover, focus or tap;
    - the typical band is shaded.
  - **The date grid** sits below the chart:
    - cells are coloured by level;
    - dimmed cells are hatched;
    - clicking a cell scrolls to that trip in the list and highlights it (`#trip-{option_key}` anchors work without JS).
  - **Trip rows** keep all of today's content. Snooze, exclude and book are in place (Task 1).
  - **The Related panel** becomes small photo cards (Task 5's `cover`).

- [ ] **Step 1: Write the failing tests.**
```python
def test_grid_rows_are_departure_weeks_and_columns_trip_lengths(): ...
def test_grid_cell_takes_the_cheapest_non_dimmed_option(): ...
def test_grid_cell_is_dimmed_when_every_option_is(): ...
def test_date_grid_with_no_trips_shows_an_empty_state(client, db): ...
def test_cells_link_to_their_trip_rows(client, db): ...
def test_chart_points_carry_date_and_price(client, db): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check of a destination with many trips and of one with none, at 1280 and 390 px. The grid must scroll horizontally inside its own box on phones, never the page.
- [ ] **Step 6: Commit and push** (`feat(web): a livelier destination page`).

---

### Task 8: Landing page

**Files:**
- Modify: `templates/landing.html`, `static/app.css`, `ptopilot/web/samples.py` (if the panels need more example data).
- Test: `tests/web/test_landing_v2.py`.

**Interfaces:**
- **Consumes:** `cover`, the hero and card components, and the planner calendar's markup (read-only example).
- **Page:**
  - **A full-width photo hero.** Use a built-in photo with its credit.
  - **The promise (exact):** "Your time off, your places, the right fare." The line under it (exact): "ptopilot watches flights for the trips you want, fits them to your PTO, and tells you when a fare is worth taking."
  - **A sign-in-by-email box**, using the existing `/login` POST.
  - **Three "how it works" panels**, each with a real component filled from `sample_cards` and labelled "Example":
    1. "Mark your free dates" (the calendar);
    2. "Get the deals that fit" (a deal card);
    3. "Know when to move" (a Rare tag with its duration line).
  - **A footer** with a Credits link.
  - **No testimonials, user counts or savings claims.**

- [ ] **Step 1: Write the failing tests.**
```python
def test_landing_has_the_promise_and_sign_in(client): ...
def test_landing_examples_are_labelled(client): ...  # three "Example" labels
def test_landing_makes_no_claims(client): ...        # no "users", "saved $", "testimonial"
def test_landing_links_credits(client): ...
```
- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff.
- [ ] **Step 5 (controller):** a browser check signed out at 1280 and 390 px.
- [ ] **Step 6: Commit and push** (`feat(web): a landing page that sells it`).

---

### Task 9: Roadmap and a live check

- [ ] **Step 1:**
  - In `ROADMAP.md`, move "Plan 15: site polish" to Done with a one-line description; "Hidden gems" becomes the first queued item.
  - Add the README's static-assets note: scripts are vanilla modules in `ptopilot/web/static/`, with no build step.
  - Commit and push (`docs: roadmap after site polish`).
- [ ] **Step 2 (controller):** after Render deploys, take a browser walk of the live site at 1280 and 390 px:
  - landing (signed out);
  - `/credits`;
  - for the owner's signed-in pages, ask the owner to sign in and look, since the controller can't receive their sign-in email.
  - Report screenshots (not committed) and anything off.
