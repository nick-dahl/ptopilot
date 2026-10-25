# ptopilot Plan 9: Destinations You Control

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A traveler can search any place on the website ("Japan", "Tokyo", "Bermuda", "BDA"), add it with a target number of days away, and remove it again at any time. The next morning's scan tracks it in their open ranges, with seasons from real climate data and travel time from flight distance.

**Architecture:**
- **Airport catalog:** a bundled, filtered airport list from OurAirports. It provides search, nearby airports, coordinates and zones, and replaces the need to hand-edit `geo.yaml`.
- **Added destinations** live in a new `destinations` table, and their season ratings in `destination_seasons`. Ratings are computed once from Open-Meteo climate normals.
- **Merged loaders:** `load_geo(engine)` and `load_seasons(engine)` merge the bundled YAML (which takes precedence) with those tables. Every place that loads geography passes its engine; the web app reloads per request so additions show immediately.
- **Trackers** gain `target_days` (days away). When set, planning searches target ±2 days away and uses the target as the preferred length.

**Tech Stack:** No new dependencies (`httpx` already exists). Data from OurAirports (public domain) and the Open-Meteo climate API (free, no key).

**Spec:** [`docs/superpowers/specs/2026-10-25-ptopilot-year-plan-design.md`](../specs/2026-10-25-ptopilot-year-plan-design.md) §3.1 (days away ±2) and §3.7 (destinations you control). Plans 10 and 11 build the planning year, planner page, booking, fit warnings and combinations on top of this. The "Building price history" card note from §3.7 belongs to Plan 10, together with the planner's trip list.

## Global Constraints

- **Cost:** free services only. The airport catalog is bundled (no runtime download), and Open-Meteo is called once per newly added place, never per scan.
- **Data precedence:** hand-written `geo.yaml` and `seasons.yaml` entries always win over database entries and generated ratings. Zone-pair travel rules in `geo.yaml` win over distance bands.
- **Days away:** with `target_days` set, any trip of `target_days ± TARGET_TOLERANCE_DAYS` (= 2) days away qualifies, never shorter than the route's `min_trip_days`.
- **Removing never deletes history:** a removed destination's tracker is deactivated (`active = False`); price observations, candidates and baselines stay.
- **Scoping:** every web route acts only on the signed-in user's own trackers. Another user's tracker is a 404.
- **Migrations reach Neon before code that reads them deploys** (Render auto-deploys `main`).
- Default `pytest` never touches the network: the climate fetcher and airport download are injectable or run only by scripts.
- `ruff check .` and `ruff format --check .` pass; `PTOPILOT_REQUIRE_DB=1` for database tests.
- Work on `main`; every task ends with a commit and push; the full suite stays green. Commit messages end with a `Co-Authored-By:` line for the model that wrote them. Never print or commit secrets.

## Review Focus

1. **A search that matches nothing, or matches hundreds** ("a", "Airport") → a friendly "No places found", or at most `SEARCH_LIMIT` results with large airports first. Never an error page. *Task 1: `test_search_with_no_match_is_empty`, `test_search_is_capped_and_large_airports_come_first`.*
2. **Open-Meteo is down or slow when a place is added** → the place is still added and tracked. Its seasons fall back to "good" (the existing unknown-rating behavior) and the climate lookup is retried on the next add of that place. *Task 3: `test_adding_works_when_climate_lookup_fails`.*
3. **Re-adding a destination the user removed earlier** → the same tracker comes back (history kept) with the new target, not a duplicate. *Task 3: `test_re_adding_reactivates_the_same_tracker`.*
4. **Adding a place that already exists as a built-in destination** (search "Lisbon" or "Azores") → the built-in code is reused, so its hand-written season and colour apply. *Task 3: `test_adding_a_built_in_place_reuses_its_code`.*
5. **A target too short for a far place** (Japan with a 5-day target) → trips start at the route's minimum length, and the page says so. *Task 4: `test_target_below_the_routes_minimum_starts_at_the_minimum`; Task 5: `test_page_warns_when_a_target_is_shorter_than_the_trip_minimum`.*

