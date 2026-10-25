# ptopilot — Year Plan and Your Own Destinations (Design)

**Date:** 2026-10-25
**Status:** Draft, awaiting review
**Builds on:** [V1 spec](2026-10-16-ptopilot-design.md), [V2 look and feel](2026-10-17-ptopilot-v2-look-and-feel-design.md), [V2 price data](2026-10-18-ptopilot-v2-price-data-design.md) · **Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) "Year-plan view"

This is the first of three V2 features, in the user's order. The other two get their own designs: a "buy now or wait" score that explains how attractive an offer is against its baseline across the criteria ptopilot already tracks, and related destinations.

---

## 1. Intent

**Why.** ptopilot judges each fare on its own. A traveler actually thinks in years: "I have 15 PTO days, a few places I want to see, and stretches of the year I can get away. What fits, and what's still left?" Setting this up today is clumsy:
- Travel windows are typed dates in a long form.
- Destinations are limited to seven places hard-coded in the app's data file.
- Booked trips are a single manual "already committed" number.

**What the user wants, in their words, condensed:**
- Start a new travel year on a **visual calendar with holidays already highlighted**. Like the Google Flights date picker, **drag across the ranges you're open to travel**.
- At the top, a **planner**:
  - list destinations, each with a rough number of **days away from home**;
  - below it, a bottom line of **total trips** and **total PTO**.
- That information drives what is tracked and what the email reports.
- A **year at a glance** view.
- A **suggested combination** of trips, flagged **only when every leg is fantastic**, a higher bar than an ordinary deal.
- An **"I booked this"** button that turns a trip into a realized plan and then re-checks fit warnings on the remaining deals.
- **Add or remove any destination from the website, at any time.** Adding Japan today should start tracking it for next year's ranges.

**Success looks like:**
- The user plans 2027 entirely on the website: open ranges, trips, booking. They never touch the profile form's window dates or a YAML file.
- Each email shows at a glance how much PTO is booked, planned and left.
- A combination appears only when it is genuinely exceptional on every leg.

---

## 2. Goals, non-goals, anti-goals

**Goals**
1. A **year planner page** with a full-year calendar:
   - holidays highlighted;
   - drag-to-open travel ranges;
   - a trip list (destination + days away);
   - a bottom line of trips, days away, and estimated PTO against available PTO.
2. **Destinations the user controls.** Search any place, add it, remove it, at any time. A new place starts being tracked on the next daily scan, for whatever open ranges exist.
3. **"I booked this."** It records a booked trip, removes that destination from monitoring, counts its real PTO, and re-checks fit on everything else.
4. **Fit warnings on deals:**
   - "overlaps a booked trip";
   - "doesn't fit your remaining PTO" (soft, informational only).
5. **Combinations:**
   - Offered on the website only when every leg is at least ~20% below typical **and** in a good season.
   - The legs mustn't overlap.
   - The whole combination must fit the remaining PTO.
6. **Email:** stays a short call to action built around individual deals, with a banner at the top: booked · planned · left PTO days.
7. **New year:**
   - tick which trips carry over;
   - open ranges reset;
   - a prompt to add destinations.

**Non-goals**
- Calendar export, multi-traveler trips, hotels, booking through ptopilot, paid data sources.
- Showing the year plan or combinations inside the email. The email is a call to action, and the logistics live on the website.

**Anti-goals: failure even if it technically works**
- Pitching a combination where any leg is merely good, or out of season.
- Stopping or weakening tracking of a trip because planned trips exceed PTO. That warning is soft: the user's PTO is flexible and they may drop other trips.
- Letting the email grow into a dashboard.

---

## 3. Decided behavior

