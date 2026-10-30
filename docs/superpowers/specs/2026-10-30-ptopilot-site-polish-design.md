# ptopilot — Site Polish (Design)

**Date:** 2026-10-30
**Status:** Approved 2026-10-30
**Builds on:**
- [V2 look and feel](2026-10-17-ptopilot-v2-look-and-feel-design.md) (Plan 7: the design system);
- Plans 9–14 (destinations, planner, booking, misery, buy now or wait, related destinations).

**Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) §1 "Plan 15: site polish"; hidden gems follows as its own design.

---

## 1. Intent

**Why.** ptopilot works, but the site reads as "a high school CS project":
- comma-separated airport codes;
- plain number boxes and drop-downs;
- pages that load and sit there.

Before friends see it, the owner wants it to feel like a professional travel product. It should be "the kernel of a potentially marketable tool", and it should amaze friends.

**What the owner wants, in their words, condensed:**
- **The bar:** the calm, data-first polish of **Google Flights** (it "sleekly captures the important data") and the **Capital One Travel** portal. Professional, dynamic, intriguing; "the first website I want to go to when I'm daydreaming about how to spend my time off", tailored to their availability and interests.
- **Onboarding** is engaging, guided and intuitive: one step at a time, never overwhelming.
- **Editing later** isn't laborious.
- **Inputs work like Google Flights' airport picker:**
  - type, pick from an auto-populating dropdown, press Enter;
  - each item "saves" as its own visible object in the list.
  - "That same sort of flow is extensible to each of the data fields."
  - "Intuitive, approachable, and slick without being overengineered."
- **The planner calendar is the benchmark:** "user-friendly, kind of fun". Keep it.
- **The deal that brought you here** sits in a highlighted card at the top of the dashboard, with a countdown when time matters. A pop-up is acceptable when there is real time pressure.
- **Cover photos** on destination cards.

**Mockups the owner approved** (brainstorm session, 2026-10-30):
- **`inputs.html`:** airport chips with a type-ahead dropdown (city or code, nearest first); three plain-language weather choices; one trip-length slider with a ★ for the ideal length; a 4-step progress bar for new users.
- **`dashboard.html`:**
  - a hero card for the day's best deal, with photo background, "Rare · likely gone within ~2 days" pill, price and % below typical, route, dates, PTO cost, a sparkline, "View flights" and "I booked this", and a countdown chip;
  - photo cards for the other destinations below;
  - a "Hidden gems" teaser, which is out of scope here (§2).

**Success looks like:**
- A friend opens the link, is set up in a few minutes without typing an airport code, and lands on a dashboard that looks like a real travel product.
- Changing an airport, the trip length or the PTO takes one or two interactions, with no full-form resubmit.
- Nothing the owner relies on today breaks: the planner, booking, snooze, related places, email links.

---

## 2. Goals, non-goals, anti-goals

**Goals**
1. **Guided onboarding** for a user without a profile (§3.2).
2. **One input pattern everywhere** (§3.3):
   - chips with type-ahead for lists;
   - segmented plain-language choices for enums;
   - sliders or steppers for numbers;
   - tap-on-calendar for dates;
   - edits save in place.
3. **Dashboard:** the hero card and photo cards (§3.4).
4. **Destination page:** more alive (§3.5).
5. **Cover photos** for every destination, built-in and added (§3.6).
6. **Small actions without page reloads:** snooze, accept or dismiss related, add or remove a destination, plan or unplan, profile edits.
7. **A landing page** that sells the product to a friend seeing it for the first time (§3.7).
8. **Works well on a phone.**

**Non-goals**
- Hidden gems (the next design).
- Changing the email digest or alert emails.
- New data, scoring or pipeline behaviour.
- Accounts, payments, or multi-user features beyond what exists.
- Rebuilding the site as a single-page app.

**Anti-goals**
- **Overengineering:** a heavy front-end framework, a build step, or a dependency the site doesn't need. "Slick without being overengineered" is the owner's line.
- **Gimmicks that fight Google Flights' calm:** autoplaying motion, confetti, a loud hero on a quiet day, or a pop-up that nags.
- **Losing functionality or speed:** a page that is slower or harder to use than today's.
- **Breaking existing links**: digest snooze links, `/trackers/{id}`, `/plan/{year}`.

---

## 3. Decided behaviour

### 3.1 How it's built (my calls)
- **Stack:**
  - keep server-rendered Jinja pages, the existing design tokens (Fraunces + Inter, destination colours) and `app.css`;
  - add small hand-written vanilla JS modules in `static/`, as `planner.js` is today.
  - No framework, no bundler, no npm build.
- **Progressive enhancement:**
  - every form still works as a plain HTML POST without JS;
  - with JS, small actions use `fetch` and update the page in place.
  - JSON endpoints sit next to the existing routes and return 4xx with a message the UI shows.
- **Look:**
  - tighten the existing system toward Google Flights: more white space, clear hierarchy, consistent cards, subtle shadows, a 150–200 ms ease on state changes;
  - `prefers-reduced-motion` respected.