---

## File structure

```
scripts/build_airport_data.py           # NEW: OurAirports → ptopilot/data/airports.csv + countries.csv (run by hand)
ptopilot/data/airports.csv              # NEW (generated, committed): scheduled-service airports with IATA codes
ptopilot/data/countries.csv             # NEW (generated, committed): code,name,continent
ptopilot/core/airports.py               # NEW: AirportCatalog (search, nearby, zones, distance)
ptopilot/core/geo.py                    # distance-band travel rules; catalog airports; Destination from rows
ptopilot/core/climate.py                # NEW: monthly climate → season ratings + notes
ptopilot/sources/climate.py             # NEW: Open-Meteo climate fetch (injectable client)
ptopilot/data/__init__.py               # load_geo(engine=None), load_seasons(engine=None)
ptopilot/db/models.py                   # Destination, DestinationSeason models; Tracker.target_days
ptopilot/db/migrations/versions/0006_destinations.py
ptopilot/destinations.py                # NEW: add_destination, remove_destination
ptopilot/core/planner.py, ptopilot/pipeline/expand.py, ptopilot/pipeline/score.py   # target_days
ptopilot/web/app.py, templates/destinations.html, templates/dashboard.html          # the page
ptopilot/pipeline/context.py, ptopilot/digest/__main__.py, ptopilot/profiles.py     # load_geo(engine)
ptopilot/config.py                      # new constants (below)
```

New config constants (exact values):
```python
TARGET_TOLERANCE_DAYS = 2
SEARCH_LIMIT = 12
NEARBY_KM = 100                       # other airports offered with a picked one
CLIMATE_YEARS = (2011, 2020)          # Open-Meteo climate normals period
CLIMATE_MODEL = "EC_Earth3P_HR"
WET_DAY_MM = 1.0
# Season rating from monthly mean daily max temperature (°C) and wet days per month:
SEASON_GOOD = {"tmax_min": 18, "tmax_max": 30, "wet_days_max": 13}
SEASON_AVOID = {"tmax_below": 10, "tmax_above": 34, "wet_days_min": 18}
# Travel overhead by great-circle distance from the origin airport, used where geo.yaml has no zone pair:
DISTANCE_BANDS_KM = [  # (up to km, overhead_days, min_trip_days)
    (1500, 1.0, 3), (4000, 1.5, 4), (7000, 2.0, 5), (10000, 2.5, 7), (float("inf"), 3.0, 9)]
```

---

### Task 1: Airport catalog

**Files:**
- Create: `scripts/build_airport_data.py`, `ptopilot/data/airports.csv`, `ptopilot/data/countries.csv`, `ptopilot/core/airports.py`
- Modify: `ptopilot/config.py`, `pyproject.toml` (package-data: `"ptopilot.data" = ["*.yaml", "*.csv"]`)
- Test: `tests/core/test_airports.py`

**Interfaces:**
- Produces:
  - `CatalogAirport(code: str, name: str, city: str, country: str, continent: str, lat: float, lon: float, size: str)` with `size` one of `"large"`, `"medium"`, `"small"`.
  - `PlaceMatch(airport: CatalogAirport, nearby: tuple[CatalogAirport, ...], country_name: str)`.
  - `AirportCatalog.load() -> AirportCatalog`, cached once per process.
  - `catalog.get(code) -> CatalogAirport | None`.
  - `catalog.search(query: str, limit: int = SEARCH_LIMIT) -> list[PlaceMatch]`.
  - `catalog.nearby(code: str, km: float = NEARBY_KM) -> list[CatalogAirport]`.
  - `distance_km(a: CatalogAirport, b: CatalogAirport) -> float`, great-circle.
  - `zone_for(country: str, continent: str) -> str`.

