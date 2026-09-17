"""Constants for Fly House."""

from __future__ import annotations

DOMAIN = "fly_house"

CONF_INPUT_ENTITIES = "input_entities"
CONF_OUTPUT_ENTITIES = "output_entities"
CONF_TICK_INTERVAL = "tick_interval"
CONF_INTENSITY = "intensity"
CONF_SEED = "seed"
CONF_WHOLE_HOUSE = "whole_house"
CONF_CAMERA_ENTITY = "camera_entity"
CONF_VISION_TICK_INTERVAL = "vision_tick_interval"

DEFAULT_TICK_INTERVAL = 10
DEFAULT_INTENSITY = 0.55
DEFAULT_SEED = 42
DEFAULT_RESERVOIR_SIZE = 256
MAX_INPUT_ENTITIES = 32
MAX_OUTPUT_ENTITIES = 32
DEFAULT_VISION_TICK_INTERVAL = 30
OMMATIDIA_GRID_SIZE = 16

ATTR_SPIKES = "spikes"
ATTR_MODE = "mode"
ATTR_ENERGY = "energy"

MODE_IDLE = "idle"
MODE_WANDER = "wander"
MODE_ESCAPE = "escape"

SERVICE_POKE = "poke"
ATTR_STRENGTH = "strength"
DEFAULT_POKE_STRENGTH = 1.0

SERVICE_FEED = "feed"
ATTR_FOOD_TYPE = "food_type"
ATTR_AMOUNT = "amount"
DEFAULT_FEED_AMOUNT = 0.3

ATTR_HUNGER = "hunger"
ATTR_RETINA = "retina"

PLATFORMS = ["binary_sensor", "sensor"]
