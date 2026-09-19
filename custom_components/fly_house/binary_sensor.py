"""Binary sensors for HouseFly."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_ESCAPE, MODE_SLEEP
from .coordinator import FlyHouseCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlyHouseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        FlyAwake(coordinator, entry),
        FlyEscaping(coordinator, entry),
        FlyUnusual(coordinator, entry),
    ])


class _Base(CoordinatorEntity[FlyHouseCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "HouseFly",
            "manufacturer": "Drosophila melanogaster",
            "model": f"hemibrain v1.2 · {coordinator.brain.data.n} neurons",
        }


class FlyAwake(_Base):
    """Whether the circadian circuit currently says it is daytime for the fly."""

    _attr_name = "Awake"
    _attr_icon = "mdi:eye-outline"

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "awake")

    @property
    def is_on(self) -> bool:
        return (self.coordinator.data or {}).get("mode") != MODE_SLEEP


class FlyEscaping(_Base):
    """The giant-fibre-adjacent descending neurons are firing."""

    _attr_name = "Escaping"
    _attr_icon = "mdi:run-fast"
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "escaping")

    @property
    def is_on(self) -> bool:
        return (self.coordinator.data or {}).get("mode") == MODE_ESCAPE

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "escape_drive": data.get("escape", 0.0),
            "pathway": "LPLC2 / LC4 -> DNp09, DNp10, DNp11",
        }


class FlyUnusual(_Base):
    """The house does not look like itself.

    This is the fly being useful rather than the fly being decorative, and the
    distinction worth drawing is that nothing about it was grafted on. Telling
    familiar from unfamiliar is what a mushroom body is *for*; the Kenyon layer
    is a locality-sensitive hash (Dasgupta, Stevens & Navlakha 2017) and the
    alpha'3 compartment is the circuit that reads it out (Hattori et al. 2017).

    So there is no model to train, no labels to collect and nothing to send
    anywhere. It learns what your house is like by living in it, and it says so
    when the house stops looking like that. It will not tell you *what* changed
    -- it has no idea -- only that something has, which is the one thing a
    rules engine cannot do because you would have had to write the rule first.

    Deliberately slow and deliberately quiet: it holds its tongue entirely
    until it has learned something, and then needs two minutes of sustained
    strangeness before it will say anything.
    """

    _attr_name = "Something unusual"
    _attr_icon = "mdi:comment-question-outline"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: FlyHouseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "unusual")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("unusual", {}).get("unusual", False))

    @property
    def extra_state_attributes(self) -> dict:
        data = (self.coordinator.data or {}).get("unusual", {})
        return {
            **data,
            "how": "unsupervised familiarity in the mushroom body, not a rule",
            "caveat": "it can tell you something changed, never what",
        }
