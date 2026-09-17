"""Constants for Fly House."""

from __future__ import annotations

DOMAIN = "fly_house"

CONF_INPUT_ENTITIES = "input_entities"
CONF_OUTPUT_ENTITIES = "output_entities"
CONF_TICK_INTERVAL = "tick_interval"
CONF_INTENSITY = "intensity"
CONF_SEED = "seed"
CONF_WHOLE_HOUSE = "whole_house"

DEFAULT_TICK_INTERVAL = 10
DEFAULT_INTENSITY = 0.55
DEFAULT_SEED = 42
DEFAULT_RESERVOIR_SIZE = 256
MAX_INPUT_ENTITIES = 32
MAX_OUTPUT_ENTITIES = 32

ATTR_SPIKES = "spikes"
ATTR_MODE = "mode"
ATTR_ENERGY = "energy"

MODE_IDLE = "idle"
MODE_WANDER = "wander"
MODE_ESCAPE = "escape"

SERVICE_POKE = "poke"
ATTR_STRENGTH = "strength"
DEFAULT_POKE_STRENGTH = 1.0

PLATFORMS = ["binary_sensor", "sensor"]
