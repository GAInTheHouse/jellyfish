"""Simulation-wide constants. Values that are rules of the game live here."""

# --- Ocean geometry -------------------------------------------------------
OCEAN_SIZE = 1000.0  # km, the ocean is an OCEAN_SIZE x OCEAN_SIZE torus
ZONE_RADIUS = 200.0  # km, radius of feeding / breeding / predator zones

# --- Calendar -------------------------------------------------------------
DAYS_PER_YEAR = 360
DAYS_PER_SEASON = 90

# --- Currents (km/day), indexed by Depth value ----------------------------
CURRENT_SPEEDS = (40.0, 20.0, 10.0, 5.0)  # surface, shallow, medium, deep

# --- Life cycle -----------------------------------------------------------
PREDATION_PROBABILITY = 0.05  # chance of being eaten per day started in predator zone
MAX_PREDATOR_OVERLAP = 0.5  # predator zone may cover at most half of another zone
EAT_DAYS_TO_MATURE = 30  # first eating days only grow the jellyfish
EAT_DAYS_PER_OFFSPRING = 10  # eating days (previous summer) per offspring

# --- Parameter bounds / defaults -----------------------------------------
MIN_MEMORY_BYTES = 1
MAX_MEMORY_BYTES = 1024
DEFAULT_MEMORY_BYTES = 8

DEFAULT_LIFETIME_YEARS = 3.0  # S
DEFAULT_INITIAL_JELLYFISH = 10  # J
DEFAULT_DAYS = 10 * DAYS_PER_YEAR  # T
MAX_DAYS = 1000 * DAYS_PER_YEAR

# Safety valve so a very successful strategy can't freeze the class laptop.
DEFAULT_MAX_POPULATION = 2000

EPS = 1e-9
