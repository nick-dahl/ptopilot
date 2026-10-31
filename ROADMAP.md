# ptopilot Roadmap

V1 scope and design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md). V1 and Plans 7–14 are live. This page is the agenda: what's queued, what to settle before inviting friends, feature ideas, and the polish backlog from code reviews.

## 1. Queued work, in order

The owner wants the site to feel like a polished travel product before friends see it: the calm, data-first polish of Google Flights and Capital One Travel, and "the first website I want to go to when I'm daydreaming about how to spend my time off". The checklist in §2 follows these.

- [ ] **Plan 15: site polish (designing now).** It covers:
  - guided onboarding for new users, one step at a time;
  - Google-Flights-style inputs everywhere: type-ahead airport chips, plain-language choices, a trip-length slider;
  - a "reason you came" hero card for the day's best deal, with a countdown when time matters;
  - destination cards with cover photos;
  - livelier destination pages.
- [ ] **Plan 16: hidden gems (planned, runs after Plan 15).** Plan: `docs/superpowers/plans/2026-10-31-ptopilot-plan-16-hidden-gems.md`; design approved 2026-10-31. It covers:
  - a weekly magazine of off-the-beaten-path, affordable places, matched to your trip styles;
  - a live-checked fare with a "fits your dates" pill;
  - a "Track this place" button.

  Write-ups are drafted and approved with the owner in sessions, with no AI API for now.
- [ ] **Then the pre-invite checklist (§2).**

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

**Booking, fit notes, combinations and banner (Plan 11)**
- [ ] **Booking data checks:**
  - a caller-supplied PTO cost isn't checked for negative values;
  - two bookings saved at the same moment could both pass the overlap check (revisit before inviting friends).
- [ ] **Booked days on the calendar:**
  - a booked holiday's tooltip drops the holiday name;
  - a day that is both booked and open flashes during a drag-close.
- [ ] **Booking and fit-note details:**
  - fit notes also show on dimmed (snoozed or excluded) deal rows;
  - a signed-out "I booked this" gives a 404 rather than a sign-in redirect;
  - "Start planning" lists last year's booked destinations unchecked, rather than leaving them out.
- [ ] **Combination search:**
  - it is capped at 12 destinations;
  - with mixed currencies, the savings line would use the first leg's;
  - a confidence field defaults to "normal", so a missed constructor could let a low-confidence offer in;
  - the pruning has no randomized regression test.
- [ ] **Totals:**
  - year totals are recomputed (with estimates) on every dashboard load and digest build, with no caching;
  - in the text email, the banner comes before the "ptopilot · date" line.
- [ ] **Test tidiness:**
  - several loose or after-the-fact tests (dashboard bar numbers, the banner year test, test_plan_totals);
  - the `pto_bar` macro mixes new and old parameters.

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

**Skip miserable flights (Plan 12)**
- [ ] **Measure the real effect** after a few daily scans: how many of the owner's dates are ruled out or forgiven. The health email now shows a `ruled_out=` count.
- [ ] **Behaviour details:**
  - a trip over its max price whose only cheaper option is ruled out disappears instead of showing greyed;
  - the email's tracker table shows bare dashes for a destination whose trips are all ruled out.
- [ ] **Same-city rule:** it uses the first airport the catalog knows, not strictly the first listed. Several geo branches are untested (an open-jaw return in another city, no known airports, a destination without coordinates).
- [ ] **Code tidiness:**
  - the two sources treat negative layover gaps differently;
  - there's no downgrade test for migration 0009;
  - a few contrived or weak tests (the slow-option test, `set(asked) <= {4}`, a test that overwrites its options, a stale test name in test_return_check);
  - the planner filter could use `not o.dimmed`;
  - the buy-now-or-wait plan's `alerts.run` Produces line doesn't list the `would_send_return_*` counts.

**Buy now or wait (Plan 13)**
- [ ] **Measure it:** after a few scans, check how many deals get a duration estimate and whether any standouts or alerts appear.
- [ ] **Alerts:**
  - the send log is written after the email, so a failed write lets a re-run resend, and an overlapping run could stop later users' alerts;
  - a crashed return check sends the alert without showing in the health email;
  - a `--dry-run` makes real return searches and uses up that day's 3 return checks and SerpApi calls;
  - the README's stage list doesn't name `alerts` (or `seed_history`).
- [ ] **More alert edge cases:**
  - a manual run for a past `--date` can send a stale "instant" alert;
  - raising `ALERTS_PER_DAY` above 1 would fail on the one-per-day database rule;
  - removing a destination deletes its alert history, so re-adding it allows another alert within the week;
  - the digest's 8-deal cut can drop a standout before the lead card is chosen;
  - the 3 return checks a day are shared by all users (revisit before inviting friends).
