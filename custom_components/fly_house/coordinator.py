"""DataUpdateCoordinator that ticks the fly brain and drives outputs."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .brain import FlyBrain, map_channel_to_output
from .const import (
    CONF_INPUT_ENTITIES,
    CONF_INTENSITY,
    CONF_OUTPUT_ENTITIES,
    CONF_SEED,
    CONF_TICK_INTERVAL,
    DEFAULT_INTENSITY,
    DEFAULT_SEED,
    DEFAULT_TICK_INTERVAL,
    DOMAIN,
    MODE_IDLE,
)

_LOGGER = logging.getLogger(__name__)


class FlyHouseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Periodically update reservoir and write mapped outputs."""

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any], entry_id: str) -> None:
        self.entry_id = entry_id
        self.input_entities: list[str] = list(entry_data.get(CONF_INPUT_ENTITIES, []))
        self.output_entities: list[str] = list(entry_data.get(CONF_OUTPUT_ENTITIES, []))
        interval = int(entry_data.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL))
        intensity = float(entry_data.get(CONF_INTENSITY, DEFAULT_INTENSITY))
        seed = int(entry_data.get(CONF_SEED, DEFAULT_SEED))

        self.brain = FlyBrain(seed=seed, intensity=intensity)
        self._apply_outputs = True

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(2, interval)),
        )

    def reconfigure(self, entry_data: dict[str, Any]) -> None:
        """Apply options / config changes."""
        self.input_entities = list(entry_data.get(CONF_INPUT_ENTITIES, []))
        self.output_entities = list(entry_data.get(CONF_OUTPUT_ENTITIES, []))
        interval = int(entry_data.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL))
        intensity = float(entry_data.get(CONF_INTENSITY, DEFAULT_INTENSITY))
        seed = int(entry_data.get(CONF_SEED, DEFAULT_SEED))
        self.update_interval = timedelta(seconds=max(2, interval))
        # Re-seed only if seed changed
        if seed != self.brain.seed:
            self.brain.reset(seed=seed)
        self.brain.set_intensity(intensity)

    def poke(self, strength: float = 1.0) -> None:
        self.brain.poke(strength)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            states = [
                self.hass.states.get(eid)
                for eid in self.input_entities
            ]
            values = [st.state if st is not None else None for st in states]
            result = await self.hass.async_add_executor_job(self.brain.step, values)

            if self._apply_outputs:
                await self._async_drive_outputs(result.get("channels", []))

            return {
                "active": True,
                "spikes": int(result.get("spikes", 0)),
                "mode": result.get("mode", MODE_IDLE),
                "energy": result.get("energy", 0.0),
                "tick": result.get("tick", 0),
                "channels": result.get("channels", []),
            }
        except Exception as err:  # noqa: BLE001 — surface as UpdateFailed
            raise UpdateFailed(f"Fly brain tick failed: {err}") from err

    async def _async_drive_outputs(self, channels: list[float]) -> None:
        for idx, entity_id in enumerate(self.output_entities):
            if idx >= len(channels):
                break
            domain = entity_id.split(".", 1)[0]
            mapped = map_channel_to_output(channels[idx], domain)
            if mapped is None:
                _LOGGER.debug("Skipping unsupported output domain %s (%s)", domain, entity_id)
                continue
            service_domain, service_name = mapped["service"].split(".", 1)
            data = {"entity_id": entity_id, **mapped["data"]}
            try:
                await self.hass.services.async_call(
                    service_domain,
                    service_name,
                    data,
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to drive output %s", entity_id)