- [ ] **Step 1: Generate the data files.**
  - Write `scripts/build_airport_data.py`:
    - Download `https://davidmegginson.github.io/ourairports-data/airports.csv` and `countries.csv`.
    - Keep rows with `scheduled_service == "yes"`, a non-empty `iata_code`, and `type` in large/medium/small airport.
    - Write `airports.csv` with columns `code,name,city,country,continent,lat,lon,size`, UTF-8, sorted by code, coordinates to 4 decimals.
    - Write `countries.csv` as `code,name,continent`.
  - Run it: `.venv/Scripts/python scripts/build_airport_data.py`.
  - Expected: about 4,000 airports (3,244 large and medium plus about 764 small, as of 2026-10-25), with HND, NRT, BDA, PDL, FNC, PUQ, OPO, SCQ, JFK and LIS all present.
- [ ] **Step 2: Write the failing tests** in `tests/core/test_airports.py`:

```python
CAT = AirportCatalog.load()

def test_search_by_city_puts_its_airport_first_and_offers_nearby_ones():
    first = CAT.search("Tokyo")[0]
    assert first.airport.code == "HND" and "NRT" in {a.code for a in first.nearby}

def test_search_by_country_lists_its_main_airports():
    codes = [m.airport.code for m in CAT.search("Japan")]
    assert codes and all(CAT.get(c).country == "JP" for c in codes) and {"HND", "NRT"} <= set(codes)

def test_search_by_iata_code_and_island_names():
    assert CAT.search("BDA")[0].airport.code == "BDA"
    assert CAT.search("bermuda")[0].airport.country == "BM"

def test_search_with_no_match_is_empty():
    assert CAT.search("zzqx") == [] and CAT.search("  ") == []

def test_search_is_capped_and_large_airports_come_first():
    results = CAT.search("international")
    assert len(results) == config.SEARCH_LIMIT
    sizes = [m.airport.size for m in results]
    assert sizes == sorted(sizes, key=["large", "medium", "small"].index)

def test_nearby_uses_distance_not_city_names():  # Narita's city is "Narita", not "Tokyo"
    assert "NRT" in {a.code for a in CAT.nearby("HND")}
    assert "KIX" not in {a.code for a in CAT.nearby("HND")}  # Osaka is ~400 km away

def test_distance_and_zones():
    assert 10_700 < distance_km(CAT.get("JFK"), CAT.get("HND")) < 10_950
    assert zone_for("JP", "AS") == "E_ASIA" and zone_for("TH", "AS") == "SE_ASIA"
    assert zone_for("BM", "NA") == "NA" and zone_for("PT", "EU") == "EUROPE"
    assert zone_for("CL", "SA") == "S_AMERICA" and zone_for("ZA", "AF") == "AFRICA"
```

- [ ] **Step 3: Run them.** Run: `.venv/Scripts/python -m pytest -q tests/core/test_airports.py`. Expected: fails on import.
- [ ] **Step 4: Implement `ptopilot/core/airports.py`.**
  - **Search:** lower-case `query.strip()`. An exact IATA code, then city prefix, airport-name word, or country name (via `countries.csv`) count as matches. Rank by match kind (code > city > country > name), then size, then name.
  - **Nearby:** other catalog airports within `km` in the same country, sorted by distance.
  - **Zones:** `E_ASIA` = JP, KR, CN, TW, HK, MO, MN. The rest of Asia is `SE_ASIA`. Otherwise map continents EU → EUROPE, NA → NA, SA → S_AMERICA, AF → AFRICA, OC → OCEANIA.
- [ ] **Step 5: Run the tests.** Expected: 7 pass. Then run the full suite and ruff.
- [ ] **Step 6: Commit and push** (`feat(geo): bundled airport catalog with place search`).

---

### Task 2: Distance-based travel rules and climate-based seasons

