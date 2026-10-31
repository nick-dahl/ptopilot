# ptopilot — Hidden Gems (Design)

**Date:** 2026-10-31
**Status:** Draft, awaiting review
**Builds on:**
- [Site polish](2026-10-30-ptopilot-site-polish-design.md) (Plan 15): design system, input chips, cover photos and the `photos` stage, onboarding.
- [Related destinations](2026-10-25-ptopilot-related-destinations-design.md) (Plan 14): the light live-check pattern and the curated-YAML pattern.

**Backlog:** [`ROADMAP.md`](../../../ROADMAP.md) §1 "Hidden gems".

---

## 1. Intent

**Why.** The owner wants ptopilot to be "the first website I want to go to when I'm daydreaming about how to spend my time off". The core feature hunts bargains on places you already track. Hidden gems is the other half: inspiration. It offers a handful of fun, relatively affordable places you hadn't thought of, written up the way a friend who's been would tell you about them.

**What the owner wants, in their words, condensed:**
- **What a gem is.** Spectacular but not widely known: places friends haven't been to, but might go after you tell them. The touchstones are the Lofoten Islands and Ljubljana. Morocco is another flavor: "a sensational trip that can be carved out by the right adventurous, motivated individual".
- **Affordability is the whole trip, not just the fare.** Lofoten works because free dispersed camping takes lodging off the table, so a backpacking trip is "very manageable cost-wise".
- **Tailored to trip styles.** The profile knows the kinds of trips a person enjoys ("thru-hiking + camping, city hopping, Euro-rail trips, beach bum, etc."), and gems match them.
- **A magazine cadence.** A new gem appears "occasionally"; the page doesn't regenerate every visit.
- **The owner approves every write-up.** Approve, or reject with a note, so the writing learns the owner's style and that draft gets redrafted. The point is to "set the vibe before this becomes a fully incorporated feature".
- **No API for now.** The catalogue is built in working sessions with Claude, and the owner refreshes it on rotation. Automatic drafting via the Claude API may come later if this scales.
- **Live-checked fares** on each gem: "a very useful piece of information".
- **A gem stays in the feed even when its fare is high or no dates fit.** "I'm more interested in showing a handful of fun, relatively affordable destinations… The core feature already focuses on bargain hunting aggressively."

**Approved mockup** (brainstorm session 2026-10-31, `gems.html`):
- a "For you" line with the person's trip styles and an edit link;
- this week's gem as a large feature: cover photo with credit, trip-style tags and best months, the write-up's opening, a "How to do it on a budget" box, and the live fare with route, dates and "checked this morning";
- a fit pill: green "Fits your August range · 6 PTO", orange "outside your dates";
- "Read the full guide" and "Track this place" buttons;
- "Earlier issues" as smaller photo cards.

**Success looks like:**
- Opening ptopilot on a quiet day still gives something to dream about.
- A friend reads a gem and wants to go: the owner's test.
- The owner recognises their own voice in every write-up and never finds a wrong claim in one.

---

## 2. Goals, non-goals, anti-goals

**Goals**
1. **A trip-styles field** on the profile and in onboarding (§3.1).
2. **A gem catalogue** in the repo: write-ups, budget angles, styles and claims, approved by the owner (§3.2).
3. **A session workflow** for drafting, approving and redrafting, with a style guide that accumulates the owner's notes (§3.3).
4. **A per-person feed** that publishes about one new gem a week, matched to trip styles, with an archive (§3.4).
5. **Live-checked fares** per gem and person, with a fit pill (§3.5).
6. **The page**, the full guide page, and "Track this place" (§3.6).

**Non-goals**
- Automatic AI drafting or any paid AI API.
- User-submitted gems, comments or ratings.
- Gems in the email digest (a later idea).
- Booking or lodging search.
- Hiding a gem because of price or dates.

