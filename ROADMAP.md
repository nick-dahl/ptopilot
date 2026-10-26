# ptopilot Roadmap

V1 scope and design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md). V1 and Plans 7–10 are live. This page is the agenda: what's queued, what to settle before inviting friends, feature ideas, and the polish backlog from code reviews.

## 1. Queued work, in order

- [ ] **Plan 11: booking, fit warnings, combinations, email banner.** In progress. Plan: `docs/superpowers/plans/2026-10-25-ptopilot-plan-11-booking-and-fit.md`. It finishes the year-plan view below.
- [ ] **Plan 12: buy now or wait.** Written and approved: `docs/superpowers/plans/2026-10-25-ptopilot-plan-12-buy-now-or-wait.md`. It covers:
  - a stricter go-now score;
  - "likely gone within ~N days";
  - standout deals;
  - instant alerts (at most one a day, the same destination at most once a week).
- [ ] **Plan 13: related destinations.** The design is approved (`docs/superpowers/specs/2026-10-25-ptopilot-related-destinations-design.md`); the plan is still to write. It covers:
  - nearby airports within 160 km;
  - curated groups of major tourist destinations;
  - at most 5 suggestions per destination;
  - an "Also worth a look" section.

## 2. Before inviting friends

- [ ] **Verify a Resend sending domain.** Until then, email reaches only the owner.
- [ ] **Signed-in check of the live planner** (`/plan`). Only signed-out checks have run on production.
- [ ] **One person's digest failure stops the others.** Only email failures are isolated today. A database hiccup right after sending could also cause one repeat send.
- [ ] **A rule for deleting old price data.** Price observations grow without limit.
- [ ] **Harden the scan workflow:**
  - its manual-run inputs go into a shell command unescaped;
  - `scan.yml` has no `permissions:` block.
- [ ] **Health email:** add per-stage durations (the spec asks for them). If GitHub kills a run, its stages stay marked "running" and no health email goes out.
- [ ] **README note:** snooze links work for anyone holding them for 30 days, so forwarding a digest forwards them.
- [ ] **Session cookie.** It is signed but not encrypted, so the email inside is readable as base64. And if `APP_BASE_URL` were unset in production, the cookie would lose its https-only flag.

## 3. Feature ideas (not scheduled)

**From the year-plan brainstorm**
- [ ] **Draft plan:** pin trips you're considering without booking them, and watch the plan's total price move day to day.
- [ ] **Bucket-list coverage:** "this year covers 2 of your 4 places", plus which ones fit next year instead.
- [ ] **Calendar export:** booked trips as an `.ics` file.
- [ ] **Use-it-or-lose-it nudge:** late in the year, flag unused PTO and short trips that would still fit.
- [ ] **A different target per year** for the same destination (today one target is shared by all years).
- [ ] **"I booked this" from the email**, not just the website.

**From the V2 list**
- [ ] **Adaptive polling:** check stable routes weekly, and volatile routes or departures within 90 days daily.
- [ ] **Crowd and shoulder-season signal** in go-now: add tourist-volume data to the score.
- [ ] **Per-user digest timezone and send-day preferences.**
- [ ] **Multi-city trips with more than two legs.** Open-jaw (two legs) is done.

**Search and destinations**
- [ ] **Region and landmark search** ("Bali", "Kyoto"). Only cities, countries and airport names match today.
- [ ] **Mark places you already track** in search results.

**Later and unsorted**
- [ ] **Travel companions:** alert only on the overlap between a partner's PTO windows and your own.
- [ ] **Visa and passport requirements** by nationality, including lead time.
- [ ] **Points and miles:** show award availability next to cash prices.
- [ ] **Monetization:** affiliate booking links, and sponsored itineraries from airlines and hotels.
- [ ] **Paid fare source** (Duffel, Kiwi, a paid SerpApi tier) if the free sources prove unreliable.

## 4. Polish backlog (from code reviews)

None of these is urgent. Items from Plans 1–6 come from those reviews and weren't all re-checked since, so a few may already be fixed.

**Planner and calendar**
- [ ] **A destination planned in no current year is silently never searched.** The destinations page gives no hint.
- [ ] **A range that starts in one year and spills into the next** shows in both calendars. Editing the later year saves the spillover again as a separate range.
- [ ] **Calendar accessibility:**
  - open days are shown by colour only (add `aria-pressed`);
  - every day is a separate Tab stop;
  - closing an open holiday still shows its red ring during the drag.