**Files:**
- Modify: `ptopilot/core/geo.py`, `ptopilot/config.py`
- Create: `ptopilot/core/climate.py`, `ptopilot/sources/climate.py`, `tests/sources/fixtures/real_open_meteo_tokyo_2011_2020.json`
- Test: `tests/core/test_travel_by_distance.py`, `tests/core/test_climate.py`

**Interfaces:**
- Consumes: Task 1 `AirportCatalog`, `distance_km`.
- Produces:
  - `Geo.travel_rule(origin, dest)` keeps zone pairs first. Otherwise it uses `DISTANCE_BANDS_KM` on the distance from the origin airport to the destination's first airport. If either airport lacks coordinates, it falls back to the existing default rule.
  - `Geo.from_dict(data, catalog: AirportCatalog | None = None)`: airports not in `geo.yaml` resolve through the catalog.
  - `MonthlyClimate(tmax_mean: float, wet_days: float)`.
  - `monthly_climate(payload: dict) -> list[MonthlyClimate]` (12 items).
  - `rate_months(climate: list[MonthlyClimate]) -> tuple[list[Rating], dict[int, str]]`.
  - `fetch_climate(lat: float, lon: float, client: httpx.Client | None = None) -> dict`, which raises `SourceUnavailable` on failure.

- [ ] **Step 1: Record the fixture**, one real call:

```bash
.venv/Scripts/python -c "import httpx,json;r=httpx.get('https://climate-api.open-meteo.com/v1/climate',params=dict(latitude=35.55,longitude=139.79,start_date='2011-01-01',end_date='2020-12-31',models='EC_Earth3P_HR',daily='temperature_2m_max,precipitation_sum'),timeout=60);open('tests/sources/fixtures/real_open_meteo_tokyo_2011_2020.json','w').write(r.text)"
```

Expected: about 84 KB, with `daily.time` running from 2011-01-01.

- [ ] **Step 2: Write the failing tests.**

```python
# tests/core/test_travel_by_distance.py
GEO = Geo.from_dict(yaml.safe_load((DATA_DIR / "geo.yaml").read_text()), AirportCatalog.load())

def test_a_zone_pair_in_geo_yaml_still_wins():
    tokyo = destination_at("HND")  # helper: Destination built from catalog airport HND
    assert GEO.travel_rule("JFK", tokyo) == TravelRule(2.5, 7)  # the NA–E_ASIA pair

def test_without_a_zone_pair_distance_decides():
    cape_town = destination_at("CPT")   # NA–AFRICA has no pair; JFK–CPT ≈ 12,600 km
    assert GEO.travel_rule("JFK", cape_town) == TravelRule(3.0, 9)
    lima = destination_at("LIM")        # NA–S_AMERICA pair exists → (3, 9) as before
    assert GEO.travel_rule("JFK", lima) == TravelRule(3.0, 9)

def test_catalog_airports_resolve_even_when_not_in_geo_yaml():
    assert GEO.airport("BDA").country == "BM"
```

```python
# tests/core/test_climate.py
TOKYO = json.loads((FIXTURES / "real_open_meteo_tokyo_2011_2020.json").read_text())

def test_monthly_climate_from_the_real_tokyo_record():
    months = monthly_climate(TOKYO)
    assert len(months) == 12
    assert 7 < months[0].tmax_mean < 10 and 27 < months[7].tmax_mean < 31  # Jan cold, Aug hot

def test_rating_rules():
    ratings, notes = rate_months(monthly_climate(TOKYO))
    assert ratings[0] == "avoid"          # January, ~8 °C max
    assert ratings[4] == "good"           # May, ~21 °C, ~11 wet days
    assert ratings[9] == "good"           # October, ~21 °C, ~12.5 wet days
    assert ratings[5] == "shoulder"       # June, ~24 °C but ~16 wet days
    assert ratings[3] == "shoulder"       # April, ~17 °C
    assert notes[1] == "~8°C, 6 wet days" # format: "~{tmax:.0f}°C, {wet:.0f} wet days"

def test_fetch_failures_are_source_unavailable():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(SourceUnavailable):
        fetch_climate(35.5, 139.8, client)
```