- [ ] **Duration estimate:**
  - it says at least "~1 day" even on departure day, and rounds the typical dip length up;
  - a missed scan yesterday makes today's own dip count as a past one;
  - a brand-new trip with under 10 days of history says "not enough history yet" even when today isn't a dip;
  - the live-check purpose values (`trip`, `return`, `dryret`) are bare strings.
- [ ] **Code tidiness:**
  - the "standout" rule and its labels are repeated in the digest and site code;
  - trip history costs two queries per trip, and the dip search rescans the series per day;
  - a few loose or missing tests (the go-now cap, ruled-out standouts in the digest, the one-day subject).
- [ ] **Look:** a greyed destination row that is also standout shows the Rare tag without the accent; only the digest's lead card gets the standout border.

**Related destinations (Plan 14)**
- [ ] **Measure it:** after a few scans, check which suggestions appear, which you accept, and whether any related deals are confirmed.
- [ ] **Suggestions:**
  - Lisbon is in two groups, so the cap of 5 cuts Seville for it;
  - "Remove" on an accepted place is a permanent dismissal, with no way back in the page;
  - dismissing a place you added yourself stores its airport code as the place code (harmless, but uncommented).
- [ ] **Watch:**
  - the live currency is never checked against the USD typical (today they can't differ);
  - two users with the same trip spend two of the day's 5 checks on the same search;
  - the trip year, the season lookup and the length band are worked out again inside loops (once per link or quote, not once per user or trip);
  - two page views at once can both save the same climate row, and a double-submitted accept can fail one of the two requests (nothing is corrupted);
  - a missing climate lookup is retried once per page view, so a place that keeps failing and sorts first blocks retries for the places after it.
- [ ] **Digest and site:**
  - related deals are never recorded as sent, so one repeats in every digest while it lasts and can make an otherwise quiet digest go out;
  - the check that hides snoozed destinations doesn't hide ones you booked after the scan, so that day's card can still show;
  - the destinations page makes a few extra queries per destination.
- [ ] **Code tidiness:**
  - `place_for` takes a session it doesn't use, and `dismiss` loads the airport list itself where `accept` is handed it;
  - `_typical` has no return annotation, and the plan doc still lists `related_deals` without its `today` parameter.
- [ ] **Tests:**
  - none pins the nearest-of-two-own-airports distance, accepting one airport of a multi-airport place of your own, or the climate retry directly;
  - the cap test checks kinds, not which five survive;
  - no test that a snoozed destination's related places aren't watched;
  - the panel test matches "Related" anywhere on the page, and the snoozed-panel test accepts either of two strings.

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

- [x] **Related destinations:** each destination suggests up to 5 related places (curated look-alikes and airports within 65 km) to accept or dismiss on the destinations page; a light daily watch (free cached fares, at most 5 free live checks a day) surfaces a stunning, fitting fare under "Also worth a look" in the digest and in a "Related" panel on the destination page (Plan 14; spec `docs/superpowers/specs/2026-10-25-ptopilot-related-destinations-design.md`).
- [x] **Buy now or wait:** a stricter go-now score that judges each trip against its own price history and discounts thin evidence; "likely gone within ~N days" on every deal; "Rare" standout offers on the site and in the digest; and instant alert emails (at most one a day, the same destination at most once a week) after checking the flight home (Plan 13; spec `docs/superpowers/specs/2026-10-25-ptopilot-buy-now-or-wait-design.md`).
- [x] **Skip miserable flights:** itineraries with very long layovers, needlessly long journeys or a landing far from the destination are ruled out (greyed on the destination page), unless a fare about 40% below typical forgives one moderate problem. Includes a one-way return-flight check for instant alerts (Plan 12; spec `docs/superpowers/specs/2026-10-26-ptopilot-skip-miserable-flights-design.md`).
- [x] **Your own destinations:** search, add and remove on the website (Plan 9).
- [x] **Year-plan view:**
  - planning years, the planner page, drag calendar and "Start planning" (Plan 10);
  - "I booked this", fit warnings on deals, "fantastic on every leg" combinations, and the email banner with booked, planned and left PTO (Plan 11).
- [x] **Open-jaw itineraries:** fly into one city and home from another (Plan 4: Camino Portugués, Porto → Santiago, priced through SerpApi).
- [x] **Digest visual polish, and web app look and feel** (Plan 7; spec `docs/superpowers/specs/2026-10-17-ptopilot-v2-look-and-feel-design.md`).
- [x] **Preferred trip length:** `ideal_trip_days` steers which trips are priced and adds a go-now bonus (Plan 7).
- [x] **History seeding and daily checks of every in-range route** (Plan 8; spec `docs/superpowers/specs/2026-10-18-ptopilot-v2-price-data-design.md`).
- [x] **Broad scan "to anywhere":** tested 2026-10-18 and not useful for niche routes. The existing broad scan keeps running (free) for hub destinations.
- [x] **fast-flights completeness check:** measured in the scan health email (Plan 8). Revisit the source order if fast-flights proves systematically pricier.
