# Hidden gems: the style guide

Every gem is a place friends haven't been to, but might go after you tell them about it: spectacular,
not widely known, and doable on a sensible budget. This guide is how a gem gets written. Drafts follow
it; the owner's notes at the bottom refine it, session by session.

Reference examples: Lofoten and Ljubljana, the owner's touchstones, are to be added in the first
session, written with the owner.

## The voice: a friend telling you how they did it

- Write like someone who has been, telling a friend over a drink how to pull it off: specific,
  practical, a little excited, never a brochure.
- Second person and concrete: "take the morning ferry to Moskenes", not "visitors can enjoy ferry
  connections".
- Lead with the moment that makes the place worth the flight, then get straight to how to do it.
- Name real things: the trail, the train line, the dish, the campsite, the month the light is best.
- Honest about the catch (the weather turns, the bus runs twice a day, August is busy). A friend
  would tell you.
- Short paragraphs. The headline is one line a friend would actually say.

## The budget angle: the whole trip, not the fare

- Affordability is the whole trip: getting there, sleeping, getting around, eating.
- When free or cheap lodging exists, name it: free wild camping, mountain huts, hostels, guesthouses,
  night trains that double as a bed. This is often the whole reason a place is a gem.
- Say where the money goes and how to keep it down (a rail pass, a shared car, supermarket lunches).
- `budget` is a short "how to do it on a budget" paragraph. `daily_cost_usd` is a rough, honest
  integer for one person on the ground, excluding flights, for the trip the write-up describes.

## Per-style emphasis

The same place leads differently depending on whom it is for. Tag every style that genuinely fits
(`styles`), and let the opening lean towards the first one.

- **Hiking & camping** (`hiking_camping`): the route, its length and difficulty, where you can camp
  and the rules, water and resupply, the season the trails are open.
- **City hopping** (`city_hopping`): which cities pair up, how long in each, how you get between
  them, the neighbourhood to stay in.
- **Rail trips** (`rail`): the line, the journey time, the view side of the train, passes or cheap
  tickets, night trains.
- **Beach time** (`beach`): which beach and why, the water temperature and season, where to stay
  within walking distance.
- **Islands** (`islands`): the ferries and how often they run, island-hopping order, what each
  island is for.
- **Road trips & adventure** (`adventure`): the route, the car or bike, the roads to be careful
  on, what you need to be self-sufficient.
- **Food & wine** (`food_wine`): the dishes and where to eat them, the wine region, market days,
  what it costs.
- **History & culture** (`culture`): the sites worth the detour, the story in one or two lines,
  the festival or season that brings it alive.

## Banned filler

Never use these, or anything like them: "hidden gem", "nestled", "breathtaking", "bucket list".
Also out: "off the beaten path", "something for everyone", "a feast for the senses", "paradise",
"must-see". If a word could describe anywhere, it doesn't describe this place.

## The claims rule

- Every checkable fact in `headline`, `body` or `budget` (a rule, a price, a timetable, a season, a
  distance, an opening date) is listed under `claims` with a `source_url` (http or https) and the
  `checked_on` date it was confirmed against that source.
- Prefer official sources: the park authority, the rail operator, the tourist board, the law.
- A claim you can't source doesn't go in the write-up.
- Claims older than 12 months are stale: `python -m ptopilot.gems check` lists them, and the
  session re-checks or retires the gem.

## Format notes

- One file per gem, `ptopilot/data/gems/{slug}.yaml`; the slug is lowercase words joined by hyphens.
- `country` is the ISO code; quote it (`"NO"` is Norway, a bare `NO` is YAML for false).
- `body` uses a small Markdown subset: paragraphs, `**bold**`, `*italic*`, `[text](https://...)`
  links, `- ` bullet lists and `## ` subheadings. Anything else shows as plain text.
- A `photo` block is optional; if given, it follows the built-in photo rules (a Wikimedia Commons
  file, a free licence, `source_url` the Commons file page). Otherwise the photos stage finds one.
- Nothing personal: the repo is public.

## Notes from the owner

Each session appends the lesson from every rejected draft here, as a short rule or example.
