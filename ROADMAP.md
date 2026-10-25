# ptopilot Roadmap

V1 scope and design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md)

## V2: begin once V1 runs end to end

- [ ] **Year-plan view.** (Your own destinations, searched and added on the website, are done: Plan 9.) Combine several deals into a single plan that fits the annual PTO budget, e.g. "Lisbon in April plus Thailand in September uses 14 of 20 PTO days." Replace the V1 manual `pto_committed` with booked trips that are tracked.
- [x] **Open-jaw itineraries.** Fly into one city and home from another (Plan 4: Camino Portugués, Porto → Santiago, priced through SerpApi). Multi-city with more than two legs is still open.
- [ ] **"Buy now or wait" advice.** Use price-trend history per route and lead time to recommend booking now or holding.
- [ ] **Related destinations.** Suggest places similar to the bucket list (Thailand → Vietnam). This is also the hook for sponsored or affiliate placements.
- [ ] **Adaptive polling.** Check stable routes weekly and check volatile routes, or departures within 90 days, daily.
- [ ] **Crowd and shoulder-season signal in go-now.** Add tourist-volume data to the score.
- [ ] **Per-user digest timezone and send-day preferences.**
- [x] **Digest visual polish.** Lead deal card and compact rows in destination colors (Plan 7).
- [x] **Web app look and feel.** Design system, landing page, destination-grid dashboard, destination pages with a 30-day price trend (Plan 7; spec `docs/superpowers/specs/2026-10-17-ptopilot-v2-look-and-feel-design.md`).
- [x] **Preferred trip length.** `ideal_trip_days` steers which trips are priced and adds a go-now bonus (Plan 7).

## Data quality: findings from real API calls (2026-10-16)

- [x] **Broad scan by city, "to anywhere" (tested 2026-10-18, not useful for niche routes).** NYC/EWR→anywhere for March 2027 returns ~100 fares to 59 destinations but none to PDL, FNC, PUQ or OPO; October 2027 returns 10 fares in total; exact NYC→PDL/FNC/PUQ returns nothing in any month. Travelpayouts only caches recently searched routes. The existing broad scan keeps running (free) for hub destinations.
- [x] **Check fast-flights for completeness.** Measured in the scan health email on trips both sources price the same day: each seeded trip while history seeding runs, plus SerpApi fallbacks (Plan 8). Revisit the source order if fast-flights proves systematically pricier; a continuous audit would need spare SerpApi calls, which Camino currently uses.
- [x] **History seeding.** SerpApi round-trip results carry ~60 days of Google's own daily prices; one call per baseline key seeds a confident baseline (Plan 8; spec `docs/superpowers/specs/2026-10-18-ptopilot-v2-price-data-design.md`). Also: every in-range route is checked daily, and routes Google returns no itineraries for no longer trip the circuit breaker.

## Later and unsorted ideas

- [ ] Travel companions: alert only on the overlap between a partner's PTO windows and your own.
- [ ] Visa and passport requirements by nationality, including lead time.
- [ ] Points and miles: show award availability next to cash prices.
- [ ] Monetization: affiliate booking links, sponsored itineraries from airlines and hotels.
- [ ] Paid fare source upgrade (Duffel, Kiwi, a paid SerpApi tier) if the free sources prove unreliable.
