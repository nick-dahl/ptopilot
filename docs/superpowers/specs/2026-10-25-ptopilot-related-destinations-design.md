# ptopilot — Related Destinations (Design)

**Date:** 2026-10-25
**Status:** Approved 2026-10-25
**Builds on:** [Year plan / your destinations](2026-10-25-ptopilot-year-plan-design.md) (Plan 9: airport catalog, added places, climate seasons), [Buy now or wait](2026-10-25-ptopilot-buy-now-or-wait-design.md) · **Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) "Related destinations"

Third of the user's three V2 features.

---

## 1. Intent

**Why.** A traveler's bucket list is a starting point, not a fence. Two kinds of nearby alternatives are worth a look when the price is right:
- **Immediate:** another convenient airport for the same trip. Going to Paris, you'd accept flying into a nearby airport.
- **Thematic:** a different place with a similar experience. Interested in Budapest, Prague would do for an amazing deal.

**What the user wants, in their words, condensed:**
- **A small component**, not a second search. Don't "bog down the grid search with several other routes" or stray from the core.
- **Linked places:** if ptopilot can link similar destinations and finds a **stunning deal that otherwise fits all of the search criteria**, surface it.
- **ptopilot proposes the links; the user accepts them.**
- Surface such deals in an **"Also worth a look"** section of the digest.

**Success looks like:**
- A handful of sensible suggested links per destination, accepted or dismissed in a click.
- Rarely, a related place with a stunning, fitting deal appears under "Also worth a look", without making the daily scan slower or more fragile.

---

## 2. Goals, non-goals, anti-goals

**Goals**
1. **Suggested links** for each destination, immediate and thematic, shown on the destinations page with Accept / Dismiss.
2. **A light watch** on accepted related places. Free cached fares find candidates. A small daily number of live checks confirms them.
3. **Strict surfacing.** A related deal is shown only if it is stunning **and** fits the user's criteria (§3.4).
4. **"Also worth a look"**, a digest section after the main deals, and a "Related" note on the main destination's page.

**Non-goals**
- Adding related places to the full daily grid. They never get route queries, baselines or seeding like tracked places.
- Instant alerts for related deals.
- Automatically tracking a related place. The user can always add it as a real destination.

**Anti-goals**
- Noise: more than a few related deals in a digest, or related deals that aren't remarkable.
- Slowing the scan or spending the SerpApi budget on related places.
- Suggesting places that don't fit the user's season tolerance or trip length.

---

## 3. Decided behavior