- [ ] **Step 3: Run them.** Expected: they fail.
- [ ] **Step 4: Implement.**
  - **Rating rules:**
    - `avoid` if `tmax < SEASON_AVOID.tmax_below`, `tmax > tmax_above`, or `wet_days >= wet_days_min`.
    - Otherwise `good` if `SEASON_GOOD.tmax_min <= tmax <= tmax_max` and `wet_days <= wet_days_max`.
    - Otherwise `shoulder`.
  - **Wet days:** days with precipitation ≥ `WET_DAY_MM`, averaged per year.
- [ ] **Step 5: Run the tests**, then the full suite and ruff. Commit and push (`feat(geo): distance-based travel rules and climate-based seasons`).

---

### Task 3: Destinations in the database; add and remove

**Files:**
- Create: `ptopilot/db/migrations/versions/0006_destinations.py`, `ptopilot/destinations.py`
- Modify: `ptopilot/db/models.py`, `ptopilot/data/__init__.py`, `ptopilot/core/seasons.py` (merge helper)
- Test: `tests/test_destinations.py`

**Interfaces:**
- Consumes: Task 1 catalog and `PlaceMatch`; Task 2 `fetch_climate`, `monthly_climate`, `rate_months`.
- Produces:
  - **Models:**
    - `Destination(code: str(32) PK, name, kind ("city"|"region"|"route"), airports: text[], return_airports: text[] default {}, color: str|None, added_by: users.id|None, created_at)`.
    - `DestinationSeason(code PK FK destinations.code, months: text[12], notes: JSONB, source: str, computed_at)`.
    - `Tracker.target_days: SmallInteger | None`, check `target_days IS NULL OR target_days BETWEEN 2 AND 60`.
  - **Migration 0006** creates the two tables and adds `trackers.target_days`, with a downgrade.
  - `load_geo(engine: Engine | None = None) -> Geo`: YAML, catalog, then DB destinations. YAML codes win.
  - `load_seasons(engine: Engine | None = None) -> SeasonTable`: YAML, then DB seasons. YAML codes win.
  - `add_destination(s: Session, user: User, match: PlaceMatch, airports: list[str], target_days: int, name: str | None = None, climate: Callable[[float, float], dict] = fetch_climate) -> Tracker`.
  - `remove_destination(s: Session, user: User, tracker_id: int) -> bool`, which returns False for another user's or a missing tracker.
  - `destination_code(match: PlaceMatch) -> str`: `f"{match.airport.code}_{match.airport.country}"` (e.g. `HND_JP`), unless a built-in or DB destination already uses exactly these airports, in which case its code.

- [ ] **Step 1: Write the failing tests** (`tests/test_destinations.py`, using the `session` and `clean_engine` fixtures and a fake climate function returning the Tokyo fixture payload):

