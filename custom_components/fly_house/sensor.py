"""Sensors for Fly House."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_IDLE
from .coordinator import FlyHouseCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlyHouseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FlyHouseSpikesSensor(coordinator, entry),
            FlyHouseModeSensor(coordinator, entry),
            FlyHouseBrainSensor(coordinator, entry),
        ]
    )


class FlyHouseSpikesSensor(CoordinatorEntity[FlyHouseCoordinator], SensorEntity):
    """Approximate 'spike' count (units above threshold)."""

    _attr_has_entity_name = True
    _attr_name = "Spikes"
    _attr_translation_key = "spikes"
    _attr_native_unit_of_measurement = "spikes"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_spikes"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Fly House",
            "manufacturer": "Vome (weekend meme)",
            "model": "Leaky reservoir v0.1",
        }

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return int(data.get("spikes", 0))


class FlyHouseModeSensor(CoordinatorEntity[FlyHouseCoordinator], SensorEntity):
    """Behavioral mode: idle / wander / escape."""

    _attr_has_entity_name = True
    _attr_name = "Mode"
    _attr_translation_key = "mode"
    _attr_icon = "mdi:butterfly"

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Fly House",
            "manufacturer": "Vome (weekend meme)",
            "model": "Leaky reservoir v0.1",
        }

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        return str(data.get("mode", MODE_IDLE))


class FlyHouseBrainSensor(CoordinatorEntity[FlyHouseCoordinator], SensorEntity):
    """Brain visualization sensor with spike art."""

    _attr_has_entity_name = True
    _attr_name = "Brain"
    _attr_translation_key = "brain"
    _attr_icon = "mdi:brain"

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_brain"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Fly House",
            "manufacturer": "Vome (weekend meme)",
            "model": "Leaky reservoir v0.1",
        }

    @property
    def native_value(self) -> str:
        """Return ASCII/unicode spark visualization."""
        data = self.coordinator.data or {}
        spikes = int(data.get("spikes", 0))
        energy = float(data.get("energy", 0.0))
        
        # Create a simple spark bar based on activity
        max_size = 10
        spike_level = min(max_size, int((spikes / 90) * max_size))  # Assuming ~256 neurons, ~35% = 90
        energy_level = min(max_size, int(energy * 15))
        
        spark_bar = "█" * spike_level + "░" * (max_size - spike_level)
        
        # Unicode brain activity
        if spikes > 70:
            brain_state = "⚡💥🧠"
        elif spikes > 30:
            brain_state = "✨🧠"
        elif spikes > 10:
            brain_state = "·🧠"
        else:
            brain_state = "💤🧠"
        
        return f"{brain_state} {spark_bar}"

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed brain state for visualization."""
        data = self.coordinator.data or {}
        spikes = int(data.get("spikes", 0))
        energy = float(data.get("energy", 0.0))
        channels = data.get("channels", [])
        
        return {
            "spikes": spikes,
            "energy": energy,
            "tick": data.get("tick", 0),
            "channels": channels,
            "spark_intensity": min(100, int((spikes / 90) * 100)),
            "ascii_brain": self._generate_ascii_brain(spikes, energy),
        }

    def _generate_ascii_brain(self, spikes: int, energy: float) -> str:
        """Generate a small ASCII connectome art."""
        if spikes > 70:
            return """
  ╭─◉─╮
 ◉─╋─◉─◉  ⚡⚡
  ╰─◉─╯
"""
        elif spikes > 30:
            return """
  ╭─◉─╮
 ○─╋─◉─○  ✨
  ╰─○─╯
"""
        elif spikes > 10:
            return """
  ╭─○─╮
 ○─╋─○─○  ·
  ╰─○─╯
"""
        else:
            return """
  ╭─○─╮
 ○─┼─○─○  💤
  ╰─○─╯
"""