### 3.1 Suggesting links (my calls)
- **Immediate:** other catalog airports within `RELATED_NEAR_KM` (65, great-circle, measured from the nearest of the destination's airports) of the destination's airports, in any country, that aren't already among its airports. Large and medium airports only.
  - **Why 65 km:** that's under an hour on the ground at the [skip-miserable-flights](2026-10-26-ptopilot-skip-miserable-flights-design.md) rate of 65 km/h. The user moved this from 160 km on 2026-10-26, to match their rule that an airport an hour or more away is unattractive.
  - **Example:** London → Southend (SEN, about 60 km). Paris's Beauvais (BVA, about 75 km) is now out of range.
- **Thematic:** a small bundled `ptopilot/data/related.yaml` of hand-curated groups of similar places, each a list of airport codes with a group name. Groups contain **only major tourist destinations** (the user's rule): second-tier spots such as Kraków are left out. Examples: "Central European capitals" (BUD, PRG, VIE), "Atlantic islands" (PDL, FNC, TFS, LPA), "Patagonia" (PUQ, FTE, USH). A destination's thematic suggestions are the other members of any group containing one of its airports.
- **Cap and order:** at most `RELATED_MAX_SUGGESTIONS` (5) per destination, thematic first, then immediate by distance.
- **Accept / Dismiss:** accepted links are stored per user and destination. Dismissed links are remembered so they aren't suggested again.

### 3.2 The light watch (my calls)
- **Free scan (my call):** once per scan, for each **accepted** related airport, make the existing Travelpayouts month scan (`month_scan(origin, related_airport, month)`) for the user's home airports and the months of their open ranges. These calls are free and reuse the existing request and parser.
  - A user accepts only a handful of links, so this is a few dozen free calls at most.
  - Per-pair scans were chosen over "to anywhere": the 2026-10-18 probe showed "to anywhere" returns only about 100 popular fares per origin-month and rarely includes mid-size places.
- **Promising:** a cached fare is promising when it is at least `RELATED_STUNNING_PCT` (25%) below the **main destination's** typical price (its route-month baseline median for the same trip-length bucket) and passes the fit checks in §3.4.
- **Cached fares are signals (my call):**
  - Only round-trip cached fares count; one-way fares are skipped.
  - The candidate's dates are the cached fare's own dates, and it must fit as-is (§3.4). No search for better dates.
  - The "typical" is the main destination's baseline for the bucket of the cached fare's length.
  - If the main destination has no `normal`-confidence baseline for that month and bucket, the pair is skipped (fail closed).
- **Shared related airports (my call):** links are stored per (related place, main destination). When one related airport is linked to several main destinations, the deal is compared against the **lowest** of their typical prices (the strictest test) and shown once, naming that destination.
- **Booked or removed main destinations (my call):** links of a booked or inactive main destination aren't watched.
- **Confirming:** at most `RELATED_LIVE_CHECKS_PER_DAY` (5) promising fares a day get one free Google live check (fast-flights) on those exact dates. Only confirmed live prices are surfaced. No SerpApi calls.
- **Cap details (my call):**
  - The cap is global per scan.
  - Promising fares are ranked by the biggest discount against the main destination's typical.
  - Every attempt counts against the cap, failures included.
  - Results are stored per run date, like candidates, so the digest and site read today's confirmations. Unconfirmed fares are simply re-evaluated the next day.

### 3.3 Why "below the main destination's typical"
A related place has no history of its own: that's the point of keeping it light. The user's question is "is this a better use of the trip than the place I'm tracking?", so the comparison is against what the main destination usually costs for a comparable trip.

### 3.4 Stunning and fitting (all required)
- Confirmed live price ≥ 25% below the main destination's typical, as above.
- Dates within the user's open ranges, PTO cost within PTO left, length within the main destination's target ±2 days. The planner's own rules apply, with travel time from distance.
- The related place's season is **good** for the trip month.
  - **Storage (my call):** accepting a link creates the place in Plan 9's `destinations` table without a tracker, so its ratings live in `destination_seasons`, generated once by the same climate lookup.
  - With no ratings (lookup failed), it is never surfaced (fail closed). The lookup is retried the next time the link is accepted or viewed.
- It overlaps no booked trip (Plan 11).

### 3.5 Where it shows
- **Digest:** an **"Also worth a look"** section after the main deals, with at most `RELATED_MAX_IN_DIGEST` (3) items. Each reads "{related place} instead of {main destination}", with price, how far below the main destination's typical, dates, PTO, and View flights. It uses a calm, distinct style, never the standout treatment.
- **Site:** the main destination's page shows a small "Related" panel with the current confirmed related deals.
- Shown only while the confirmed price is from today's scan.
- **Same email (my call):** the section rides in the regular Mon/Thu digest. A digest with no main deals but a related deal still goes out on its scheduled day, with the section as its content.

---

## 4. Constraints

- **Cost and load:** free sources only (Travelpayouts cache, fast-flights). At most 5 extra live checks a day per scan. No SerpApi.
- **The core daily grid** (route queries, baselines, seeding, alerts) is unchanged in size and behavior.
- **Look:** the existing design system and email patterns. Commit and push to `main`, and migrations reach Neon first. Never print or commit secrets.
- **Order:** builds on Plans 9–12 (catalog, climate, planner open ranges and targets, booked trips, digest structure). It's last in the agreed queue, so all four are done before this is planned.

---

## 5. Left to the builder

- The initial contents of `related.yaml`: a dozen sensible groups of **major tourist destinations only**, including groups for the user's current places.
- The data model for accepted and dismissed links.
- How "to anywhere" results are matched to related airports and dates (exact dates from the cache vs re-deriving the best dates within the open ranges).
- Exact visual treatment of the digest section and the site panel within the design system.
