# Adaptive polling: every trip fresh, every day (design)

Date: 2026-11-06. Owner-approved direction in conversation; calls marked *(builder's call: …)* or *(my call)* were made by Claude and are open to the owner's correction.

## Why

ptopilot exists to surface a good fare **when it happens**, even if it lasts a day. Fares jump around day to day, so a trip whose live price is days old is useless for the tool's purpose. The owner's words: "Stale is no good for the tool's purpose."

Two things threaten freshness:

1. **Today, for one person.** The `shortlist` stage picks at most `LIVE_CHECK_CAP = 150` route queries a day for a live Google Flights check (deals first, then exploration). On 2026-11-05 production had 420 route queries for the owner's 5 trackers; 260 depart within `LIVE_HORIZON_DAYS = 300` (Google can price them), and only 146 were live-checked. So ~44% of priceable trips were not live-checked that day.
2. **The beta.** The owner plans a beta of 5–10 people with 4–5 trips each: roughly 25–50 trackers. At today's ratio (~52 in-horizon route queries per tracker) that is ~1,300–2,600 live checks a day before overlap between people. One check takes ~6 s including the random pause (`LIVE_DELAY_S = (3.0, 8.0)`): 146 checks took ~860 s. So the beta needs ~2–4.5 hours of live checking a day, against today's single run with a 50-minute live budget (`LIVE_VERIFY_BUDGET_S`) inside a 75-minute job.

## Goals

- **The freshness promise:** every tracked trip that Google can price (in-horizon route query) gets at least one successful live check every UTC day.
- **Free sources only.** Google Flights via fast-flights stays the live source; SerpApi stays on its existing small budget (8/day, 250/month) for open-jaw and fallbacks.
- **Scale to the beta** (5–10 people, 4–5 trips each) without breaking the promise, by spreading checks over several runs a day.
- **Catch a good day the same day:** every run scores what it checked and can send instant alerts, so a fare found in the afternoon reaches the person that afternoon.
- **Be polite to Google, and notice early when it pushes back.** The health email makes freshness and Google's refusal rate visible every run.
- **Use spare capacity well:** when every trip is fresh and time is left, give a second same-day check to the trips most likely to move into a deal.

## Non-goals

- Paid fare sources (Duffel, Kiwi, a paid SerpApi tier) and monetization. The owner: "Before paying for a service, I'd want to wire it so that I could profit." They are one later, paired project, triggered only if free bandwidth turns out to limit the beta.
- Changing the broad scan (Travelpayouts cached fares), baselines, scoring rules, digest selection, or alert caps.
- Pricing trips beyond `LIVE_HORIZON_DAYS` live (Google returns nothing ~10–11 months out; the cached broad scan keeps covering them).

## Anti-goals (a failure even if it technically works)

- **Checking any in-horizon trip less often than daily** to save time. "Adaptive" here means *more* checks for hot trips, never fewer for quiet ones.
- **A silent miss.** If a trip goes a whole UTC day without a live check, the owner must see it in the health email, plainly.
- **Getting the free source blocked** by hammering it; one blocked day stales everything at once.
- **Repeat or extra alerts** because runs multiplied: the existing per-person limits (`ALERTS_PER_DAY = 1`, the same destination at most once every `ALERT_SAME_DESTINATION_DAYS = 7`) hold across all of a day's runs.

## What exists today (build on it)

- `route_queries` are already de-duplicated and shared across trackers (unique on origin, dest, return airport, depart, return dates). Two friends watching the same trip already share one route query, and so one check.
- `live_checks` records every attempt; `live_verify` already skips route queries checked successfully earlier the same run date, so a same-day re-run is cheap.
- `shortlist` ranks deals (cached price ≤ ~p35 of a confident baseline, by deal strength × urgency × tracker priority) and exploration (thin history, least recently checked), capped at `LIVE_CHECK_CAP`, with `EXPLORATION_QUOTA` reserved.
- The scan workflow (`.github/workflows/scan.yml`) runs once daily at 06:00 UTC with `concurrency: group: scan, cancel-in-progress: false` and `timeout-minutes: 75`; stages run in order (`expand`, `broad_scan`, `shortlist`, `seed_history`, `live_verify`, `baselines`, `score`, `related`, `gems`, `photos`, `alerts`, `prune`). Plan 17 added per-stage durations to the health email and an `interrupted` report for killed runs.
- The digest (Mon/Thu 12:00 UTC) reads the latest scored run date.

## The design

### 1. The shortlist becomes "everything in horizon, in the right order"

The daily live-check list is **every in-horizon route query linked to an active tracker today**, not a capped pick. The cap stops being a selection rule and becomes a per-run work budget (below). The shortlist's job becomes **ordering**:

1. Trips **not yet fresh this UTC day** come first, always.
2. Among those, **the longest-waiting first** (time since the trip's last fresh check; never checked counts as longest). The owner chose this rotation, 2026-11-06: on a day without capacity for every trip, no trip should miss two days in a row, so the miss rotates instead of always landing on the same quiet trips. Within the same staleness (e.g. all checked yesterday), most promising first, using signals the pipeline already has:
   - yesterday's (or today's) cached fare at or below the deal threshold, or a fresh cached dip versus the trip's last live price;
   - the trip's last live price close to a deal threshold (within a margin, *builder's call* on the margin, a config constant);
   - departure soon (the existing `urgency(days_until)`);
   - tracker priority (existing `PRIORITY_WEIGHTS`);
   - routes with thin history (exploration) keep a share, so history keeps building (*builder's call* how this maps from `EXPLORATION_QUOTA`).
3. Trips **already fresh today** are eligible only for a **second check** (section 4), after every not-yet-fresh trip.

**What "fresh" means** *(my call)*: a trip is fresh today when a live source answered for it today — a priced result, or Google's clean "no flights" (`live_checks.ok` true, zero options), or a SerpApi price (from `seed_history` or a fallback). live_verify may still run Google on a SerpApi-priced round trip for the health audit's pairs, as today, but that check doesn't count against freshness. A trip whose Google checks fail for that route alone (route-specific errors, not an outage) on every attempt is **not** counted as a miss in the warning below; it is listed separately as "Google can't price these trips", so the daily warning never fires forever on a handful of routes and stops being read.

Open-jaw route queries stay limited by what SerpApi's budget can still price; they are counted in freshness but a missed open-jaw because the SerpApi budget ran out is reported separately (it is a budget fact, not a capacity failure).

### 2. Several runs a day, each a full pass

- The scan workflow runs **three times a day, about 8 hours apart** *(my call; e.g. 06:00, 14:00, 22:00 UTC; the builder may pick other times if a reason appears)*. Runs stay serialized by the existing `concurrency` group.
- Each run has a **live-check time budget** (the existing `LIVE_VERIFY_BUDGET_S`, possibly retuned *(builder's call)*) and works down the ordered list from section 1, skipping trips already fresh today (the existing same-day skip), until the list is done or the budget is spent.
- **Every run is a full pass:** after `live_verify` it runs `baselines`, `score` and `alerts` on the day's data, so a good fare found by a later run can alert that run. The once-a-day stages that don't need to repeat (*builder's call* which: likely `expand`, `broad_scan`, `seed_history`, `related`, `gems`, `photos`, `prune`) run only on the day's first run, or are cheap and idempotent enough to repeat; the design requires only that repeating them never duplicates work or output (gems publish weekly, photos and prune are idempotent).
- **All runs share one run date** (the UTC day), so a day's candidates, alerts and digest selection behave as today; a later run re-scores the day with more fresh prices. A later run must score every live price of the day, not just its own run's, and must **update the day's candidates in place** (upsert on their existing unique key) rather than delete and rewrite them as `score` does today: a rewrite creates new candidate ids, which loses the `state='sent'` the 12:00 digest set, nulls `alert_sends.candidate_id`, and breaks the digest's links to candidate ids on digest days *(found by the builder check; the mechanism is the builder's call)*.
- The alert caps hold across runs because they are already counted per UTC day and per week from `alert_sends`.
- The digest is unchanged: it reads the latest scored run date, so a Monday digest at 12:00 UTC sees the 06:00 run.

### 3. Capacity math the builder should keep in mind

At ~6 s a check, three runs with a ~50-minute live budget each give ~1,500 checks a day; the beta's upper estimate is ~2,600 before overlap. The design therefore expects the builder to:

- confirm the real per-check time on production and size runs and budgets from it (a config constant per value);
- prefer more runs or longer live budgets over shorter pauses (politeness first);
- keep the job `timeout-minutes` comfortably above the live budget plus the other stages.

If even that cannot keep every trip fresh at the beta's real size, the health email says so (section 5), and that is the signal for the later paid-source-plus-monetization project. This project does not solve that case.

### 4. Second checks with spare capacity

When every in-horizon trip is fresh today and a run still has budget, it spends the rest on **second checks** for the trips most likely to change into a deal, in this order *(my call)*: last live price within the near-threshold margin, then departures soonest, then routes whose recent live prices swing most (volatility from `price_observations`, *builder's call* on the measure and window). A trip gets at most one extra check per run, and a second check never displaces a first check.

### 5. Politeness, back-off and the health email

- Keep the random pause between checks. Add a **soft back-off:** if the share of Google failures or empty answers among a run's recent checks rises above a threshold *(builder's call; config constants)*, the run lengthens its pauses; if it rises further, the run stops live checking early, records why, and leaves the rest to the next run. The existing per-source circuit breaker (`BREAKER_THRESHOLD`) stays as the hard stop.
- The **health email**, per run, gains a freshness block:
  - trips in horizon today, trips fresh today, and trips not yet fresh (after this run);
  - checks this run: first checks, second checks, already fresh (skipped), open-jaw skipped for SerpApi budget;
  - Google's failure and empty-answer rates this run, and whether back-off triggered;
  - on the **day's last run** (or the next day's first run, *builder's call*), a plain warning when any in-horizon trip went the whole previous UTC day without being fresh, with the count and the longest wait, e.g. "12 trips had no live price yesterday (longest: 2 days)". This warning also goes in the subject line. Trips Google can't price, and open-jaw trips out of SerpApi budget, are separate lines, not part of this warning.

## Constraints

- The repo is public: no emails, keys or personal data in code, fixtures or commits.
- Migrations, if any, reach Neon before the code that reads them deploys.
- Free sources only; SerpApi's existing budgets unchanged.
- All tunable numbers (run times excepted) live in `ptopilot/config.py`.
- GitHub Actions: keep `permissions: contents: read`, inputs via env (Plan 17), and the `!success()` interrupted-run step.

## Success looks like

- On production, with only the owner's 5 trackers: every in-horizon trip live-checked every day (today ~146 of 260).
- With the beta's real size: the health email shows "fresh today: N of N" on the day's last run, and Google's failure rate stays near today's.
- No duplicate or extra instant alerts; the digest unchanged in content and timing.

## Left to the builder

Run times; budgets and pause tuning from measured check times; the near-threshold margin, exploration share and volatility measure; which stages repeat on later runs and how; how scoring folds a day's earlier live prices in; the back-off thresholds; the health email's exact wording beyond what is stated above; test strategy (the pipeline's existing fakes for live sources and clocks are the obvious base).
