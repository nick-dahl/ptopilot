# ptopilot — Buy Now or Wait (Design)

**Date:** 2026-10-25
**Status:** Draft, awaiting review
**Builds on:** [V1 spec](2026-10-16-ptopilot-design.md) §7–8 (scoring, digest), [V2 price data](2026-10-18-ptopilot-v2-price-data-design.md) (Google history seeding) · **Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) "Buy now or wait"

Second of the user's three V2 features, after the year plan and before related destinations.

---

## 1. Intent

**Why.** A deal email today says a trip is cheap, with a go-now score and a percentage below typical. It doesn't say how good the opportunity really is, or whether it will still be there next week. The user wants to know two things: how strong an offer is, and how urgently to act. Truly exceptional, short-lived offers shouldn't wait for the next Monday or Thursday digest.

**What the user wants, in their words, condensed:**
- **A rigorous "quality index".** It reflects how good the opportunity is: right timing, right season, how many standard deviations below typical. This is not a new number. The existing **go-now score** becomes that index, provided it factors in the right data rigorously.
- **"Expected duration"** beside it: how long the low price is likely to last, shown as **"likely gone within ~3 days"** (a rough time, not a probability).
- **Escalation.** When an offer is extreme enough, the call to action is more dramatic, so the urgency or uniqueness is obvious.
- **Instant alerts.**
  - Exceptional, likely-transient offers are emailed **right away**, outside the Mon/Thu cadence.
  - If they're still there at the regular digest, they appear again, **flagged with more dramatic colours**: obviously standout.
  - Limits: **at most one instant alert a day**, and **never the same destination twice in the same week**.

**Success looks like:**
- Each deal shows a go-now score the user trusts and a duration line, on the site and in email.
- A few times a season at most, a genuinely rare fare arrives as its own email the morning it appears.
- Ordinary deals stay calm, so the dramatic treatment keeps its meaning.

---

## 2. Goals, non-goals, anti-goals

**Goals**
1. **Go-now v2.** A more rigorous score: deal depth, judged conservatively and with confidence in mind, plus season, PTO efficiency, length fit and timing. Still 0–100, same name and same place in the UI.
2. **Expected duration** per offer, from the route's own price history and the time left before departure. Shown as "likely gone within ~N days", "likely to hold for a week or more", or "not enough history yet".
3. **Standout offers.** A clear, testable threshold for "exceptional" (§3.3), and a distinct, louder look for them on the site and in the digest.
4. **Instant alerts.** A short single-trip email right after the daily scan, rate-limited per §3.4.

**Non-goals**
- Predicting prices days ahead with a learned model.
- Push notifications or SMS.
- Changing the Mon/Thu digest schedule.
- Changing the year plan (Plans 9–11) beyond showing the new fields.

**Anti-goals**
- Alerting on a merely good deal, or alerting so often that alerts stop meaning anything.
- A duration claim the data can't support. When history is thin, say so.
- Dramatic styling leaking onto ordinary deals.

---

## 3. Decided behavior

### 3.1 Go-now v2 (my calls on what "rigorous" means)
The score keeps its five parts and weights (deal 0.5, weather 0.2, efficiency 0.15, length 0.1, timing 0.05). The deal part gets stricter:
- **Conservative depth.** When the exact trip has its own price history of at least `TRIP_HISTORY_MIN` (10) daily points, which seeded Google history provides, the deal z-score is the **less extreme** of:
  - the z against the route-month baseline;
  - the z against that trip's own history.
  - A trip that's normally cheap doesn't look like a steal against a pricier month-wide average.
- **Confidence.** A `low`-confidence baseline caps the deal part at half its weight. A cached (unverified) price caps it the same way.
- **Timing.** It stays as today (the 30–120-day sweet spot for international trips). The time-pressure aspect of timing lives in expected duration (§3.2), which also uses days to departure.

### 3.2 Expected duration (my calls on the method; the builder may refine within these rules)
- **Data:**
  - each trip's daily price series, from seeded `google_history` and the daily live checks;
  - the route-month's series where a single trip has too little history.
- **Dips:**
  - Find past dips: runs of consecutive days where the price was at least as far below the trailing 30-day median as today's price is.
  - Measure each dip's length in days.
- **Estimate:** the median dip length, capped at the days left before departure.
- **Wording:**
  - median ≤ 7 → **"likely gone within ~N days"**;
  - more → **"likely to hold for a week or more"**;
  - fewer than `DURATION_MIN_DIPS` (2) past dips → **"not enough history yet"**.
- **Storage:** stored per candidate (`expected_days`, null when there isn't enough history), so the site, digest and alerts all read the same value.

### 3.3 Standout ("exceptional") offers (my call on the threshold)
A candidate is **standout** when all of these hold:
- go-now ≥ `STANDOUT_GO_NOW` (85);
- deal level `great`;
- baseline confidence `normal`;
- the price is verified (live);
- expected duration ≤ `STANDOUT_MAX_DAYS` (3) days.

Standout candidates get the louder treatment everywhere they appear: a distinct accent and a "Rare: likely gone within ~N days" label.

### 3.4 Instant alerts
- **When:** right after the daily scan's score stage. A new pipeline stage `alerts` runs last in `scan.yml`, which already has the email secrets.
- **What:** for each user, the best standout candidate of the day that passes the limits, emailed as a short single-trip message in the existing email style. It shows destination, dates, price against typical, go-now, the duration line, View flights, and the snooze links.
  - Subject (my call): "Rare: {destination} {price} ({pct}% below typical) — likely gone within ~{n} days".
- **Limits:** at most **one** instant alert per user per day, and never the same destination for that user within **7 days** (a rolling week). Recorded so re-runs don't resend.
- **The digest still shows it.** An alerted offer still appears in the next Mon/Thu digest if it's still current, marked standout. The alert doesn't count as "sent" for the digest's resend rule.
- **Tuning:** a dry-run or admin-only mode, as the digest has, to inspect candidates without emailing anyone.

### 3.5 Where the new fields show
- **Digest:** each deal shows go-now and the duration line. Standout deals get the louder look, and the lead card is standout when one exists.
- **Site:** the dashboard cards and destination-page rows show the duration line and the standout marker.

---

## 4. Constraints

- **Stack and cost:** Python, Postgres on Neon, the GitHub Actions daily scan, Resend email. Free tiers only.
- **No new external data.** Everything comes from data ptopilot already stores.
- **Look:** the existing design system and email patterns (Plan 7). Email stays inline-styled with no web fonts.
- **Process:** migrations reach Neon before code reading them deploys. Commit and push to `main` at each step. Never print or commit secrets.
- **Delivery:** emails reach only the owner until a Resend domain is verified. That's acceptable for building and tuning.

---

## 5. Left to the builder

- Exact data model: candidate `expected_days`, a standout flag (stored or derived), and an alerts send log.
- The dip-detection details (trailing-median window, how gaps in the series are treated), within §3.2.
- Exact visual treatment of standout offers within the design system (colour from the destination palette or a dedicated accent).
- Whether the tuning mode is a CLI flag on the scan or a separate command.
- How the work splits into plans (probably one plan).