### 3.2 Onboarding (my calls on the steps)
A signed-in user with no completed profile goes to `/welcome`, a 4-step flow with a progress bar, Back and Next. Each step saves when you press Next, so leaving halfway keeps what's done.

1. **Where do you fly from:** airport chips. The home airport is the first chip; suggestions are the nearest airports to it.
2. **Your time off:**
   - PTO days per year;
   - holiday calendar, picked by country with the calendar's holidays listed;
   - company days off, tapped on a small calendar.
3. **How you like to travel:**
   - the trip-length slider with the ideal ★;
   - weather choice;
   - stops and overnight layovers as plain toggles;
   - the leave-after-work option.
4. **Where you'd love to go:**
   - destination search with photos and type-ahead;
   - add 1–5 places, each a card with a target-length stepper;
   - "Start planning" creates the current planning year and lands on `/plan/{year}`, the calendar the owner likes, to mark open dates.

- **Copy:** friendly and short, one sentence of why per step. My call; wording is left to the builder within that tone.
- **Existing users** never see `/welcome` unless they open it.
- **Completion state (my call):** a new `users.onboarded_at` timestamp, nullable.
  - The migration backfills every existing user to the migration time, so no current user is ever pushed into onboarding.
  - **Step 1 creates the user row:** the first airport chip becomes the home airport, and every other field takes today's defaults.
  - Each later step saves only its own fields, validated with the existing rules for those fields.
  - **The finish:** step 4's "Start planning", or a "Skip for now" link on any step after 1, sets `onboarded_at`. "Start planning" then creates the planning year exactly as `/plan/new` does today, reusing the same code.
  - **Redirects:**
    - a signed-in email with no user row, or a user with `onboarded_at` null, goes to `/welcome` from `/` and `/profile`;
    - everyone else is unaffected.

### 3.3 The input pattern
- **Airports:**
  - type-ahead over the existing airport catalog, matching city, code or name;
  - a dropdown of up to 6, large and medium airports first, nearest to the home airport when one exists;
  - Enter or click adds a chip "PHL · Philadelphia" with ×;
  - duplicates refused gently;
  - keyboard: ↑ ↓ Enter Esc Backspace.
- **Enums** (weather, stops): segmented cards with a one-line plain description each.
- **Numbers:**
  - trip length is one dual-handle slider plus ★;
  - PTO days and target days use steppers (− value +).
  - Bounds are the existing validation limits.
- **Dates:**
  - company days off and other dates use the planner's tap-calendar component, reused rather than copied;
  - holidays the office works are chips picked from that calendar's holiday list.
- **Field mapping (my calls): every control writes the existing columns and values.** Nothing about stored meaning or scoring changes.
  - **Weather** (`weather_tolerance`):
    - "Only the best months" = `strict`;
    - "Shoulder season is fine" = `normal`;
    - "Any time if it's cheap" = `relaxed`.
  - **Stops:** two small segmented controls keep both columns.
    - "Shorter flights": Nonstop only / Up to 1 stop / Up to 2 stops, writing `max_stops_short` 0 / 1 / 2.
    - "Long-haul": Up to 1 stop / Up to 2 stops, writing `max_stops_long` 1 / 2.
  - **Overnight layovers** and **leave after work** stay on/off switches for their boolean columns. The leave-after-work time appears only when that switch is on.
  - **Trip length:**
    - the two slider handles write `min_trip_days` and `max_trip_days`;
    - the ★ is optional: a "No preference" chip clears `ideal_trip_days` to null, and dragging the ★ sets it;
    - the ★ is kept between the handles.
- **Saving:**
  - on the profile page, each section saves on change, with a quiet "Saved" tick;
  - errors are shown inline next to the field.
  - Without JS, one Save button as today.

### 3.4 Dashboard
- **Hero card:**
  - It shows the user's single best deal today: a standout first, else the best "great" deal, else nothing.
  - Contents, as in the mockup:
    - the destination's cover photo, darkened for legibility;
    - a pill with the duration or Rare label;
    - destination and month;
    - price and % below typical;
    - origin → arrival airport, dates, days away and PTO;
    - stops;
    - a 30-day sparkline;
    - "View flights", "I booked this" and Snooze.
  - **Countdown chip:** "~N days" before it's likely gone, only when expected_days ≤ 7.
- **Quiet day:**
  - no hero;
  - a calm one-line status ("No standout fares today · checked 38 trips at 06:12");
  - and the photo cards.
- **Arrival pop-up:**
  - only for a standout;
  - once per deal per browser, remembered in localStorage;
  - dismissible with Esc or a click outside;
  - never on a phone's first paint over the content: a slide-up sheet instead.
- **Photo cards:**
  - one per destination: cover photo, name, best price and level, dates and PTO, a tiny trend arrow;
  - snoozed or booked state shown as a quiet badge;
  - the whole card links to the destination page.
