"""Tunable thresholds and weights. Change behavior here, not in the logic modules."""

# Itinerary pruning
TOP_SHAPES_PER_WINDOW = 8
MAX_SHAPES_PER_LENGTH = 3
MAX_SHAPES_PER_WEEK = 2  # spread picks across the window instead of bunching at its start
WINDOW_SLACK_DAYS = 2

# Baselines
COLD_START_N = 15
MAD_TO_SIGMA = 1.4826
SIGMA_FLOOR_FRACTION = 0.03

# Deal levels (z-score thresholds, inclusive)
GOOD_DEAL_Z = -1.0
GREAT_DEAL_Z = -1.5

# Go-now score
GO_NOW_WEIGHTS = {"deal": 0.5, "weather": 0.2, "efficiency": 0.15, "length": 0.1, "timing": 0.05}
DEAL_Z_FOR_FULL_SCORE = 2.5
WEATHER_SCORES = {"good": 1.0, "shoulder": 0.6, "avoid": 0.2}
SWEET_SPOT_DAYS = {"international": (30, 120), "domestic": (21, 90)}
OFF_SWEET_SPOT_TIMING = 0.5
# Preferred trip length (V2): fit fades from 1 at the ideal to 0 this many days away from it.
LENGTH_FIT_SPAN = 4
LENGTH_SELECTION_BONUS = 0.25  # selection ranks by efficiency x (1 + bonus x fit)

# Pipeline (spec §7)
DEFAULT_CURRENCY = "USD"
CACHE_LOOKBACK_DAYS = 7  # cached fares older than this are ignored
BASELINE_WINDOW_DAYS = 60
SHORTLIST_Z = -0.385  # z at the 35th percentile of a normal distribution
LIVE_CHECK_CAP = 150  # a safety ceiling: every in-range route is checked daily (~70-140 for one traveler)
EXPLORATION_QUOTA = 10  # slots reserved for routes with too little history or no cached price
PRIORITY_WEIGHTS = {1: 1.0, 2: 0.8, 3: 0.6}
MONTH_ESTIMATE_WEIGHT = 0.5  # a month's cheapest fare is a weaker signal than a fare for the exact dates
URGENCY = {"soon": 0.7, "sweet": 1.0, "far": 0.5}  # <30 days, 30-120 days, >120 days out
BREAKER_THRESHOLD = 3  # consecutive failures before a live source is skipped for the rest of the run
LIVE_DELAY_S = (3.0, 8.0)  # random pause between live checks
SOURCE_BUDGETS = {"serpapi": {"per_day": 8, "per_month": 250}}  # every attempted call counts
SHORT_HAUL_MAX_MIN = 600  # fastest option under 10 h -> short-haul stop limit applies
# Miserable itineraries (Plan 12): problems, and what forgives them.
MISERY_LAYOVER_MODERATE_MIN = 300  # longest layover > 5h is moderate
MISERY_LAYOVER_SEVERE_MIN = 540  # > 9h is severe
MISERY_DURATION_MODERATE = 1.4  # total travel >= 1.4x the fastest is moderate
MISERY_DURATION_SEVERE = 2.0  # >= 2x is severe
MISERY_GROUND_MODERATE_MIN = 60  # ground time >= 1h is moderate
MISERY_GROUND_SEVERE_MIN = 120  # >= 2h is severe
GROUND_KM_PER_HOUR = 65
MISERY_FORGIVE_PCT = 40  # price <= 0.6 x the normal-confidence baseline median forgives ONE moderate problem
RETURN_CHECKS_PER_DAY = 3
# A source failing this many routes route-specifically with no success in the run has likely changed
# format everywhere: stop using it for the rest of the run.
ROUTE_FAILURE_LIMIT = 8
LIVE_VERIFY_BUDGET_S = 50 * 60  # stop starting live checks after this long so later stages still run
LIVE_HORIZON_DAYS = 300  # Google Flights returns nothing ~10-11 months out; don't spend checks beyond this
# History seeding (V2): Google's own daily prices from SerpApi round-trip results seed baselines.
HISTORY_SOURCE = "google_history"  # observations source for those points; never a price shown to users
SEED_RESERVE_FOR_OPEN_JAW = 2  # SerpApi calls per day seeding leaves for open-jaw routes
SEED_RETRY_DAYS = 30  # a key whose SerpApi result had no history is tried again after this many days
# A baseline where one trip supplies more than this share of the points (typically a seeded trip's history)
# measures that trip's price over time, not the spread across trips: give it a wider sigma floor.
SINGLE_TRIP_SHARE = 0.5
SINGLE_TRIP_SIGMA_FLOOR_FRACTION = 0.08
AUDIT_EQUAL_USD = 5  # fast-flights vs SerpApi prices this close count as equal in the health audit
AUDIT_DAYS = 30  # the health audit's longer view covers this many run dates

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
MIN_TREND_POINTS = 3  # the destination page draws a price trend from this many scan days
DIGEST_WEEKDAYS = (0, 3)  # Monday, Thursday: must match the cron in .github/workflows/digest.yml
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent

# Destinations you control (Plan 9)
TARGET_TOLERANCE_DAYS = 2
SEARCH_LIMIT = 12
NEARBY_KM = 100  # other airports offered with a picked one
CLIMATE_YEARS = (2011, 2020)  # Open-Meteo climate normals period
CLIMATE_MODEL = "EC_Earth3P_HR"
CLIMATE_TIMEOUT_S = 10  # a slow Open-Meteo must not hold a request (or a transaction) for long
WET_DAY_MM = 1.0
SEASON_GOOD = {"tmax_min": 18, "tmax_max": 30, "wet_days_max": 13}
SEASON_AVOID = {"tmax_below": 10, "tmax_above": 34, "wet_days_min": 18}
DISTANCE_BANDS_KM = [  # (up to km, overhead_days, min_trip_days)
    (1500, 1.0, 3),
    (4000, 1.5, 4),
    (7000, 2.0, 5),
    (10000, 2.5, 7),
    (float("inf"), 3.0, 9),
]

# Planning year (Plan 10)
PLAN_YEARS_AHEAD = 1  # a new planning year may be this year or up to 1 year ahead
PLAN_NEXT_YEAR_FROM_MONTH = 10  # from October on, "Start planning" defaults to next year
MAX_PTO_DAYS = 365
MAX_BOOKED_DAYS = 60  # a booked trip may span at most this many days
EXTRA_RANGE_ROWS = 2  # blank range rows on the no-JavaScript form

# Combinations (Plan 11)
COMBO_MIN_PCT_BELOW = 20  # a leg must be at least this far below its typical price
COMBO_MIN_LEGS = 2
COMBO_MAX_SHOWN = 3
COMBO_LEGS_PER_TRACKER = 5  # best eligible offers per destination considered by the search
COMBO_MAX_TRACKERS = 12  # destinations searched: those whose best eligible offer saves the most

# Buy now or wait (Plan 13)
TRIP_HISTORY_MIN = 10  # daily points for the exact trip before its own history is judged
DURATION_MIN_DIPS = 2  # past dips needed to estimate how long a deal lasts
DURATION_WINDOW_DAYS = 30
DURATION_LONG_DAYS = 7
STANDOUT_GO_NOW = 85
STANDOUT_MAX_DAYS = 3
ALERTS_PER_DAY = 1  # instant alerts per user per UTC day
ALERT_SAME_DESTINATION_DAYS = 7
