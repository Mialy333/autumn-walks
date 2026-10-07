"""Settings for the walk planner."""

# Used when the question gives no coordinates. A public landmark.
DEFAULT_START_NAME = "Opéra Garnier"
DEFAULT_START = (48.8719, 2.3316)

SEARCH_RADIUS_M = 2000
MAX_LOOP_M = 4000  # straight-line length of the loop
DETOUR_FACTOR = 1.3  # real streets vs straight lines, for the walking time
WALK_M_PER_MIN = 80  # 4.8 km/h
