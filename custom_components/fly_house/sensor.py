"""Sensors for HouseFly.

These are deliberately slow and meaningful. The fast visual stream goes over a
websocket, so nothing here needs to update more than once every couple of
seconds, and everything here is something you might reasonably put on a graph
or trigger an automation from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEGREE, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FlyHouseCoordinator


@dataclass(frozen=True, kw_only=True)
class FlySensorDescription(SensorEntityDescription):
    """A sensor plus how to get its value out of a tick."""

    value: Callable[[dict[str, Any], FlyHouseCoordinator], Any]
    attrs: Callable[[dict[str, Any], FlyHouseCoordinator], dict[str, Any]] | None = None


SENSORS: tuple[FlySensorDescription, ...] = (
    FlySensorDescription(
        key="mode",
        name="Mode",
        icon="mdi:bee",
        value=lambda d, c: d.get("mode", "groom"),
        attrs=lambda d, c: {
            "goal_entity": d.get("goal_entity"),
            "landmarks_visible": d.get("landmarks", 0),
            "age_seconds": d.get("age_seconds", 0),
            # A sensor stuck on "unknown" is not a smell of nothing, it is no
            # smell at all, and silently feeding the brain a zero for it hides
            # a misconfiguration that makes the fly look broken instead.
            "live_inputs": d.get("live_inputs", 0),
            "dead_inputs": d.get("dead_inputs", []),
        },
    ),
    FlySensorDescription(
        key="heading",
        name="Heading",
        icon="mdi:compass-outline",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: round(d.get("heading_deg", 0.0), 1),
        attrs=lambda d, c: {
            # How concentrated the activity bump is around a single heading.
            # Near zero means the compass has lost track of where it is facing.
            "bump_strength": d.get("bump_strength", 0.0),
            "turn_command": d.get("turn", 0.0),
            "compass_profile": c.brain.compass_profile(),
        },
    ),
    FlySensorDescription(
        key="valence",
        name="Valence",
        icon="mdi:emoticon-neutral-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: round(d.get("valence", 0.0), 3),
        attrs=lambda d, c: {
            "mbon_activity": d.get("mbon_activity", 0.0),
            "explanation": "Positive means the mushroom body output favours "
                           "approach; negative means avoidance.",
        },
    ),
    FlySensorDescription(
        key="memory",
        name="Memory",
        icon="mdi:brain",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: round(d.get("memory_depression", 0.0) * 100, 2),
        attrs=lambda d, c: {
            "plastic_synapses": int(len(c.brain.kc_mbon_gain)),
            "explanation": "Percentage depression of the Kenyon cell to MBON "
                           "synapses away from their measured strength. This is "
                           "everything the fly has learned about your house.",
        },
    ),
    FlySensorDescription(
        key="arousal",
        name="Arousal",
        icon="mdi:sleep-off",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: round(d.get("arousal", 0.5), 3),
        attrs=lambda d, c: {
            "driven_by": "s-LNv / l-LNv morning and LNd / DN1 evening oscillators",
        },
    ),
    FlySensorDescription(
        key="hunger",
        name="Hunger",
        icon="mdi:food-apple-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: round(d.get("hunger", 0.0) * 100),
    ),
    FlySensorDescription(
        key="kenyon_cells",
        name="Kenyon cells active",
        icon="mdi:scatter-plot-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: d.get("kc_active", 0),
        attrs=lambda d, c: {
            "kenyon_cells_total": d.get("kc_total", 0),
            "sparseness": d.get("kc_sparseness", 0.0),
            "explanation": "Real mushroom bodies keep roughly 5% of Kenyon "
                           "cells active for any given odour. That sparse code "
                           "is what makes the memory addressable.",
        },
    ),
    FlySensorDescription(
        key="network_activity",
        name="Network activity",
        icon="mdi:pulse",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: round(d.get("network_activity", 0.0), 5),
        attrs=lambda d, c: {
            "active_neurons": d.get("active_neurons", 0),
            "neurons": int(c.brain.data.n),
            "synapses": int(len(c.brain.data.pre)),
            "tick": d.get("tick", 0),
        },
    ),
    FlySensorDescription(
        key="familiarity",
        name="Familiarity",
        icon="mdi:head-question-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # How much of the house, right now, looks like something it has met
        # before. This is the mushroom body doing the job it evolved for.
        #
        # Dasgupta, Stevens & Navlakha (2017) showed the Kenyon cell layer is a
        # locality-sensitive hash: a sparse random projection whose codes stay
        # close for similar inputs and separate for different ones. Hattori et
        # al. (2017) found the readout -- repeated exposure depresses KC->MBON
        # synapses in the alpha'3 compartment whether or not anything good or
        # bad happened, so those cells answer "have I met this?" and nothing
        # else. No labels, no training set, no cloud: it learns what your house
        # is like by living in it.
        value=lambda d, c: round(100.0 * (1.0 - d.get("novelty", 0.0)), 1),
        attrs=lambda d, c: {
            "novelty": d.get("novelty", 0.0),
            **{k: v for k, v in d.get("unusual", {}).items() if k != "novelty"},
            "compartment": "MBON16 / MBON17 / MBON28 (alpha-prime-3)",
        },
    ),
    FlySensorDescription(
        key="approach",
        name="Approach",
        icon="mdi:arrow-collapse-right",
        state_class=SensorStateClass.MEASUREMENT,
        # theta-dot itself, in radians per second, before anything in the brain
        # touches it. Published because it is useful on its own and the rest of
        # HouseFly is not always what you want in a control loop.
        #
        # A path light that brightens as somebody walks up to it wants exactly
        # this curve: v/r^2 is near zero for someone far off or dawdling and
        # climbs steeply as they close, so it ignores a person standing at the
        # gate without needing a threshold to do it. Distance alone cannot tell
        # those apart; a PIR cannot either.
        #
        # Drive the lights from this sensor with an ordinary automation. Do not
        # put the fly in the loop: it is crepuscular and it sleeps, and a porch
        # light that depends on whether a simulated insect is having its
        # afternoon nap is not a porch light.
        value=lambda d, c: round(d.get("approach", {}).get("rate", 0.0), 4),
        attrs=lambda d, c: {
            **d.get("approach", {}),
            "units": "radians per second of angular expansion",
            "pathway": "the same figure LPLC2 receives",
        },
    ),
    FlySensorDescription(
        key="actuations",
        name="Actuations this hour",
        icon="mdi:gesture-tap-button",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d, c: d.get("safety", {}).get("calls_last_hour", 0),
        attrs=lambda d, c: {
            **d.get("safety", {}),
            "recent_actions": d.get("recent_actions", []),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlyHouseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(FlySensor(coordinator, entry, d) for d in SENSORS)


class FlySensor(CoordinatorEntity[FlyHouseCoordinator], SensorEntity):
    """One reading off the fly."""

    _attr_has_entity_name = True
    entity_description: FlySensorDescription

    def __init__(
        self,
        coordinator: FlyHouseCoordinator,
        entry: ConfigEntry,
        description: FlySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "HouseFly",
            "manufacturer": "Drosophila melanogaster",
            "model": f"hemibrain v1.2 · {coordinator.brain.data.n} neurons",
            "sw_version": "2.0.0",
        }

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data or {}, self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs is None:
            return None
        return self.entity_description.attrs(self.coordinator.data or {}, self.coordinator)
