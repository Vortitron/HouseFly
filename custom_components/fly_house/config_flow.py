"""Config flow for HouseFly.

Outputs are vetted here rather than at runtime, so that a choice the fly is
never going to be allowed to act on is refused while the person is still
looking at the screen and can pick something else.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ACTUATION_ENABLED,
    CONF_APPROACH_ENTITIES,
    CONF_LIGHT_ENTITIES,
    CONF_CLOCK_OFFSET,
    CONF_NAME,
    CONF_HOURLY_BUDGET,
    CONF_INPUT_ENTITIES,
    CONF_OUTPUT_ENTITIES,
    CONF_QUIET_HOURS_END,
    CONF_QUIET_HOURS_START,
    CONF_TICK_INTERVAL,
    CONF_WATCH_WHOLE_HOUSE,
    DEFAULT_ACTUATION_ENABLED,
    DEFAULT_HOURLY_BUDGET,
    DEFAULT_TICK_INTERVAL,
    DOMAIN,
    MAX_APPROACH_ENTITIES,
    MAX_INPUT_ENTITIES,
    MAX_OUTPUT_ENTITIES,
)
from .safety import ALLOWED_DOMAINS, ActuationGovernor


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        # A house can hold more than one fly, so they need telling apart. The
        # name becomes the device name, and therefore the entity prefix.
        vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "HouseFly")): str,
        # Hours to shift this fly's day. Two flies twelve hours apart cover the
        # clock between them, and the sleeping one cannot act.
        vol.Optional(CONF_CLOCK_OFFSET, default=defaults.get(CONF_CLOCK_OFFSET, 0)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, step=1, mode="box",
                                              unit_of_measurement="h")),
        # Watching is free and touching is not, so they are asked separately
        # and the safe one is the one that can be turned on wholesale.
        vol.Optional(CONF_WATCH_WHOLE_HOUSE,
                     default=defaults.get(CONF_WATCH_WHOLE_HOUSE, False)):
            selector.BooleanSelector(),
        vol.Optional(CONF_INPUT_ENTITIES, default=defaults.get(CONF_INPUT_ENTITIES, [])):
            selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
        vol.Optional(CONF_OUTPUT_ENTITIES, default=defaults.get(CONF_OUTPUT_ENTITIES, [])):
            selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True, domain=sorted(ALLOWED_DOMAINS))
            ),
        # Ranging sensors get their own slot rather than going in with the
        # rest: a distance is not a smell, it is the one input the looming
        # detectors can actually use, and differencing it is what makes an
        # approach an approach.
        vol.Optional(CONF_APPROACH_ENTITIES, default=defaults.get(CONF_APPROACH_ENTITIES, [])):
            selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True, domain="sensor",
                                              device_class="distance")
            ),
        # Which light the fly should call daylight. Its own slot for the same
        # reason ranging sensors have one: this is not a smell, it is the
        # zeitgeber, and the fly sets its whole day by it.
        #
        # Left empty it falls back to the old behaviour -- the first
        # illuminance sensor it happens to be watching, then the sun's
        # elevation. That fallback was fine when a fly watched six entities
        # somebody had chosen. With whole-house watching it means "whichever
        # illuminance sensor sorts first out of 250", which on a real house
        # was an indoor one that flips whenever a room light does.
        vol.Optional(CONF_LIGHT_ENTITIES, default=defaults.get(CONF_LIGHT_ENTITIES, [])):
            selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True, domain="sensor",
                                              device_class="illuminance")
            ),
        vol.Optional(CONF_ACTUATION_ENABLED,
                     default=defaults.get(CONF_ACTUATION_ENABLED, DEFAULT_ACTUATION_ENABLED)):
            selector.BooleanSelector(),
        vol.Optional(CONF_HOURLY_BUDGET,
                     default=defaults.get(CONF_HOURLY_BUDGET, DEFAULT_HOURLY_BUDGET)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=240, step=1, mode="slider")),
        vol.Optional(CONF_TICK_INTERVAL,
                     default=defaults.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=30, step=1,
                                              unit_of_measurement="s", mode="slider")),
        vol.Optional(CONF_QUIET_HOURS_START, default=defaults.get(CONF_QUIET_HOURS_START, 23)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, step=1, mode="box")),
        vol.Optional(CONF_QUIET_HOURS_END, default=defaults.get(CONF_QUIET_HOURS_END, 7)):
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, step=1, mode="box")),
    })


def _validate(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if len(data.get(CONF_INPUT_ENTITIES, [])) > MAX_INPUT_ENTITIES:
        errors[CONF_INPUT_ENTITIES] = "too_many_inputs"
    if len(data.get(CONF_APPROACH_ENTITIES, [])) > MAX_APPROACH_ENTITIES:
        errors[CONF_APPROACH_ENTITIES] = "too_many_approach"
    outputs = data.get(CONF_OUTPUT_ENTITIES, [])
    if len(outputs) > MAX_OUTPUT_ENTITIES:
        errors[CONF_OUTPUT_ENTITIES] = "too_many_outputs"
    refused = [e for e in outputs if not ActuationGovernor.vet_entity(e).allowed]
    if refused:
        errors[CONF_OUTPUT_ENTITIES] = "unsafe_output"
    return errors


class FlyHouseConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=str(user_input.get(CONF_NAME) or "HouseFly"), data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
            description_placeholders={
                "note": "Actuation is off by default. The fly will watch the house "
                        "and walk around your dashboard without touching anything."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return FlyHouseOptionsFlow(entry)


class FlyHouseOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        current = {**self._entry.data, **self._entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(user_input or current), errors=errors
        )
