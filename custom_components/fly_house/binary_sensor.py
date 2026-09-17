"""Binary sensors for Fly House."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ENERGY, ATTR_MODE, ATTR_SPIKES, DOMAIN
from .coordinator import FlyHouseCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlyHouseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FlyHouseActiveBinarySensor(coordinator, entry)])


class FlyHouseActiveBinarySensor(CoordinatorEntity[FlyHouseCoordinator], BinarySensorEntity):
    """On while the fly brain is ticking successfully."""

    _attr_has_entity_name = True
    _attr_name = "Active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "active"

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Fly House",
            "manufacturer": "Vortitron",
            "model": "Leaky reservoir v1.0",
        }

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return bool(data.get("active", False))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            ATTR_SPIKES: data.get("spikes"),
            ATTR_MODE: data.get("mode"),
            ATTR_ENERGY: data.get("energy"),
            "tick": data.get("tick"),
        }
