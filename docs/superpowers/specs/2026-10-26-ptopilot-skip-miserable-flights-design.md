# ptopilot — Skip Miserable Flights (Design)

**Date:** 2026-10-26
**Status:** Approved 2026-10-26
**Builds on:**
- [V1 spec](2026-10-16-ptopilot-design.md) §7 (live checks, scoring);
- [Year plan](2026-10-25-ptopilot-year-plan-design.md) (destination airports and nearby airports);
- [Buy now or wait](2026-10-25-ptopilot-buy-now-or-wait-design.md) §3.4 (instant alerts);
- [Related destinations](2026-10-25-ptopilot-related-destinations-design.md) (nearby-airport alternatives).

**Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) "Skip miserable flights".

---

## 1. Intent

**Why.** A cheap fare isn't a deal if the trip is miserable. Today ptopilot already caps stops (from the profile), can rule out overnight layovers, and drops options more than 1.5× slower than the fastest. It doesn't judge two things:
- a single long layover;
- landing far from where the traveler is actually going.

It also has no way to weigh several moderate annoyances together, or to let a truly exceptional price buy some tolerance.

**What the user wants, in their words, condensed:**
- **Don't surface miserable flights:**
  - three or more flights (already covered by the stop caps);
  - layovers longer than about **5–6 hours**, which make the journey "unnecessarily long";
  - airports **an hour or more** away from where they want to end up.
- **Combined criteria:** an itinerary is ruled out by *either* one extremely poor feature *or* several moderately unattractive ones together.
- **Weighed against price:** at roughly **40% below typical**, the user would still want to see an itinerary with one moderate problem (for example a 7-hour layover, or landing 75 minutes away).
- **The flight home** is checked only before an off-schedule, highly attractive email is sent. If it doesn't live up to expectations, that email is cancelled. Otherwise, judging the outbound journey is enough.
- **On the website, ruled-out itineraries are greyed out**, not hidden, "so that we know the process is running well".

**Success looks like:**
- No email or dashboard card leads with an itinerary the user would wince at.
- A great price with one bearable flaw still gets through, and its trade-off is named.
- The destination page shows what was skipped and why, so the filter can be trusted and tuned.

---

## 2. Goals, non-goals, anti-goals

**Goals**
1. **A misery check** for every live-priced itinerary, looking at three problems: longest layover, total travel time against the fastest option, and ground time from the landing airport. Each problem is graded none, moderate or severe.
2. **A combined verdict:** acceptable, forgiven (by price) or ruled out.
3. **Best acceptable option per trip:** when the cheapest itinerary for a set of dates is ruled out, the trip uses the cheapest acceptable one on the same dates, and its deal is judged on that price.
4. **Visibility:**
   - ruled-out itineraries are greyed out with their reason on the destination page;
   - forgiven ones carry a short trade-off note;
   - neither ever leads the dashboard or an email.
5. **The return-flight check before an instant alert:** one extra search of the flights home for the alert's exact dates, with the same rules. A miserable return cancels that alert.

**Non-goals**
- Judging the flights home for the regular digest or the website.
- Airline quality, seat comfort, aircraft type, or departure-time preferences beyond the existing Friday-evening rule.
- Real driving times from a maps service. Ground time is estimated from distance.
- Changing the stop caps or the overnight-layover preference.

**Anti-goals**
- Hiding things silently: a ruled-out itinerary must be visible as such on the website.
- Being so strict that ordinary good deals disappear. A trip with no problems is judged on price exactly as today.
- Spending more searches. The only new search is the one return check before an instant alert, and alerts are capped at one a day.

---

## 3. Decided behavior

### 3.1 The three problems (my calls on the lines; all in one config block)

| Problem | Moderate | Severe |
|---|---|---|
| **Longest layover** on the outbound journey | over 5h | over 9h |
| **Total travel time** against the fastest option found for the same trip and dates | 40% or more longer | twice as long or more |
| **Ground time** from the landing airport to the destination | 1h or more | 2h or more |

- **Longest layover** is the longest single connection, not the total.
  - Both sources give per-flight times: fast-flights segments, and SerpApi legs and layovers.
  - Today only the total travel time is stored, so the longest layover needs storing too.
- **Total travel time** replaces today's hard 1.5× rule. 1.4× becomes moderate (forgivable) and 2× severe.
  - So a 1.6× itinerary is now shown only when the price is exceptional, instead of always dropped.
