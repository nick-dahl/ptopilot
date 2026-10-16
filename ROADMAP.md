# ptopilot Roadmap

V1 scope and design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md)

## V2: begin once V1 runs end to end

- [ ] **Year-plan view.** Combine several deals into a single plan that fits the annual PTO budget, e.g. "Lisbon in April plus Thailand in September uses 14 of 20 PTO days." Replace the V1 manual `pto_committed` with booked trips that are tracked.
- [ ] **Open-jaw and multi-city itineraries.** Fly into one city and out of another (e.g. into BKK, out of DPS). Requires a new shape type and new source queries.
- [ ] **"Buy now or wait" advice.** Use price-trend history per route and lead time to recommend booking now or holding.
- [ ] **Related destinations.** Suggest places similar to the bucket list (Thailand → Vietnam). This is also the hook for sponsored or affiliate placements.
- [ ] **Adaptive polling.** Check stable routes weekly and check volatile routes, or departures within 90 days, daily.
- [ ] **Crowd and shoulder-season signal in go-now.** Add tourist-volume data to the score.
- [ ] **Per-user digest timezone and send-day preferences.**
- [ ] **Digest visual polish.** Iterate on the design once real MVP emails exist.

## Later and unsorted ideas

- [ ] Travel companions: alert only on the overlap between a partner's PTO windows and your own.
- [ ] Visa and passport requirements by nationality, including lead time.
- [ ] Points and miles: show award availability next to cash prices.
- [ ] Monetization: affiliate booking links, sponsored itineraries from airlines and hotels.
- [ ] Paid fare source upgrade (Duffel, Kiwi, a paid SerpApi tier) if the free sources prove unreliable.
