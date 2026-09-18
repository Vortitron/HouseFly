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

DEFAULT_TICK_INTERVAL = 2
DEFAULT_HOURLY_BUDGET = 30
MAX_INPUT_ENTITIES = 64
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