- **The PTO banner** (booked / planned / left) stays, restyled as a slim bar.
- **Data:** all of this exists today.
  - `Candidate.expected_days` and `duration_thin` drive the pill and countdown.
  - The 30-day trend per tracker (`web/history.trend`) drives the sparkline. Loading it for the hero and up to a dozen cards is a read of existing data, not new data.
  - The builder may batch the trend reads.

### 3.5 Destination page
- **A photo header** with the name, season for the chosen month, and target length.
- **Interactive 30-day price chart:**
  - hover or tap shows the date and price;
  - the typical band is shaded.
- **A date grid**, Google Flights' "date grid" idea in our terms:
  - rows are depart weeks, columns are trip lengths within the target band;
  - each cell shows today's best price, coloured by deal level;
  - greyed cells are ruled out, snoozed or excluded;
  - clicking a cell selects that trip in the list below.
- **The trip list** keeps today's rows: duration line, Rare tag, misery notes, fit notes, booking. Snooze, exclude and book act in place.
- **The Related panel and related suggestions** restyled as small photo cards.

### 3.6 Cover photos (my call on the source)
- **Source:** Wikimedia Commons, through the Wikipedia page image of the destination's city or region:
  - free licences, no API key;
  - fetched once per place and stored with its attribution (author, licence, source URL).
- **Built-ins:** hand-picked images, listed in `geo.yaml` with attribution.
- **Fallback:** the destination-colour gradient used today.
- **Attribution** shows in a small "Photo: …" credit on hover or tap, and on a credits page.
- **Storage:** an image URL plus attribution per place. The site links to Wikimedia's thumbnail CDN rather than hosting files (my call). A failed load falls back to the gradient.
- **Where it's stored and when it's fetched (my calls):**
  - **A new `place_photos` table** keyed by place code: `image_url`, `width`, `height`, `author`, `licence`, `source_url`, `fetched_at`, and `status` (`ok` or `none`). Built-ins are seeded from `geo.yaml` into the same lookup.
  - **Fetched outside web requests:** a small `photos` step in the daily scan fills places that have no row, so adding a place never waits on Wikipedia. Until then the card shows the gradient.
  - **Lookup:** the Wikipedia REST page summary for the place's city or region name, plus the country to disambiguate.
    - Only a JPEG lead image of at least 800 px wide is accepted; SVG maps and flags are rejected.
    - No acceptable image → `status none`, and the gradient stays. The place is retried after 30 days.
  - **Attribution** comes from the Commons file's metadata (artist, licence short name, file page).
  - **Requests to Wikimedia** send a descriptive User-Agent, as their API policy asks.
  - **Hotlinking** Wikimedia's thumbnail CDN with attribution is acceptable for this project's scale (my call). Switching to stored copies later is a change to the image URL only.

### 3.7 Landing page
- **For a signed-out visitor:**
  - a full-width photo hero with the one-line promise;
  - a sign-in-by-email box;
  - three short "how it works" panels showing real UI (the calendar, a deal card, the Rare tag);
  - a footer.
- **No made-up testimonials or stats.**
- **The panels show the real components** (calendar, deal card, Rare tag), filled with the existing `sample_cards` fixtures and labelled "Example" (my call). Example trips are fine; invented claims about users or savings are not.
- **Auth (my call):** `/welcome` and the new JSON endpoints, including the airport and destination type-ahead, are signed-in only. The landing page's sign-in box is the only signed-out form.

---

## 4. Constraints

- **Stack:** Python, FastAPI, Jinja, Postgres on Neon, Render free tier.
  - No new paid services.
  - No front-end build step; scripts stay small, readable vanilla JS.
  - External script and CSS CDNs only if clearly needed. My call: none planned; fonts already load.
- **Performance:**
  - pages render server-side and stay fast on Render's free tier;
  - photos are lazy-loaded thumbnails sized for their slot;
  - the type-ahead endpoint answers from the in-memory catalog.
- **Accessibility:**
  - keyboard operable;
  - visible focus;
  - labels and ARIA for chips, sliders and the dialog;
  - colour is never the only signal;
  - reduced motion respected.
- **Compatibility:** current Chrome, Safari (incl. iOS) and Firefox.
- **Tests:**
  - the existing suite stays green;
  - new JSON endpoints and server-rendered states are tested;
  - JS is checked by hand in a real browser (Playwright is available to the builder for screenshots), as the calendar was.
- **Process:**
  - migrations reach Neon before code that reads them deploys;
  - commit and push to `main`;
  - never print or commit secrets.
  - The repo is public: no personal data in fixtures or screenshots committed.

---

## 5. Left to the builder

- Exact visual details within §3: spacing, type scale, shadows, motion timings, icons (inline SVG).
- The `/welcome` step copy, within the tone in §3.2.
- How the in-place saves map to endpoints, and how the server-rendered page and JS share one source of truth for each component.
- The date grid's exact shape for open-jaw and very long target bands.
- Which hand-picked photos to use for the built-in places, under free licences with attribution.
- How the work splits into tasks. Probably in this order: design-system tightening, input components, onboarding, dashboard, destination page, photos, landing.