**Anti-goals**
- **A write-up with a confident wrong claim** (camping rules, visa needs, seasons). Every factual claim worth checking is listed and checked before approval.
- **Generic travel-blog filler**, or the same place pitched the same way to everyone.
- **Turning gems into another bargain feed.** They are inspiration first, with the fare as information.
- **Spending the SerpApi allowance** or slowing the core scan.

---

## 3. Decided behaviour

### 3.1 Trip styles (my calls on the list)
- **A new user field:** `trip_styles`, a list from a fixed vocabulary, with labels and emoji in the UI:
  - `hiking_camping` 🥾 Hiking & camping;
  - `city_hopping` 🏙 City hopping;
  - `rail` 🚆 Rail trips;
  - `beach` 🏖 Beach time;
  - `islands` 🏝 Islands;
  - `adventure` 🧭 Road trips & adventure;
  - `food_wine` 🍷 Food & wine;
  - `culture` 🏛 History & culture.
- **Where it's set:**
  - chips, multi-select, in the profile's Travel style section and onboarding step 3 ("How you like to travel");
  - empty means "show me anything".

### 3.2 The catalogue
- **One YAML file per gem**, in `ptopilot/data/gems/` (my call), validated by tests. The owner and Claude edit these in sessions. Fields:
  - `slug`;
  - `name`, `country`;
  - `airports` (where you'd fly in, plus optional `return_airports` for open-jaw);
  - `styles` (from the vocabulary);
  - `best_months`;
  - `headline` (one line);
  - `body` (the full guide, Markdown subset);
  - `budget` (a short "how to do it on a budget" paragraph plus `daily_cost_usd`, a rough integer);
  - `claims` (the factual statements worth checking, each with `source_url` and `checked_on`);
  - `status` (`draft`, `approved` or `retired`);
  - `approved_on`;
  - optional `photo` (a Commons photo picked by hand; otherwise the `photos` stage finds one).
- **Only `approved` gems are ever shown.** `retired` gems leave every feed, but their full-guide page stays reachable for anyone who saw them.
- **Sizing (my call):** start with about 12 approved gems spread across styles, then add a few on each refresh.

### 3.3 The session workflow and style guide
- **Drafting:** in a session, Claude drafts a batch as `draft` files following `docs/gems/style-guide.md`, checking each claim against its source.
- **Review:** the owner approves each draft, or rejects it with a note.
  - **Approved** → `status: approved`, `approved_on` set.
  - **Rejected** → that gem is redrafted in the same session from the note, and the note's lesson is added to the style guide as a short rule or example.
- **The style guide** (`docs/gems/style-guide.md`) holds:
  - the voice: a friend telling you how they did it;
  - the budget-angle rule;
  - per-style emphasis (the same place leads with hiking for a hiker, food for a food lover);
  - banned filler;
  - the claims rule;
  - the owner's accumulated notes.
  - Lofoten and Ljubljana are the first reference examples, written with the owner.
- **Publishing** is a commit and push. No admin UI.
- **A session checklist** (`docs/gems/README.md`) gives the refresh routine: check the stale claims (older than 12 months), retire stale gems, draft new ones, review, push.

### 3.4 The feed (my calls on the rules)
- **Each person has their own publication schedule.** A new `gem_issues` table records `(user_id, gem_slug, published_on)`.
- **Cadence:** on each daily scan, if a person's latest issue is at least `GEM_ISSUE_DAYS` (7) old, the next gem is published to them.
- **Choosing the next gem:**
  - the approved gem not yet published to them that best matches their trip styles, by the number of shared styles, ties broken by catalogue order;
  - **wildcard:** every `GEM_WILDCARD_EVERY` (4th) issue ignores style matching, so the feed isn't an echo chamber;
  - **excluded:** places the person already tracks, by destination code or a shared airport.
- **The first visit** publishes the first issue immediately, so a new user never sees an empty page.
- **When the catalogue runs out** for a person, no new issue is published. The archive remains.
- **Page order:** the newest issue is the feature; "Earlier issues" lists the rest, newest first.

### 3.5 Fares (my calls on the mechanics)
- **Which gems are priced:** each person's newest 4 issues, from their home airports.
- **Finding dates:**
  - candidate dates come from the free Travelpayouts cache, a month scan per gem airport across the person's open ranges and best months, kept round trip only;
  - the trip length is the person's ideal length, else the middle of their min..max.
- **Confirming:**
  - the cheapest candidate per (person, gem) gets one free Google live check;
  - the miserable-flight judge and the person's stop filters apply;
  - SerpApi is never used;
  - checks are capped at `GEM_LIVE_CHECKS_PER_DAY` (8) globally;
  - each (person, gem) is re-checked at most every `GEM_RECHECK_DAYS` (3).
- **Storage:** results go in a `gem_fares` table (user, gem, dates, price, currency, checked_at, fits, PTO cost, deep link).
- **The fit pill:**
  - green "Fits your {Month} range · {n} PTO" when the dates lie inside an open range and the PTO cost fits what's left;
  - orange "outside your dates" otherwise;
  - grey "Checking fares…" before the first check;
  - **grey "No fares found lately" (my call)** when the last check found nothing usable: no cached candidates, an empty live result, or only miserable flights. This is likely for remote places.
  - `gem_fares` keeps a row for such a miss, with a null price and a `status` of `found`, `none` or `failed`, so it is re-checked on the same 3-day rule and not on every scan.
- **The fare always shows when known.** Never hidden for being high.

### 3.6 Pages
- **`/gems`:**
  - the "For you" line, with styles and an edit link to the profile section;
  - this week's feature as in the mockup;
  - "Earlier issues" as photo cards.
  - Linked from the main nav as "Hidden gems".
- **`/gems/{slug}`:** the full guide, with the cover photo and credit, styles and best months, the body, the budget box, the person's fare and fit, a "Facts we checked" list of claims with sources, and the buttons.
- **"Track this place":**
  - adds the gem's place as a destination, in place, through the existing add flow (`add_destination`), with the person's ideal length as the target;
  - once tracked, the button reads "Tracking", linking to the destination page.
  - **Open-jaw gems (my call)** are tracked on their arrival airports only, as an ordinary round-trip destination. Tracking a different return airport would be a feature change to the places code and is out of scope. The gem's own fare check still prices the open-jaw route.
- **Who can open a guide page (my call):**
  - any signed-in user can open `/gems/{slug}` for any **approved** gem, so a friend can be sent a link, which is the owner's whole test;
  - viewing one doesn't add it to their issues;
  - **retired** gems open only for people who were issued them;
  - **drafts** are 404 for everyone.
- **The first issue (my call):** the first visit to `/gems` writes the first issue with an idempotent insert, and the first issue is also written by the scan.
  - Its card shows "Checking fares…" until the next scan prices it.
  - If someone's styles change later, only future issues follow the new styles.
- **Dashboard:** a small "This week's hidden gem" card under the destination cards, linking to `/gems`.
- **Signed-in only**, like the rest of the app.

---

## 4. Constraints

- **Free tiers only:**
  - no paid AI API;
  - no SerpApi for gems;
  - fast-flights live checks capped per day.
- **Daily scan:** the core grid and its timing are unchanged. Gem work is a separate continue-on-failure stage after `related`.
- **Photos:**
  - reuse Plan 15's `photos` stage and `cover()` macro;
  - Commons only, with attribution;
  - gem codes join the places it fills.
- **Look:** Plan 15's design system and components. The mockup is the reference.
- **Process:**
  - migrations reach Neon before code that reads them deploys;
  - commit and push to `main`;
  - never print or commit secrets;
  - the repo is public, so the catalogue and style guide hold nothing personal.

---

## 5. Left to the builder

- The exact Markdown subset for `body` and how it's rendered safely.
- The gem stage's name and where it sits relative to `photos`.
- How a gem's `airports` map to a destination code for "Track this place", using the existing `destination_code` rules.
- The visual details within the mockup.
- **The first catalogue batch is not a build task.** It is written with the owner in a session after the code lands, starting from Lofoten, Ljubljana and Morocco.
