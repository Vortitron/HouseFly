"""HouseFly -- a connectome-constrained fruit fly living in Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_AMOUNT,
    ATTR_STRENGTH,
    CONF_ACTUATION_ENABLED,
    CONF_HOURLY_BUDGET,
    CONF_OUTPUT_ENTITIES,
    CONF_TICK_INTERVAL,
    DEFAULT_HOURLY_BUDGET,
    DEFAULT_FEED_AMOUNT,
    DEFAULT_LOOM_STRENGTH,
    DEFAULT_TICK_INTERVAL,
    DOMAIN,
    SERVICE_FEED,
    SERVICE_LOOM,
    SERVICE_RESET_MEMORY,
)
from .connectome_fetch import async_ensure_connectome
from .coordinator import FlyHouseCoordinator
from .safety import ActuationGovernor
from . import websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
_FRONTEND_KEY = f"{DOMAIN}_frontend_registered"

CARDS = ("housefly-overlay.js", "housefly-brain-card.js")

LOOM_SCHEMA = vol.Schema({
    vol.Optional(ATTR_STRENGTH, default=DEFAULT_LOOM_STRENGTH):
        vol.All(vol.Coerce(float), vol.Range(min=0.1, max=3.0)),
})
FEED_SCHEMA = vol.Schema({
    vol.Optional(ATTR_AMOUNT, default=DEFAULT_FEED_AMOUNT):
        vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
})


def _merged(entry: ConfigEntry) -> dict[str, Any]:
    return {**entry.data, **entry.options}


# Settings that existed in v1 and mean nothing now: the reservoir's size and
# seed, and the camera the old compound eye sampled.
REMOVED_IN_V2 = ("intensity", "seed", "camera_entity", "vision_tick_interval",
                 "whole_house")


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring a v1 config entry forward.

    Without this, Home Assistant logs "Migration handler not found" and refuses
    to load the entry at all, so an existing install upgrades itself into an
    integration that silently does nothing. The version was bumped when the
    options changed shape; this is the other half of that change.

    Two decisions worth stating:

    * Actuation comes back **off**. A v1 entry had no such switch -- it wrote to
      every configured output on every tick, unconditionally. Carrying that
      forward as "enabled" would mean an upgrade silently granted write access
      under a new set of rules the user never agreed to. They can turn it on.
    * Outputs are re-vetted. v1 accepted domains v2 refuses outright, `cover`
      among them, so anything that no longer passes is dropped here rather than
      being silently ignored at runtime.
    """
    if entry.version > 2:
        # Downgrade. Nothing sensible to do, and pretending otherwise loses data.
        return False
    if entry.version == 2:
        return True

    data = {**entry.data, **entry.options}
    removed = [k for k in REMOVED_IN_V2 if k in data]
    for key in removed:
        data.pop(key, None)

    outputs = list(data.get(CONF_OUTPUT_ENTITIES, []))
    kept = [e for e in outputs if ActuationGovernor.vet_entity(e).allowed]
    refused = [e for e in outputs if e not in kept]
    data[CONF_OUTPUT_ENTITIES] = kept

    data[CONF_ACTUATION_ENABLED] = False
    data.setdefault(CONF_HOURLY_BUDGET, DEFAULT_HOURLY_BUDGET)
    data.setdefault(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL)

    hass.config_entries.async_update_entry(entry, data=data, options={}, version=2)
    _LOGGER.info(
        "Migrated HouseFly to v2. Dropped %s. %s. Actuation is off -- turn it "
        "on in the integration options once you are happy with what it does.",
        ", ".join(removed) or "nothing",
        f"Refused {len(refused)} output(s) on safety grounds: {', '.join(refused)}"
        if refused else "All outputs still allowed",
    )
    _async_forget_v1_entities(hass, entry)
    return True


@callback
def _async_forget_v1_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop registry entries for sensors that no longer exist.

    v1's spikes/brain/retina sensors and its "active" binary sensor are gone.
    Left in the registry they sit there as `unavailable` for ever, which looks
    exactly like a broken integration.
    """
    registry = er.async_get(hass)
    stale = {"spikes", "brain", "retina", "active"}
    for reg_entry in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        suffix = (reg_entry.unique_id or "").rsplit("_", 1)[-1]
        if suffix in stale:
            _LOGGER.debug("Removing v1 entity %s", reg_entry.entity_id)
            registry.async_remove(reg_entry.entity_id)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    if hass.data.get(_FRONTEND_KEY):
        return
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}", str(www), cache_headers=False)]
    )
    for card in CARDS:
        add_extra_js_url(hass, f"/{DOMAIN}/{card}")
    hass.data[_FRONTEND_KEY] = True
    _LOGGER.debug("HouseFly cards registered: %s", ", ".join(CARDS))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await _async_register_frontend(hass)

    # Normally a no-op: the connectome ships with the integration. It only does
    # anything where the files arrived by a route that could not carry 432 KB of
    # binary, and it refuses anything whose checksum does not match.
    connectome_dir = Path(__file__).parent / "connectome"
    if not await async_ensure_connectome(hass, connectome_dir):
        raise ConfigEntryNotReady(
            "HouseFly's connectome data pack is missing and could not be "
            "fetched. Without it there is no brain to run."
        )

    coordinator = FlyHouseCoordinator(hass, _merged(entry), entry.entry_id)
    await coordinator.async_restore_state()
    await coordinator.async_settle()
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_services(hass)
    _LOGGER.info(
        "HouseFly awake: %d neurons, %d synapses, actuation %s",
        coordinator.brain.data.n,
        len(coordinator.brain.data.pre),
        "ENABLED" if coordinator.governor.enabled else "off (observe-only)",
    )
    return True


def _register_services(hass: HomeAssistant) -> None:
    def _each() -> list[FlyHouseCoordinator]:
        return [c for c in hass.data[DOMAIN].values() if isinstance(c, FlyHouseCoordinator)]

    async def async_loom(call: ServiceCall) -> None:
        strength = float(call.data[ATTR_STRENGTH])
        for coordinator in _each():
            coordinator.loom(strength)
            await coordinator.async_request_refresh()

    async def async_feed(call: ServiceCall) -> None:
        amount = float(call.data[ATTR_AMOUNT])
        for coordinator in _each():
            coordinator.feed(amount)
            await coordinator.async_request_refresh()

    async def async_reset_memory(call: ServiceCall) -> None:
        for coordinator in _each():
            coordinator.brain.kc_mbon_gain[:] = 1.0
            await coordinator.async_save_state()
        _LOGGER.info("HouseFly memory reset -- every learned synapse back to measured strength")

    for name, handler, schema in (
        (SERVICE_LOOM, async_loom, LOOM_SCHEMA),
        (SERVICE_FEED, async_feed, FEED_SCHEMA),
        (SERVICE_RESET_MEMORY, async_reset_memory, None),
    ):
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator: FlyHouseCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.reconfigure(_merged(entry))
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: FlyHouseCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_save_state()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not any(isinstance(c, FlyHouseCoordinator) for c in hass.data[DOMAIN].values()):
            for name in (SERVICE_LOOM, SERVICE_FEED, SERVICE_RESET_MEMORY):
                if hass.services.has_service(DOMAIN, name):
                    hass.services.async_remove(DOMAIN, name)
    return unloaded
