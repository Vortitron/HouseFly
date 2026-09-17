"""Config flow for Fly House."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_INPUT_ENTITIES,
    CONF_INTENSITY,
    CONF_OUTPUT_ENTITIES,
    CONF_SEED,
    CONF_TICK_INTERVAL,
    CONF_WHOLE_HOUSE,
    DEFAULT_INTENSITY,
    DEFAULT_SEED,
    DEFAULT_TICK_INTERVAL,
    DOMAIN,
    MAX_INPUT_ENTITIES,
    MAX_OUTPUT_ENTITIES,
)

INPUT_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(multiple=True, domain=["sensor", "binary_sensor", "input_boolean", "input_number", "person", "device_tracker", "sun", "weather"])
)

OUTPUT_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(multiple=True, domain=["light", "cover", "switch", "number", "input_number", "fan"])
)


def _schema(defaults: dict[str, Any] | None = None, *, show_whole_house: bool = True) -> vol.Schema:
    d = defaults or {}
    schema_dict = {
        vol.Required(
            CONF_INPUT_ENTITIES,
            default=d.get(CONF_INPUT_ENTITIES, []),
        ): INPUT_SELECTOR,
        vol.Required(
            CONF_OUTPUT_ENTITIES,
            default=d.get(CONF_OUTPUT_ENTITIES, []),
        ): OUTPUT_SELECTOR,
        vol.Required(
            CONF_TICK_INTERVAL,
            default=d.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=2, max=120, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="s")
        ),
        vol.Required(
            CONF_INTENSITY,
            default=d.get(CONF_INTENSITY, DEFAULT_INTENSITY),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required(
            CONF_SEED,
            default=d.get(CONF_SEED, DEFAULT_SEED),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=2_147_483_647, step=1, mode=selector.NumberSelectorMode.BOX)
        ),
    }
    
    if show_whole_house:
        schema_dict[vol.Optional(CONF_WHOLE_HOUSE, default=d.get(CONF_WHOLE_HOUSE, False))] = selector.BooleanSelector()
    
    return vol.Schema(schema_dict)


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    inputs = user_input.get(CONF_INPUT_ENTITIES) or []
    outputs = user_input.get(CONF_OUTPUT_ENTITIES) or []
    
    if not inputs:
        errors["base"] = "no_inputs"
    elif len(inputs) > MAX_INPUT_ENTITIES:
        errors["base"] = "too_many_inputs"
    if not outputs:
        errors["base"] = errors.get("base") or "no_outputs"
    elif len(outputs) > MAX_OUTPUT_ENTITIES:
        errors["base"] = "too_many_outputs"
    
    return errors


class FlyHouseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fly House."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        # Single instance is enough for the meme
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                # Coerce number selector floats to ints where needed
                data = {
                    CONF_INPUT_ENTITIES: list(user_input[CONF_INPUT_ENTITIES]),
                    CONF_OUTPUT_ENTITIES: list(user_input[CONF_OUTPUT_ENTITIES]),
                    CONF_TICK_INTERVAL: int(user_input[CONF_TICK_INTERVAL]),
                    CONF_INTENSITY: float(user_input[CONF_INTENSITY]),
                    CONF_SEED: int(user_input[CONF_SEED]),
                    CONF_WHOLE_HOUSE: bool(user_input.get(CONF_WHOLE_HOUSE, False)),
                    CONF_NAME: "HouseFly",
                }
                return self.async_create_entry(title="HouseFly", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FlyHouseOptionsFlow()


class FlyHouseOptionsFlow(config_entries.OptionsFlow):
    """Options flow to retune the fly without reinstalling."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                data = {
                    CONF_INPUT_ENTITIES: list(user_input[CONF_INPUT_ENTITIES]),
                    CONF_OUTPUT_ENTITIES: list(user_input[CONF_OUTPUT_ENTITIES]),
                    CONF_TICK_INTERVAL: int(user_input[CONF_TICK_INTERVAL]),
                    CONF_INTENSITY: float(user_input[CONF_INTENSITY]),
                    CONF_SEED: int(user_input[CONF_SEED]),
                    CONF_WHOLE_HOUSE: bool(user_input.get(CONF_WHOLE_HOUSE, False)),
                }
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current if user_input is None else user_input),
            errors=errors,
        )
