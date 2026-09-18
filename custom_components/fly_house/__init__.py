"""HouseFly -- a connectome-constrained fruit fly living in Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    ATTR_AMOUNT,
    ATTR_STRENGTH,
    DEFAULT_FEED_AMOUNT,
    DEFAULT_LOOM_STRENGTH,
    DOMAIN,
    SERVICE_FEED,
    SERVICE_LOOM,
    SERVICE_RESET_MEMORY,
)
from .coordinator import FlyHouseCoordinator
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
