"""Tunable thresholds and weights. Change behavior here, not in the logic modules."""

# Itinerary pruning
TOP_SHAPES_PER_WINDOW = 6
MAX_SHAPES_PER_LENGTH = 2
WINDOW_SLACK_DAYS = 2

# Baselines
COLD_START_N = 15
MAD_TO_SIGMA = 1.4826
SIGMA_FLOOR_FRACTION = 0.03

# Deal levels (z-score thresholds, inclusive)
GOOD_DEAL_Z = -1.0
GREAT_DEAL_Z = -1.5

# Go-now score
GO_NOW_WEIGHTS = {"deal": 0.5, "weather": 0.2, "efficiency": 0.2, "timing": 0.1}
DEAL_Z_FOR_FULL_SCORE = 2.5
WEATHER_SCORES = {"good": 1.0, "shoulder": 0.6, "avoid": 0.2}
SWEET_SPOT_DAYS = {"international": (30, 120), "domestic": (21, 90)}
OFF_SWEET_SPOT_TIMING = 0.5