- **Ground time:**
  - **The destination's own airports count as "you're there"** (ground time 0). For example Azores means Ponta Delgada, Tokyo means Haneda or Narita, and Camino Portugués means its arrival airports.
  - **Other airports are timed** by great-circle distance from the nearest of the destination's own airports, at `GROUND_KM_PER_HOUR` (65) km per hour of ground travel. This mainly covers:
    - nearby airports a traveler ticked when adding a place (Plan 9);
    - "related destinations" alternatives. The user shrank their radius from 160 km to 65 km (under an hour) on 2026-10-26, so they always fall below the moderate ground-time line.
  - **Which airports are "own" (my call), with no data migration:**
    - every airport of a built-in place in `geo.yaml` (Tokyo HND+NRT, Azores, Camino's arrival and return airports);
    - for a place added from the catalog, the airports whose catalog city matches its first airport's city (e.g. Rome FCO and CIA).
    - Any other airport a traveler ticked as "nearby" gets timed.
- **Stops:** unchanged. The profile caps still apply first, and the overnight-layover preference still applies.

- **"Fastest" (my call):** the fastest of all that day's live options for the same route and dates, as today's 1.5× rule measures it, before the stop and overnight filters.

### 3.2 The verdict (my call, following the user's 40% line)
- **Acceptable:** no problems. Judged on price as today.
- **The verdict is per trip offer (my call).** It is computed when a trip is scored, for each tracker's candidate, and stored with it. Ground time depends on the destination and forgiveness on that route's baseline, so two trackers sharing a route can get different verdicts.
- **Forgiven:** exactly one *moderate* problem, and the fare is **at least `MISERY_FORGIVE_PCT` (40)% below typical**, i.e. price ≤ 0.6 × the baseline median.
  - "Typical" is the same baseline median the deals already show, and it must be a `normal`-confidence baseline.
  - It is shown, with a trade-off note.
- **Ruled out:** any of these:
  - a severe problem;
  - two or more moderate problems;
  - one moderate problem without the 40% price;
  - one moderate problem without a reliable typical price.

### 3.3 Choosing the itinerary for a trip
- Among a trip's live options (same route, dates and departure variant), drop those that fail the existing filters (stops, overnight, Friday evening).
- Then pick the **cheapest option that isn't ruled out**, with forgiven ones counting as allowed. Its price drives the deal level, go-now, the digest and the dashboard.
- **When every option is ruled out**, the trip still gets recorded for the website, greyed out with the reason of its cheapest option. It never becomes a deal: no email, no dashboard "best", no combination leg, no instant alert.
- Cached (unverified) fares have no flight details. They're unaffected until a live check prices them, as today.

### 3.4 Where it shows
- **Destination page:**
  - a ruled-out trip stays in the date list, greyed out like snoozed or excluded trips, with its reason;
  - a forgiven trip shows normally with a small trade-off note in the same style as fit notes.
- **Reason and note wording (my call):**
  - "9h layover in Madrid";
  - "38h journey, 2.1× the fastest";
  - "Lands ~1h 15m from Tokyo";
  - with two problems, both joined with " · ".
  - A forgiven note reads as the problem plus "(worth it at 42% below typical)".
- **Dashboard card:** "best" skips ruled-out trips. A forgiven best shows its note.
- **Other readers (my call):** the 30-day price trend, the typical band and every count ignore ruled-out trips. The destination page's date list is the only place they appear.
- **Email:**
  - ruled-out trips never appear;
  - forgiven ones carry the note under the PTO line, like fit notes.
- **Combinations (Plan 11):** only acceptable or forgiven legs.

### 3.5 The flight home, before an instant alert
- This is tied to the buy-now-or-wait plan's `alerts` stage.
- **Before an instant alert is emailed,** ptopilot makes one search for the flights home on the alert's exact dates:
  - fast-flights first, with the return leg as a one-way search;
  - SerpApi only if that fails and budget allows (my call).
- **It applies the same three problems** to the return journey's options. Ground time is measured at the departure airport.
- **How the return passes (my call):** it passes when *any* option in that search is acceptable, or forgiven. Forgiveness uses the alert's own round-trip discount against typical, because a one-way fare has no comparable baseline.
- **If the return is ruled out, the alert isn't sent.** The trip may still appear in the next regular digest, which judges only the outbound journey.
- **That day's alert slot isn't used up,** so the next-best standout candidate can be tried, capped at `RETURN_CHECKS_PER_DAY` (3) searches a day (my call).
- **Failure (my call):** if the return search fails (source down), the alert is sent as today, without the return check. A missing check shouldn't silence a rare deal.

---

## 4. Constraints

- **Stack and cost:** Python, Postgres on Neon, the GitHub Actions daily scan, free sources only. The only new searches are the return checks before instant alerts, at most `RETURN_CHECKS_PER_DAY` (3) a day.
- **Daily scan:** grid size and timing are unchanged. The misery check uses data the live checks already return, plus the longest layover, which they must now record.
- **Look:**
  - the existing design system and email patterns;
  - greyed-out rows reuse the dimmed style;
  - notes reuse the fit-note style.
- **Process:**
  - migrations reach Neon before code that reads them deploys;
  - commit and push to `main`;
  - never print or commit secrets.
- **Order:**
  - It builds on Plans 9–11, which are done.
  - It goes before buy-now-or-wait, which becomes Plan 13, and related destinations, which becomes Plan 14.
  - **§3.5 (my call):** this plan ships the return check as a tested function plus its config, and edits the buy-now-or-wait plan so its alert task calls it. The "try the next candidate, up to 3 checks a day" loop and the "send anyway if the search fails" rule are built in that plan's alerts stage, since the stage doesn't exist yet.

---

## 5. Left to the builder

- **Data model:**
  - where the longest layover is stored (on price observations);
  - where the verdict and reason live (computed when scoring, stored on the candidate, or recomputed when shown);
  - how a "ruled out" trip is recorded so the destination page can grey it out.
- **The parsing details** for each source's per-flight times. This includes SerpApi's explicit `layovers` list against computing gaps from leg times.
- **Whether ground time for a destination's airports** is precomputed when places are loaded, or computed on demand from the catalog's coordinates.
- **How the return-flight search is expressed** for each source (one-way search, or a round-trip search reading the return leg).
- **Exact copy for edge cases** (an unknown connection airport, an itinerary missing times).
