# ptopilot — V2 "Look and Feel" Design Spec

**Date:** 2026-10-17
**Status:** Draft, awaiting review
**Builds on:** [V1 spec](2026-10-16-ptopilot-design.md) · **Backlog:** [`ROADMAP.md`](../../../ROADMAP.md)
**Mockups:** chosen in the brainstorming visual companion (`.superpowers/brainstorm/`, git-ignored)

---

## 1. Purpose and success criteria

**Problem.** V1 works end to end, but the web app and digest are bare HTML. The author wants form *and* function: clean landing pages, consistent stylistic choices, professional quality, an easy flow, and an inviting, information-dense design. V1 also ignores the user's preferred trip length, and price history is collected but never shown.

**This release delivers:**
1. A design system (palette, destination colors, type, shared components) used by every page and the email.
2. A public landing page, a redesigned dashboard, and a new destination detail page with a price-history chart.
3. A redesigned digest email.
4. A preferred-trip-length preference that influences both which trips are priced and how they score.

**Successful when:**
1. Every web page is built from the shared stylesheet and components, with no page-specific ad-hoc styling.
2. Pages render without horizontal scroll at 375px and look deliberate at 1280px (checked by screenshots).
3. The digest renders correctly in Gmail (web and mobile) and is readable in Outlook.
4. A user with `ideal_trip_days` set sees near-ideal trips priced and ranked higher, while other lengths still appear.
5. No new paid services; hosting cost stays $0/month.

**Non-goals:** year-plan view, buy now or wait, related destinations, a verified Resend domain, data-quality work, JavaScript frameworks, dark mode.

---

## 2. Decisions from brainstorming

| Question | Choice |
|---|---|
| Visual direction | **B · Travel editorial**: warm cream background, a colored header per destination, serif names, a "where this price sits" bar (typical band plus a dot) instead of a dense chart. |
| Dashboard | **A · Destination grid**: PTO bar on top, one card per tracker showing its best current trip. |
| Destination page | **A · Trip table + one trend line**: every date option in a table, plus one "cheapest fare, last 30 days" chart. |
| Landing page | **A · Product hero**: headline, value line and sign-in on the left; two sample deal cards on the right; then "how it works" in 3 steps. |
| Digest email | **C · Lead deal + list**: the top deal as a full card, the rest as compact rows. |
| Type | **B · Fraunces + Inter** (web); Georgia + system sans in email. |
| Trip-length preference | Counts in **both** selection and the go-now score. |

---

## 3. Design system

### 3.1 Tokens

Defined once as CSS custom properties in `ptopilot/web/static/app.css`:

| Token | Value | Use |
|---|---|---|
| `--bg` | `#fbf7f0` | page background (warm cream) |
| `--surface` | `#ffffff` | cards, tables, form panels |
| `--ink` | `#1f2937` | body text |
| `--muted` | `#6b7280` | secondary text |
| `--line` | `#f3f4f6` | table rules, dividers |
| `--track` | `#e5e7eb` | empty bar track |
| `--btn` | `#111827` | primary buttons |
| `--danger` | `#b91c1c` | form errors |
| `--radius` | `12px` (cards), `8px` (buttons, inputs) | |
| `--shadow` | `0 1px 3px rgba(0,0,0,.08)` | cards |

Fonts come from Google Fonts with `display=swap`: **Fraunces** (opsz, weights 400/600) for destination names, page titles and the logo; **Inter** (400/600/700) for everything else. Fallbacks are `Georgia, serif` and `system-ui, -apple-system, "Segoe UI", sans-serif`. Prices use `font-variant-numeric: tabular-nums`.

### 3.2 Destination colors

