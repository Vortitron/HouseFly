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
    _user_input: dict[str, Any] | None = None

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
                # If whole house mode enabled, go to confirmation step
                if user_input.get(CONF_WHOLE_HOUSE, False):
                    self._user_input = user_input
                    return await self.async_step_confirm_whole_house()
                
                # Normal flow without whole house
                data = {
                    CONF_INPUT_ENTITIES: list(user_input[CONF_INPUT_ENTITIES]),
                    CONF_OUTPUT_ENTITIES: list(user_input[CONF_OUTPUT_ENTITIES]),
                    CONF_TICK_INTERVAL: int(user_input[CONF_TICK_INTERVAL]),
                    CONF_INTENSITY: float(user_input[CONF_INTENSITY]),
                    CONF_SEED: int(user_input[CONF_SEED]),
                    CONF_WHOLE_HOUSE: False,
                    CONF_NAME: "HouseFly",
                }
                return self.async_create_entry(title="HouseFly", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_confirm_whole_house(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirmation step for whole house mode with scary warnings."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            if not user_input.get("confirm_chaos", False):
                errors["base"] = "must_confirm_chaos"
            else:
                # User confirmed — auto-select entities
                original_input = self._user_input or {}
                
                # Auto-select outputs (lights, switches, covers, fans)
                auto_outputs = await self._async_get_whole_house_outputs()
                
                # Auto-select inputs if empty, otherwise keep user selection
                inputs = list(original_input.get(CONF_INPUT_ENTITIES, []))
                if not inputs:
                    inputs = await self._async_get_default_inputs()
                
                # Apply safety constraints for whole house mode
                tick_interval = max(15, int(original_input.get(CONF_TICK_INTERVAL, 15)))
                intensity = min(0.4, float(original_input.get(CONF_INTENSITY, 0.4)))
                
                data = {
                    CONF_INPUT_ENTITIES: inputs,
                    CONF_OUTPUT_ENTITIES: auto_outputs,
                    CONF_TICK_INTERVAL: tick_interval,
                    CONF_INTENSITY: intensity,
                    CONF_SEED: int(original_input.get(CONF_SEED, DEFAULT_SEED)),
                    CONF_WHOLE_HOUSE: True,
                    CONF_NAME: "HouseFly",
                }
                
                return self.async_create_entry(title="HouseFly (Whole House)", data=data)
        
        # Show count of entities that will be controlled
        auto_outputs = await self._async_get_whole_house_outputs()
        output_count = len(auto_outputs)
        
        return self.async_show_form(
            step_id="confirm_whole_house",
            data_schema=vol.Schema({
                vol.Required("confirm_chaos", default=False): selector.BooleanSelector()
            }),
            description_placeholders={
                "output_count": str(output_count),
                "max_outputs": str(MAX_OUTPUT_ENTITIES),
            },
            errors=errors,
        )

    async def _async_get_whole_house_outputs(self) -> list[str]:
        """Get all controllable entities for whole house mode."""
        entities = []
        domains = ["light", "switch", "cover", "fan"]
        
        for state in self.hass.states.async_all():
            if state.domain in domains:
                # Skip unavailable/unknown entities
                if state.state not in ("unavailable", "unknown"):
                    entities.append(state.entity_id)
        
        # Cap at MAX_OUTPUT_ENTITIES, prioritise lights then switches
        if len(entities) > MAX_OUTPUT_ENTITIES:
            # Sort: lights first, then switches, then covers, then fans
            def sort_key(eid: str) -> tuple:
                domain = eid.split(".", 1)[0]
                priority = {"light": 0, "switch": 1, "cover": 2, "fan": 3}.get(domain, 4)
                return (priority, eid)
            
            entities.sort(key=sort_key)
            entities = entities[:MAX_OUTPUT_ENTITIES]
        
        return entities

    async def _async_get_default_inputs(self) -> list[str]:
        """Get sensible default inputs when whole house enabled with no inputs."""
        inputs = []
        
        # Add sun if available
        if self.hass.states.get("sun.sun"):
            inputs.append("sun.sun")
        
        # Add a few motion sensors (up to 5)
        motion_count = 0
        for state in self.hass.states.async_all():
            if state.domain == "binary_sensor" and "motion" in state.entity_id.lower():
                if state.state not in ("unavailable", "unknown"):
                    inputs.append(state.entity_id)
                    motion_count += 1
                    if motion_count >= 5:
                        break
        
        # Add time sensor if available
        if self.hass.states.get("sensor.time"):
            inputs.append("sensor.time")
        
        return inputs if inputs else []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FlyHouseOptionsFlow()


class FlyHouseOptionsFlow(config_entries.OptionsFlow):
    """Options flow to retune the fly without reinstalling."""

    _user_input: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                # Check if enabling whole house mode (was off, now on)
                was_whole_house = current.get(CONF_WHOLE_HOUSE, False)
                now_whole_house = user_input.get(CONF_WHOLE_HOUSE, False)
                
                if now_whole_house and not was_whole_house:
                    # Enabling whole house — go to confirmation
                    self._user_input = user_input
                    return await self.async_step_confirm_whole_house()
                
                # Normal save or disabling whole house
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

    async def async_step_confirm_whole_house(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirmation step for enabling whole house mode in options."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            if not user_input.get("confirm_chaos", False):
                errors["base"] = "must_confirm_chaos"
            else:
                # User confirmed — auto-select entities
                original_input = self._user_input or {}
                
                # Auto-select outputs
                auto_outputs = await self._async_get_whole_house_outputs()
                
                # Keep existing inputs or add defaults if empty
                inputs = list(original_input.get(CONF_INPUT_ENTITIES, []))
                if not inputs:
                    inputs = await self._async_get_default_inputs()
                
                # Apply safety constraints
                tick_interval = max(15, int(original_input.get(CONF_TICK_INTERVAL, 15)))
                intensity = min(0.4, float(original_input.get(CONF_INTENSITY, 0.4)))
                
                data = {
                    CONF_INPUT_ENTITIES: inputs,
                    CONF_OUTPUT_ENTITIES: auto_outputs,
                    CONF_TICK_INTERVAL: tick_interval,
                    CONF_INTENSITY: intensity,
                    CONF_SEED: int(original_input.get(CONF_SEED, DEFAULT_SEED)),
                    CONF_WHOLE_HOUSE: True,
                }
                
                return self.async_create_entry(title="", data=data)
        
        # Show count of entities that will be controlled
        auto_outputs = await self._async_get_whole_house_outputs()
        output_count = len(auto_outputs)
        
        return self.async_show_form(
            step_id="confirm_whole_house",
            data_schema=vol.Schema({
                vol.Required("confirm_chaos", default=False): selector.BooleanSelector()
            }),
            description_placeholders={
                "output_count": str(output_count),
                "max_outputs": str(MAX_OUTPUT_ENTITIES),
            },
            errors=errors,
        )

    async def _async_get_whole_house_outputs(self) -> list[str]:
        """Get all controllable entities for whole house mode."""
        entities = []
        domains = ["light", "switch", "cover", "fan"]
        
        for state in self.hass.states.async_all():
            if state.domain in domains:
                if state.state not in ("unavailable", "unknown"):
                    entities.append(state.entity_id)
        
        # Cap at MAX_OUTPUT_ENTITIES, prioritise lights then switches
        if len(entities) > MAX_OUTPUT_ENTITIES:
            def sort_key(eid: str) -> tuple:
                domain = eid.split(".", 1)[0]
                priority = {"light": 0, "switch": 1, "cover": 2, "fan": 3}.get(domain, 4)
                return (priority, eid)
            
            entities.sort(key=sort_key)
            entities = entities[:MAX_OUTPUT_ENTITIES]
        
        return entities

    async def _async_get_default_inputs(self) -> list[str]:
        """Get sensible default inputs when whole house enabled with no inputs."""
        inputs = []
        
        # Add sun if available
        if self.hass.states.get("sun.sun"):
            inputs.append("sun.sun")
        
        # Add a few motion sensors (up to 5)
        motion_count = 0
        for state in self.hass.states.async_all():
            if state.domain == "binary_sensor" and "motion" in state.entity_id.lower():
                if state.state not in ("unavailable", "unknown"):
                    inputs.append(state.entity_id)
                    motion_count += 1
                    if motion_count >= 5:
                        break
        
        # Add time sensor if available
        if self.hass.states.get("sensor.time"):
            inputs.append("sensor.time")
        
        return inputs if inputs else []