```python
def test_adding_tokyo_creates_the_place_its_seasons_and_a_tracker(session):
    user = make_user(session)
    t = add_destination(session, user, CAT.search("Tokyo")[0], ["HND", "NRT"], 12, climate=tokyo_climate)
    assert (t.destination_code, t.target_days, t.active) == ("HND_JP", 12, True)
    d = session.get(Destination, "HND_JP")
    assert (d.name, d.airports, d.added_by) == ("Tokyo", ["HND", "NRT"], user.id)
    assert session.get(DestinationSeason, "HND_JP").months[0] == "avoid"

def test_added_places_load_into_geo_and_seasons(clean_engine): ...
    # after add + commit: load_geo(clean_engine).destination("HND_JP").airports == ("HND", "NRT")
    # load_seasons(clean_engine).rating(("HND_JP", "JP"), 5) == "good"

def test_adding_a_built_in_place_reuses_its_code(session):
    t = add_destination(session, make_user(session), CAT.search("Ponta Delgada")[0], ["PDL"], 9,
                        climate=fail_if_called)
    assert t.destination_code == "AZORES"   # geo.yaml's code; no climate call, seasons.yaml applies

def test_re_adding_reactivates_the_same_tracker(session):
    user = make_user(session)
    first = add_destination(session, user, CAT.search("Tokyo")[0], ["HND"], 12, climate=tokyo_climate)
    assert remove_destination(session, user, first.id) and not first.active
    again = add_destination(session, user, CAT.search("Tokyo")[0], ["HND"], 14, climate=fail_if_called)
    assert again.id == first.id and again.active and again.target_days == 14

def test_adding_works_when_climate_lookup_fails(session):
    t = add_destination(session, make_user(session), CAT.search("Bermuda")[0], ["BDA"], 5, climate=raising)
    assert t.active and session.get(DestinationSeason, t.destination_code) is None

def test_removing_someone_elses_or_a_missing_tracker_does_nothing(session): ...
    # remove_destination(session, other_user, t.id) is False and t.active stays True; missing id → False

def test_target_days_must_be_between_2_and_60(session):  # DB check constraint → IntegrityError for 1 and 61
```

- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement** the models, migration 0006, the loaders and the service.
  - A destination's tracker defaults to priority 2, with `min_stay_days`/`max_stay_days` set to `max(target_days - 2 - 1, 1)` and `target_days + 2`. Those fields stay required by the schema, and planning ignores them when `target_days` is set (Task 4).
  - Seasons are generated only when neither `seasons.yaml` nor `destination_seasons` already has the code.
- [ ] **Step 4: Run the tests**, then the full suite (the migration test must pass) and ruff.
- [ ] **Step 5: Before pushing, migrate Neon.** Same guarded PowerShell snippet as Plan 7 Task 2: read `DATABASE_URL_UNPOOLED` from `.env.local` without printing it, throw if it's empty, run `alembic upgrade head`, remove the variable. Expected: `Running upgrade 0005 -> 0006`.
- [ ] **Step 6: Commit and push** (`feat: destinations in the database; add and remove`).

---

### Task 4: Plan with the target, ±2 days

**Files:**
- Modify: `ptopilot/core/planner.py`, `ptopilot/pipeline/expand.py`, `ptopilot/pipeline/score.py`
- Test: `tests/pipeline/test_target_days.py`

**Interfaces:**
- Consumes: Task 3 `Tracker.target_days`.
- Produces:
  - `TrackerSpec.target_days: int | None = None`.
  - With `target_days` set, `plan_itineraries` uses days-away limits `max(rule.min_trip_days, target - TARGET_TOLERANCE_DAYS)` .. `target + TARGET_TOLERANCE_DAYS`, sets ground-day limits to `0..target + tolerance`, and passes `ideal_days=target` to `select_top`.
  - `score` uses `length_fit(link.days_away, tracker.target_days or user.ideal_trip_days)`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_target_of_11_plans_only_9_to_13_days_away(make_ctx):
    # LIS tracker with target_days=11, June window → every planned link has 9 <= days_away <= 13
def test_target_below_the_routes_minimum_starts_at_the_minimum():
    # plan_itineraries for a JFK user, an E_ASIA destination (min_trip_days 7), target 5 → all >= 7
def test_without_a_target_planning_is_unchanged(make_ctx):
    # the existing stay-range behaviour: same links as before for a tracker with target_days None
def test_go_now_prefers_the_trackers_target_over_the_users_ideal(make_ctx):
    # user ideal 15, tracker target 9; the 9-day trip scores higher than with the user's ideal
```

- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(pipeline): plan each destination around its target length`).

---

### Task 5: The destinations page

**Files:**
- Create: `ptopilot/web/templates/destinations.html`
- Modify: `ptopilot/web/app.py`, `ptopilot/web/templates/dashboard.html` (a "Manage destinations" link in the page head), `ptopilot/web/templates/base.html` (nav item "Destinations")
- Test: `tests/web/test_destinations_page.py`