- `geo.yaml` destinations gain an optional `color` (hex). Seeded values: Azores `#0e7490`, Madeira `#15803d`, Patagonia `#7c2d12`, Camino Portugués `#a16207`, Lisbon `#1d4ed8`, Tokyo `#be123c`, Thailand `#047857`.
- A destination without `color` uses its zone default (from its first airport's zone): `EUROPE #0e7490`, `S_AMERICA #7c2d12`, `SE_ASIA #047857`, `E_ASIA #be123c`, `NA #1d4ed8`, anything else `#374151`.
- Each color has a derived light **tint** for the typical band (the color mixed with white, 25% color / 75% white). It is computed in Python so the email can use it too.
- `ptopilot/core/geo.py` exposes `destination_color(code) -> Palette(color, tint)`. The geo loader rejects a `color` that isn't a 6-digit hex.

### 3.3 Components

Jinja macros in `ptopilot/web/templates/_components.html`. Every page composes these:

- `price_bar(position, band_start, band_end, palette)`: the "where this price sits" bar. Positions are 0–100 percentages computed in Python by `ptopilot/web/viz.py::bar_geometry(price, median, sigma)`. The bar spans median ± 3σ; the band is median ± σ; positions are clamped to 2–98 so the dot never leaves the track. With no baseline, the bar is omitted.
- `dest_card(card)`: colored header (eyebrow plus Fraunces name), price, % vs typical, price bar, then a meta line (dates · PTO · days · season note). Links to the destination page.
- `pto_bar(left, committed, total)`: segmented bar with "N PTO days left" and "M committed".
- `trip_row(option)`: one row of the destination table.
- `button(label, kind="primary"|"ghost")` and form `field(...)` with an inline error slot.

### 3.4 Layout

- Mobile first. The content column is `max-width: 1040px`, with a 16px side gutter (24px from 768px up).
- Nav: the Fraunces "ptopilot" logo on the left. Signed in: Dashboard · Profile · Sign out (POST form). Signed out: Sign in (ghost button).
- The dashboard grid is 1 column below 640px and 2 columns from 640px. The detail table collapses each row into a two-line stacked layout below 640px.
- No JavaScript is required for any page.

---

## 4. Pages

### 4.1 Landing (`GET /`, signed out)

- Hero, two columns from 768px (stacked below):
  - **Left:** a Fraunces headline ("Your PTO, spent on the right trips at the right price."), one line of value copy, then the sign-in form (email field + "Send sign-in link"). This replaces the separate `/login` form, and `GET /login` redirects to `/`.
  - **Right:** two sample `dest_card`s built from **fixed illustrative data** in the template (never real users' trips), labelled "Example".
- "How it works", 3 steps: Your PTO and windows → A daily fare watch → Deals, twice a week.
- A footer line: "Invite-only for now."
- Behavior is unchanged: invite-only, the same 120s cooldown, the same "check your email" result (now a styled `login_sent.html`).

### 4.2 Dashboard (`GET /`, signed in)

- A `pto_bar` with the user's PTO total, committed days and days left.
- One `dest_card` per tracker, cheapest current deal first, then trackers without a priced trip.
  - The best trip comes from the same data as V1 (`build_digests(user_id=…, skip_sent=False)`).
  - Season note: the trip month's season rating ("Good season" / "Shoulder season"), followed by that month's `notes` text from `seasons.yaml` when there is one (e.g. "Mild but rainy, ~15°C"). Without a rating there's no note.
- Snoozed trackers: the card is dimmed and shows "Snoozed until …" with an Unsnooze button (existing POST).
- No scan yet, or no priced trip: the card shows "First prices after the next daily scan".
- Each card links to `/trackers/{id}`.

### 4.3 Destination detail (`GET /trackers/{id}`, new)

- **Hero:** destination color gradient, eyebrow ("Atlantic islands · 7–10 days on the ground"), Fraunces name.
- **Trip table:** every candidate for this tracker on the latest run date (the latest run date ≤ today, as in the digest).
  - Columns: dates, price, vs-typical bar, PTO cost, days away, airline · stops (· "overnight" when there's an overnight layover), and "View flights" (the observation's deep link, or the Google Flights link from `ptopilot/links.py`).
  - Sorted by price ascending.
  - Rows whose candidate state is `snoozed` or `excluded` are dimmed, not hidden.
  - Open-jaw trips show "into OPO · home from SCQ".
- **Trend chart:** "Cheapest fare, last 30 days" (§5.2), drawn as inline SVG by `ptopilot/web/viz.py::trend_svg(points, band)`. It's a 0–100 viewBox polyline with the typical band as a shaded rect and the latest point as a dot; y-axis labels show the min and max price; x-axis labels show the first and last date. Fewer than 3 points: the panel reads "Price history fills in after a few daily scans."
- **Actions:** the tracker's snooze / unsnooze buttons.
- **Access:** sign-in required (otherwise redirect to `/`). A tracker belonging to another user, or one that doesn't exist, returns **404**.

### 4.4 Profile, messages, confirm

- `profile.html` is restyled into grouped panels: Home & calendar, PTO & trip length, Travel windows, Destinations.
  - It gains an **Ideal trip length (days)** field, which is optional.
  - Validation errors re-render the form with inline messages and status 400, instead of a raw 422 page.
- `message.html`, `login_sent.html` and `action_confirm.html` use a single centered panel with the same components.

---

## 5. Data and scoring

### 5.1 Preferred trip length

- **Storage:** migration `0005` adds a nullable `users.ideal_trip_days SMALLINT`, with check constraint `ideal_trip_days IS NULL OR (min_trip_days <= ideal_trip_days AND ideal_trip_days <= max_trip_days)`.
- **Input:**
  - Profile YAML key `ideal_trip_days` (optional int), validated by the loader against min/max with a clear error.
  - The profile form field accepts blank (stored as NULL) or an int within range.
- **Fit:** `ptopilot/core/scoring.py::length_fit(days_away, ideal) -> float` is `max(0, 1 − |days_away − ideal| / LENGTH_FIT_SPAN)`, with `LENGTH_FIT_SPAN = 4`. If `ideal` is None, it returns 1.0.
- **Selection:**
  - `TravelerProfile` gains `ideal_trip_days: int | None = None`.
  - `select_top` gains `ideal_days: int | None = None` and ranks by `efficiency × (1 + LENGTH_SELECTION_BONUS × fit)` with `LENGTH_SELECTION_BONUS = 0.25`. The existing tie-breaks follow.
  - The diversity caps (per length, per week, per date pair) are unchanged.
  - With `ideal_days=None`, the ranking is identical to V1.
- **Go-now:** `go_now(...)` gains `length_fit: float`.
  - `GO_NOW_WEIGHTS = {"deal": 0.5, "weather": 0.2, "efficiency": 0.15, "length": 0.1, "timing": 0.05}`, which still sums to 1.
  - `pipeline/score.py` passes `length_fit(route_query.days_away, user.ideal_trip_days)`.
  - Existing candidates keep their stored scores; new runs use the new weights.
- All new constants live in `config.py`.

### 5.2 Price history

- **Trend:** `ptopilot/web/history.py::trend(engine, tracker_id, today) -> list[TrendPoint(run_date, price)]`.
  - Points are the minimum candidate price per run date for that tracker, over run dates in `(today − 30 days, today]`, ascending.
  - Run dates with no candidates produce no point, so the chart shows a gap. The SVG uses separate polyline segments for runs of consecutive dates.
- **Band:** median ± σ of the `route_baselines` row for the route, month and length bucket of today's cheapest candidate. None if there's no such row.
- **Detail rows:** `history.trip_options(engine, tracker_id, today) -> list[TripOption]`.
  - Each row is a candidate on the latest run date, joined to its route query (dates, PTO, days away, airports) and price observation (carrier, stops, overnight, deep link), and to its baseline for bar geometry.
  - Sorted by price, then depart date.
- **No new tables.** The candidates table already holds one row per trip per run.

---

## 6. Digest email

`digest.html.j2` is rebuilt (`digest.txt.j2` is updated to match):

- **Structure:** a 600px centered table inside an Outlook `<!--[if mso]>` fixed-width wrapper. All styles are inline. Headings use Georgia and body text uses the system sans stack. There's no SVG, no web fonts and no background images.
- **Preheader:** a hidden first line, e.g. "Azores $578 (12% below typical) + 2 more".
- **Header:** "ptopilot" in Georgia, then "Monday, Oct 19 · 3 trips worth a look".
- **Lead deal:** the highest go-now deal.
  - A full card: header cell in the destination color with "Best this week" and the name plus dates; the price and % below typical; then the price bar built from a 5-cell table row (track, dot, track, band in the tint, track) using the same `bar_geometry`.
  - Then the trip facts (PTO for days · airline · stops · season note) and the links: **View flights** (button), Not this trip, Snooze 30d (existing action-token links, shown only when `APP_BASE_URL` is set).
- **Other deals:** compact rows, each with a 4px color stripe cell, the Georgia name, dates · PTO, the price, and the % below typical in the destination color.
  - Each row links to `/trackers/{id}` when `APP_BASE_URL` is set, and to the flights link otherwise.
  - The order is go-now descending.
- **Quiet digest (Mondays only, as in V1):** a single friendly card.
  - If deals exist but were all sent before: "No new deals since Thursday — your earlier ones are still on the dashboard."
  - Otherwise: "Nothing below typical yet."
  - Either way, it lists the next good month per tracker as in V1.
- **Footer:** Manage trips (dashboard link, when configured) · "Why am I getting this?" (one line explaining the invite).
- Selection, resend rules, tuning sends and email-address scrubbing are **unchanged**.

---

## 7. Testing

- **Core:**
  - `length_fit`: ideal, ±1, ±4 and None.
  - `select_top`: with an ideal, near-ideal lengths come first; the per-length and per-week caps still hold; `ideal_days=None` gives V1 order.
  - `go_now`: weights sum to 1, and the length component moves the score as expected.
  - `destination_color`: explicit color, zone fallback, invalid hex rejected.
- **Profiles and forms:** `ideal_trip_days` is optional, rejected outside min..max in both the YAML loader and the form, and blank is stored as NULL. Migration 0005 upgrades and downgrades cleanly.
- **History:** `trend` gives one point per run date, uses the minimum per date, respects the 30-day limit, ignores other trackers, and returns empty when there's no data. `trip_options` follows the sort order, includes dimmed states and labels open-jaw trips.
- **Viz:** `bar_geometry` handles clamping, no baseline, and a zero sigma floor. `trend_svg` handles gaps, fewer than 3 points (empty state) and a missing band.
- **Web (TestClient):**
  - Signed out, `/` shows the landing page with the sign-in form, and `/login` redirects.
  - Signed in, `/` shows the dashboard with the PTO bar and cards.
  - `/trackers/{own}` returns 200; another user's tracker and a missing id both return 404; signed out redirects.
  - `/static/app.css` is served.
  - A profile validation error returns 400 with an inline message.
- **Digest:** lead card plus rows, the preheader present, the Outlook wrapper present, row links to `/trackers/{id}` only when configured, both quiet variants, and the text version's order.
- **Visual QA (manual, before finishing):** Playwright screenshots of the landing page, dashboard, destination page, profile and a rendered digest at 1280px and 375px, reviewed for overflow and consistency.

---

## 8. Rollout

- Commit and push to `main` at each step. Render auto-deploys on every push.
- Migration 0005 is applied to Neon (`alembic upgrade head` with the direct URL) **before** pushing the commit that adds `ideal_trip_days` to the model, so the deployed app never reads a missing column. The column is nullable, so V1 code keeps working against the migrated database in the meantime.
- Set `ideal_trip_days: 10` in the author's git-ignored profile and reload it.
- ROADMAP: tick open-jaw; add "Web app visual polish" and "Preferred trip length" as done in V2.
