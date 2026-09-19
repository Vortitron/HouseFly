"""Constants for HouseFly."""

from __future__ import annotations

DOMAIN = "fly_house"

# --- configuration keys --------------------------------------------------
CONF_INPUT_ENTITIES = "input_entities"
CONF_OUTPUT_ENTITIES = "output_entities"
CONF_TICK_INTERVAL = "tick_interval"
CONF_ACTUATION_ENABLED = "actuation_enabled"
CONF_HOURLY_BUDGET = "hourly_budget"
CONF_QUIET_HOURS_START = "quiet_hours_start"
CONF_QUIET_HOURS_END = "quiet_hours_end"
CONF_APPROACH_ENTITIES = "approach_entities"

DEFAULT_TICK_INTERVAL = 2
DEFAULT_HOURLY_BUDGET = 30
CONF_WATCH_WHOLE_HOUSE = "watch_whole_house"

# Domains worth smelling when watching the whole house. Deliberately narrow:
# these are things whose state says something about the house, as opposed to
# things that describe Home Assistant itself.
#
# Excluded on purpose -- automation, script, scene, update, persistent_notification,
# tag, zone, todo, conversation: they change when *you* change the system, not
# when the house changes, so they would make every upgrade look like an intruder.
WATCHABLE_DOMAINS = (
    "sensor", "binary_sensor", "light", "switch", "climate", "cover", "lock",
    "fan", "media_player", "person", "device_tracker", "input_boolean",
    "input_number", "humidifier", "water_heater", "vacuum", "valve", "sun",
)

# How many entities the whole-house mode will watch. Well above the 64 a person
# would pick by hand, because novelty detection gets better with breadth, and
# capped because the antennal lobe has 131 glomeruli: past that, entities share
# channels and two rooms start smelling the same. tools/validate.py measures
# that collision rate rather than assuming it away.
MAX_WATCHED_ENTITIES = 250

MAX_INPUT_ENTITIES = 64
MAX_APPROACH_ENTITIES = 8
MAX_OUTPUT_ENTITIES = 16

# Actuation is off until someone deliberately turns it on. A fresh install
# watches the house and walks around the dashboard; it touches nothing.
DEFAULT_ACTUATION_ENABLED = False

# --- behavioural modes ---------------------------------------------------
MODE_SLEEP = "sleep"
MODE_GROOM = "groom"
MODE_WALK = "walk"
MODE_FORAGE = "forage"
MODE_ESCAPE = "escape"

# --- services ------------------------------------------------------------
SERVICE_LOOM = "loom"
SERVICE_FEED = "feed"
SERVICE_RESET_MEMORY = "reset_memory"

ATTR_STRENGTH = "strength"
ATTR_AMOUNT = "amount"

DEFAULT_LOOM_STRENGTH = 1.2
DEFAULT_FEED_AMOUNT = 1.0

PLATFORMS = ["binary_sensor", "sensor"]