### 3.1 Trips and days away
- A planned trip is a **destination** plus a **target number of days away from home**. Any length within **±2 days** of the target is acceptable: a target of 11 matches 9–13 days away.
- **One trip per destination per year** (the user's decision). A destination appears at most once in a year's trip list.
- A trip can land **anywhere in the open ranges**, wherever pricing is most competitive. Trips aren't assigned to a range.
- Targets differ per destination. Farther places justify longer trips (Japan longer than Bermuda).
- **Too-short targets (my call):** if a target's range falls below a destination's minimum trip length (from distance, §3.7), the planner warns ("Japan trips need at least 8 days away") and searches from that minimum instead.
- The target is also that trip's preferred length for the existing length bonus in selection and go-now (Plan 7), replacing the single per-user `ideal_trip_days` for trips that have a target.

### 3.2 Open ranges
- On the year calendar, the user drags across days to open them, and drags across open days to close them.
- **Saving (my call):** dragging edits the calendar on the page, and a "Save ranges" button submits them. That's the same form the no-JavaScript fallback uses, so both paths share one POST and the existing session and SameSite protections.
- Open ranges replace typed travel windows: they *are* the windows the daily scan searches.
- Holidays (from the user's calendar, minus ignored ones such as Columbus Day) and weekends are shown, so the user can see where PTO stretches furthest.

### 3.3 Bottom line
- Totals: number of trips, total days away, total estimated PTO, against the PTO available for that year.
- **PTO cost of any trip** = `WorkCalendar.pto_cost` (existing): workdays in the trip, where weekends, the user's holidays (minus ignored ones such as Columbus Day) and company days off are free. The existing Friday-evening rule applies when the user has it on.
- **Estimated PTO for an unbooked trip** = the fewest PTO days any trip in its length range costs inside the open ranges (the best case), since real dates come from prices. Use the existing trip-shape generation over the open ranges.
- **A booked trip** counts its actual PTO.
- When planned trips exceed available PTO, the affected trips show a soft note ("Won't fit: N PTO left after the others"). They stay tracked with full rigor.

### 3.4 "I booked this"
- Available on a trip row of the destination page (prefilled with that trip's dates and price) and as a manual entry for a trip booked elsewhere.
- Records the booked trip: destination, dates, price, PTO cost computed from the calendar.
- Removes the destination from monitoring (the tracker is deactivated, as removing a destination does today). It shows as booked on the planner and the calendar.
- Remaining PTO = available − booked PTO − other committed time off. The existing "already committed" number becomes "other time off (not trips)".
- Every remaining deal is then re-checked for fit (§3.6).
- **Cancelling a booking (my call):** a booked trip can be cancelled from the planner. Its destination returns to "watching" with the same target, and tracking resumes.

### 3.5 Combinations
- Built from current offers (today's candidates) for the planned, unbooked trips.
- "~20% below typical" uses the existing `pct_below` against the existing baseline median. "Good season" uses the existing season rating for the trip's month (`trip_month`: the month holding most of the trip's days).
- Shown on the website only, when:
  - **every leg** is at least ~20% below its typical price, on a `normal`-confidence baseline;
  - **every leg** falls in a **good** season (shoulder is not enough);
  - **no two legs overlap**, and none overlaps a booked trip;
  - the **total PTO fits** the remaining PTO.
- A single fantastic trip is just a great deal: a combination needs at least two legs.

### 3.6 Fit warnings
On deal cards (dashboard, destination page) and in the email, two soft, informational notes:
- "Overlaps your booked {destination} trip."
- "Doesn't fit your remaining PTO ({n} left)."

### 3.7 Destinations the user controls
- **Search** by place name or airport code ("Japan", "Tokyo", "Bermuda", "BDA"). Results are cities with their airports (e.g. "Tokyo: HND, NRT").
- The user picks one and sets its target days away. The next morning's scan starts tracking it in any open ranges. If there are none (Japan "for next year"), it waits.
- **Removing** stops tracking and alerts. Price history is kept in case the place is added back.
- **Airport data:** the public-domain OurAirports dataset, bundled with the app and filtered to airports with scheduled service. No API or key.
- **Seasons for new places:**
  - When a place is added, look up its monthly climate normals once from the free Open-Meteo service.
  - Rate each month good / shoulder / avoid from temperature and rain, honoring the user's "nothing too cold" tolerance.
  - Hand-written ratings in `seasons.yaml` stay and take precedence.
- **Travel time for new places:**
  - Travel overhead and minimum trip length come from the great-circle distance between the home airport and the destination, so Japan counts more travel days than Bermuda.
  - The hand-written zone-pair rules in `geo.yaml` still apply where they exist.
- **Color:** new places get their zone's default color (Plan 7 §3.2).
- **Baselines for new places:** Plan 8's `seed_history` seeds a new place's round-trip baseline keys automatically on the next scans. Until a key is `normal`, the place can produce ordinary deals but never a combination leg. Its card says "Building price history" while all its keys are low-confidence.
- **Distance per origin (my call):** with several home airports (JFK, EWR, PHL), overhead is computed per origin airport, as zone rules are today.
- **Season ratings are neutral (my call):** ratings are stored as good / shoulder / avoid. Each user's weather tolerance is applied when filtering, as today, so a change of tolerance needs no recomputation.

### 3.8 New year
- "Start planning {year}":
  - lists last year's unbooked trips with checkboxes to carry over;
  - starts the new year with no open ranges;
  - asks for that year's PTO total;
  - prompts the user to add destinations.
- Booked trips belong to the year they happen in.
- **Year boundaries (my call):** a trip, booked or offered, belongs to the planning year of its departure date. A range that crosses Dec 31 belongs to the year it starts in. The email banner uses the planning year of the deals shown, or the earliest one when deals span two years.

### 3.9 Email
- Unchanged apart from the banner.
- **Banner:** "{booked} booked · {planned} planned · {left} PTO left" for the year of the deals shown (or the current planning year).
  - "Planned" means the estimated PTO of unbooked planned trips.
  - The deal cards keep the fit notes from §3.6.

---

## 4. Constraints

- **Stack:** Python, FastAPI, server-rendered Jinja, Postgres on Neon, and the GitHub Actions daily pipeline.
- **Cost:** free services only.
- **Look:** the existing design system (Plan 7).
- **Access:** every new page and action is scoped to the signed-in user, as today.
- **Process:** every step is committed and pushed to `main`. Migrations reach Neon before code that reads them deploys (Render auto-deploys `main`).
- **JavaScript (my call):**
  - Drag-to-select needs JavaScript, which will be the site's first.
  - Use small, plain JavaScript in one static file: no framework, no build step.
  - The calendar must still work without JavaScript (range date fields as a fallback).
- **Secrets:** never committed or printed.
- **Existing travelers keep working:**
  - Their current windows become 2027's open ranges.
  - Their trackers become planned trips. The target is set to the midpoint of their current days-away range (stay range plus travel overhead), rounded to the nearest day.
  - Their `pto_days_total` becomes 2027's PTO.
  - Their `pto_committed` becomes "other time off".
- **Profile YAML:** `profiles load` keeps working for existing fields.

---

## 5. Left to the builder

- Data model and migration details:
  - a planning year with its PTO;
  - booked trips;
  - a destinations table seeded from `geo.yaml`;
  - stored season ratings for added places;
  - per-trip target days.
- The combination search algorithm, and how many combinations to show (a few at most).
- Distance bands for travel overhead and minimum trip length.
- Climate thresholds for good / shoulder / avoid, kept in `config.py`.
- The airport dataset filter, and how cities group airports.
- Page layouts within the design system. The visual companion sketch (`.superpowers/brainstorm/…/year-planner.html`) is a starting point, not a spec.
- Whether the profile form keeps its window fields (hidden, read-only, or removed) once the planner exists.
- How the work is split into plans. A reasonable split: (1) destinations you control; (2) planning year, planner page and calendar; (3) booking, fit warnings, combinations and the email banner.
