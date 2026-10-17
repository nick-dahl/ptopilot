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
LIVE_CHECK_CAP = 40
EXPLORATION_QUOTA = 10  # slots reserved for routes with too little history or no cached price
PRIORITY_WEIGHTS = {1: 1.0, 2: 0.8, 3: 0.6}
MONTH_ESTIMATE_WEIGHT = 0.5  # a month's cheapest fare is a weaker signal than a fare for the exact dates
URGENCY = {"soon": 0.7, "sweet": 1.0, "far": 0.5}  # <30 days, 30-120 days, >120 days out
BREAKER_THRESHOLD = 3  # consecutive failures before a live source is skipped for the rest of the run
LIVE_DELAY_S = (3.0, 8.0)  # random pause between live checks
SOURCE_BUDGETS = {"serpapi": {"per_day": 8, "per_month": 250}}  # every attempted call counts
SHORT_HAUL_MAX_MIN = 600  # fastest option under 10 h -> short-haul stop limit applies
MAX_DURATION_RATIO = 1.5
LIVE_HORIZON_DAYS = 300  # Google Flights returns nothing ~10-11 months out; don't spend checks beyond this

# Digest (spec §8)
DIGEST_MAX_DEALS = 8
DIGEST_ALTERNATES_PER_TRACKER = 2
DIGEST_RESEND_FACTOR = 0.95  # a deal already sent is only sent again once it is at least 5% cheaper
TREND_BAND = 0.03  # week-over-week change smaller than this shows as flat
QUIET_DIGEST_WEEKDAY = 0  # Monday: when there are no deals, only this day's digest is sent