**Interfaces:**
- Consumes: Task 1 `catalog.search`; Task 3 `add_destination`, `remove_destination`, `load_geo(engine)`; Task 2 `Geo.travel_rule`.
- Produces:
  - `GET /destinations?q=` shows your destinations (colour, name, target days, Remove) and a search form. With `q`, it adds result rows, each with its airport and nearby airports as checkboxes (the picked one checked), a days-away field (default 10), and Add.
  - `POST /destinations` takes form fields `code`, `airports` (repeated) and `target_days`, then 303 to `/destinations`.
  - `POST /destinations/{tracker_id}/remove` → 303 to `/destinations`.
  - `create_app(..., climate=fetch_climate)` is injectable for tests.
  - The app now calls `load_geo(engine)` and `load_seasons(engine)` per request instead of once at start-up. The YAML and catalog parts are cached; only the small DB query runs each time.

- [ ] **Step 1: Write the failing tests.**

```python
def test_signed_out_visitors_go_home(client):  # GET /destinations → 303 "/"
def test_searching_shows_places_with_nearby_airports(client, emailer, clean_engine):
    # GET /destinations?q=Tokyo → "Tokyo" and checkbox values HND (checked) and NRT
def test_a_search_with_no_results_says_so(...):  # q=zzqx → "No places found"
def test_adding_tokyo_tracks_it_and_shows_it(...):
    # POST code=HND, airports=[HND, NRT], target_days=12 → 303; page lists "Tokyo · 12 days away"
    # and the tracker exists with target_days 12 (fake climate injected)
def test_removing_a_destination(...):  # POST /destinations/{id}/remove → gone from the list, tracker inactive
def test_cannot_remove_someone_elses_destination(...):  # → 404, tracker still active
def test_bad_target_is_explained_on_the_page(...):  # target_days=1 or 61 → 400 with "between 2 and 60"
def test_page_warns_when_a_target_is_shorter_than_the_trip_minimum(...):
    # JFK user adds Tokyo with target 5 → list row says "Trips here start at 7 days away"
def test_the_dashboard_links_to_destinations(...):  # 'href="/destinations"' on "/"
```

- [ ] **Step 2: Run them** (they fail). **Step 3: Implement.** Use the existing design system (panels, `field` macro, buttons) with no inline fixed styles (the Plan 7 polish test enforces this). **Step 4: Run the tests**, the full suite and ruff. **Step 5: Commit and push** (`feat(web): add and remove destinations from the website`).

---

### Task 6: Every loader sees added places; end-to-end

**Files:**
- Modify: `ptopilot/pipeline/context.py` (`load_geo(engine)`, `load_seasons(engine)`), `ptopilot/digest/__main__.py`, `ptopilot/profiles.py` (the `load` command validates against `load_geo(engine)`), `ROADMAP.md` (mark "your own destinations" done under the year-plan item)
- Test: `tests/pipeline/test_added_destination_end_to_end.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_a_destination_added_on_the_website_is_planned_scanned_and_dated_by_its_climate(clean_engine):
    # add Tokyo (HND) for a JFK user with an October window via add_destination(fake climate);
    # build a RunContext the way build_context does (load_geo/load_seasons with the engine);
    # expand.run → route queries JFK→HND exist with 10–14 days away for target 12;
    # their links' season_rating comes from the generated ratings (October "good")
```

- [ ] **Step 2: Run it** (it fails: the context still loads YAML only). **Step 3: Implement.** **Step 4: Run the test**, the full suite and ruff. **Step 5: Commit and push** (`feat: added destinations reach the scan, digest and profile loader`).

- [ ] **Step 6: Live check (controller).** Once Render deploys:
  - On the live site, search "Tokyo" and confirm results show.
  - Add it, then remove it again unless the user wants Japan tracked.
  - The next morning's scan must stay green.
