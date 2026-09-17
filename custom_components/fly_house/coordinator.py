"""DataUpdateCoordinator that ticks the fly brain and drives outputs."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .brain import FlyBrain, map_channel_to_output
from .const import (
    CONF_CAMERA_ENTITY,
    CONF_INPUT_ENTITIES,
    CONF_INTENSITY,
    CONF_OUTPUT_ENTITIES,
    CONF_SEED,
    CONF_TICK_INTERVAL,
    CONF_VISION_TICK_INTERVAL,
    DEFAULT_INTENSITY,
    DEFAULT_SEED,
    DEFAULT_TICK_INTERVAL,
    DEFAULT_VISION_TICK_INTERVAL,
    DOMAIN,
    MODE_IDLE,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_state"


class FlyHouseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Periodically update reservoir and write mapped outputs."""

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any], entry_id: str) -> None:
        self.entry_id = entry_id
        self.input_entities: list[str] = list(entry_data.get(CONF_INPUT_ENTITIES, []))
        self.output_entities: list[str] = list(entry_data.get(CONF_OUTPUT_ENTITIES, []))
        self.camera_entity: str | None = entry_data.get(CONF_CAMERA_ENTITY) or None
        self.vision_tick_interval: int = int(
            entry_data.get(CONF_VISION_TICK_INTERVAL, DEFAULT_VISION_TICK_INTERVAL)
        )
        interval = int(entry_data.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL))
        intensity = float(entry_data.get(CONF_INTENSITY, DEFAULT_INTENSITY))
        seed = int(entry_data.get(CONF_SEED, DEFAULT_SEED))

        self.brain = FlyBrain(seed=seed, intensity=intensity)
        self._apply_outputs = True
        self._last_vision_at: float = 0.0
        self._last_image_data: bytes | None = None
        self._last_light_states: dict[str, float] = {}
        self._vision_source: str = "none"
        
        # Lifecycle metadata
        self._birth_time: datetime = dt_util.utcnow()
        self._last_poke_time: datetime | None = None
        self._last_feed_time: datetime | None = None
        self._last_mode: str = MODE_IDLE
        
        # Storage for persistence
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")

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
        self.camera_entity = entry_data.get(CONF_CAMERA_ENTITY) or None
        self.vision_tick_interval = int(
            entry_data.get(CONF_VISION_TICK_INTERVAL, DEFAULT_VISION_TICK_INTERVAL)
        )
        interval = int(entry_data.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL))
        intensity = float(entry_data.get(CONF_INTENSITY, DEFAULT_INTENSITY))
        seed = int(entry_data.get(CONF_SEED, DEFAULT_SEED))
        self.update_interval = timedelta(seconds=max(2, interval))
        if seed != self.brain.seed:
            self.brain.reset(seed=seed)
        self.brain.set_intensity(intensity)
        if not self.camera_entity:
            self._last_image_data = None
            self._vision_source = "none"

    def poke(self, strength: float = 1.0) -> None:
        self.brain.poke(strength)
        self._last_poke_time = dt_util.utcnow()

    def feed(self, amount: float = 0.3) -> None:
        self.brain.feed(amount)
        self._last_feed_time = dt_util.utcnow()
    
    async def async_save_state(self) -> None:
        """Persist fly state to storage."""
        try:
            state_data = {
                "hunger": float(self.brain.hunger),
                "mode": self._last_mode,
                "birth_time": self._birth_time.isoformat(),
                "last_poke_time": self._last_poke_time.isoformat() if self._last_poke_time else None,
                "last_feed_time": self._last_feed_time.isoformat() if self._last_feed_time else None,
            }
            await self._store.async_save(state_data)
            _LOGGER.debug("HouseFly state saved: hunger=%s, mode=%s", state_data["hunger"], state_data["mode"])
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to save HouseFly state: %s", err)
    
    async def async_restore_state(self) -> None:
        """Restore fly state from storage."""
        try:
            state_data = await self._store.async_load()
            if state_data:
                self.brain.hunger = float(state_data.get("hunger", 0.0))
                self._last_mode = state_data.get("mode", MODE_IDLE)
                
                birth_iso = state_data.get("birth_time")
                if birth_iso:
                    self._birth_time = dt_util.parse_datetime(birth_iso) or dt_util.utcnow()
                
                poke_iso = state_data.get("last_poke_time")
                if poke_iso:
                    self._last_poke_time = dt_util.parse_datetime(poke_iso)
                
                feed_iso = state_data.get("last_feed_time")
                if feed_iso:
                    self._last_feed_time = dt_util.parse_datetime(feed_iso)
                
                _LOGGER.info(
                    "HouseFly state restored: hunger=%s, mode=%s, age=%s",
                    self.brain.hunger,
                    self._last_mode,
                    dt_util.utcnow() - self._birth_time,
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("No previous HouseFly state to restore: %s", err)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            states = [self.hass.states.get(eid) for eid in self.input_entities]
            values = [st.state if st is not None else None for st in states]

            vision_data = await self._async_prepare_vision()

            result = await self.hass.async_add_executor_job(
                self.brain.step, values, vision_data
            )

            if self._apply_outputs:
                await self._async_drive_outputs(result.get("channels", []))

            mode = result.get("mode", MODE_IDLE)
            self._last_mode = mode
            
            # Periodically save state (every ~50 ticks, about 8 minutes at default 10s)
            tick = result.get("tick", 0)
            if tick > 0 and tick % 50 == 0:
                await self.async_save_state()

            # Calculate time alive
            time_alive_seconds = int((dt_util.utcnow() - self._birth_time).total_seconds())

            return {
                "active": True,
                "spikes": int(result.get("spikes", 0)),
                "mode": mode,
                "energy": result.get("energy", 0.0),
                "tick": tick,
                "channels": result.get("channels", []),
                "hunger": result.get("hunger", 0.0),
                "retina_hex": result.get("retina_hex", ""),
                "retina_ascii": result.get("retina_ascii", ""),
                "visual_motion": result.get("visual_motion", 0.0),
                "vision_source": self._vision_source,
                "camera_entity": self.camera_entity,
                "birth_time": self._birth_time.isoformat(),
                "last_poke_time": self._last_poke_time.isoformat() if self._last_poke_time else None,
                "last_feed_time": self._last_feed_time.isoformat() if self._last_feed_time else None,
                "time_alive_seconds": time_alive_seconds,
            }
        except Exception as err:  # noqa: BLE001 — surface as UpdateFailed
            raise UpdateFailed(f"Fly brain tick failed: {err}") from err

    async def _async_prepare_vision(self) -> dict[str, Any]:
        """Prepare vision data from camera snapshot or synthesized light field."""
        light_states: dict[str, float] = {}

        sun = self.hass.states.get("sun.sun")
        if sun:
            light_states["sun_elevation"] = float(sun.attributes.get("elevation", 0))

        for state in self.hass.states.async_all():
            if state.domain == "light" and state.state == "on":
                brightness = state.attributes.get("brightness", 255)
                light_states[state.entity_id] = brightness / 255.0

        self._last_light_states = light_states

        image_data: bytes | None = None
        now = time.monotonic()
        due_for_snapshot = (now - self._last_vision_at) >= max(5, self.vision_tick_interval)

        if self.camera_entity and due_for_snapshot:
            try:
                from homeassistant.components.camera import async_get_image

                image = await async_get_image(
                    self.hass,
                    self.camera_entity,
                    timeout=10,
                    width=64,
                    height=64,
                )
                image_data = image.content
                self._last_image_data = image_data
                self._last_vision_at = now
                self._vision_source = "camera"
                _LOGGER.debug(
                    "HouseFly camera snapshot ok (%s bytes) from %s",
                    len(image_data),
                    self.camera_entity,
                )
            except Exception as err:  # noqa: BLE001 — fall back to lights+sun
                _LOGGER.debug(
                    "HouseFly camera snapshot failed (%s): %s — using lights+sun",
                    self.camera_entity,
                    err,
                )
                image_data = None
                self._last_vision_at = now  # back off even on failure
                self._vision_source = "lights_sun"
        elif self.camera_entity and self._last_image_data:
            # Reuse last good frame between vision ticks
            image_data = self._last_image_data
            self._vision_source = "camera_cached"
        else:
            self._vision_source = "lights_sun" if light_states else "none"

        return {
            "image_data": image_data,
            "light_states": light_states,
        }

    async def _async_drive_outputs(self, channels: list[float]) -> None:
        hunger = float(getattr(self.brain, "hunger", 0.0))
        phototaxis = hunger > 0.35

        # Rank light outputs by current brightness for hunger phototaxis
        light_brightness: dict[str, float] = {}
        if phototaxis:
            for eid in self.output_entities:
                if not eid.startswith("light."):
                    continue
                # Prefer live HA brightness; fall back to last vision light map
                st = self.hass.states.get(eid)
                if st and st.state == "on":
                    light_brightness[eid] = (st.attributes.get("brightness") or 128) / 255.0
                else:
                    light_brightness[eid] = float(self._last_light_states.get(eid, 0.0))

        for idx, entity_id in enumerate(self.output_entities):
            if idx >= len(channels):
                break
            domain = entity_id.split(".", 1)[0]
            channel = float(channels[idx])

            # Stronger phototaxis when hungry: bias brighter light.* channels upward
            if phototaxis and entity_id in light_brightness:
                bri = light_brightness[entity_id]
                # Hungry fly seeks light: boost brighter targets more; dim ones get a small seek nudge
                boost = hunger * (0.15 + 0.45 * bri)
                channel = min(1.0, channel + boost)

            mapped = map_channel_to_output(channel, domain)
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