- [ ] **Touch and mouse edge cases:** a touch doesn't end a simultaneous mouse drag, and a cancel from any pointer drops a pending tap.
- [ ] **"Building price history" clears too early:** a reliable baseline for any month counts, including past ones.
- [ ] **Planner estimates count range days already past,** so mid-year they can be lower than what's still bookable.

**Booking (Plan 11 so far)**
- [ ] **Booking data checks:**
  - a caller-supplied PTO cost isn't checked for negative values;
  - two bookings saved at the same moment could both pass the overlap check.

**Destinations and search**
- [ ] **Same-city airports are listed alphabetically,** e.g. Rome's Ciampino before Fiumicino.
- [ ] **Re-adding a place with the same first airport** but a different set of airports reuses the old entry.
- [ ] **A failed or timed-out weather lookup** (10 s) leaves a place without season ratings, and nothing retries it.
- [ ] **An unrecognized home airport hides the minimum-length warning.**
- [ ] **A rejected add form** puts the airport code back in the search box.

**Profile and the YAML loader**
- [ ] **A profile file with no travel dates** gives destinations that are never scanned.
- [ ] **Reloading the file reactivates a listed destination** that was removed on the website.
- [ ] **Removing a field from the file** leaves its old value in the database.
- [ ] **`profiles load` with the database down** prints a stack trace instead of a clear message.

**Pipeline and data sources**
- [ ] **Google Flights flags any connection crossing midnight as an overnight layover** (23:50 → 00:30 is filtered out).
- [ ] **A missing Travelpayouts currency** is stored as blank instead of falling back to the requested one.
- [ ] **One malformed SerpApi item discards all of its options.**
- [ ] **Once SerpApi runs out mid-run,** later open-jaw trips are logged as "no source can price this" instead of "budget used up".
- [ ] **A destination missing from the season table** should log a warning (spec §6.5).
- [ ] **When a window has already started,** a few trip slots go to dates that are then dropped.
- [ ] **Flight details describe only the outbound flight;** the digest should say so.
- [ ] **The source comparison ignores the return airport,** so an open-jaw fare could be paired with a round trip.

**Digest and email**
- [ ] **The 7-day trend shows "new"** if the scan exactly a week earlier didn't run.
- [ ] **The tracker table always shows `$`,** and "best now" counts excluded trips.

**Tests and code tidiness**
- [ ] **Test gaps:**
  - no test for the `convert-targets` command;
  - adding a place through the page isn't tested end to end;
  - the calendar script has no automated browser test (it was checked by hand);
  - several "Start planning", planner and booking tests use loose checks.
- [ ] **Repeated values:** the ±2-day rule is a literal 2 in two places, and the page's target limits (2–60) are typed in by hand.
- [ ] **Unused code:** the profile form still has travel-date and destination parsing used only by tests.
- [ ] **Small inefficiencies:**
  - the dashboard looks up "Building price history" one destination at a time;
  - the digest loads every baseline and sent-record on each run.
- [ ] **Small inconsistencies:**
  - the score and the planner treat "no target" slightly differently;
  - `route_baselines.sigma` is named `mad_sigma` in the spec;
  - the model/migration drift test doesn't check defaults.

## Done

- [x] **Your own destinations:** search, add and remove on the website (Plan 9).
- [x] **Year-plan view, part 1:** planning years, the planner page, drag calendar, "Start planning" (Plan 10). Part 2 is Plan 11.
- [x] **Open-jaw itineraries:** fly into one city and home from another (Plan 4: Camino Portugués, Porto → Santiago, priced through SerpApi).
- [x] **Digest visual polish, and web app look and feel** (Plan 7; spec `docs/superpowers/specs/2026-10-17-ptopilot-v2-look-and-feel-design.md`).
- [x] **Preferred trip length:** `ideal_trip_days` steers which trips are priced and adds a go-now bonus (Plan 7).
- [x] **History seeding and daily checks of every in-range route** (Plan 8; spec `docs/superpowers/specs/2026-10-18-ptopilot-v2-price-data-design.md`).
- [x] **Broad scan "to anywhere":** tested 2026-10-18 and not useful for niche routes. The existing broad scan keeps running (free) for hub destinations.
- [x] **fast-flights completeness check:** measured in the scan health email (Plan 8). Revisit the source order if fast-flights proves systematically pricier.
