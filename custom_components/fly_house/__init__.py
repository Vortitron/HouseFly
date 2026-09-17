"""Fly House — let a fruit fly (toy reservoir) control your house."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from .const import (
    ATTR_STRENGTH,
    DEFAULT_POKE_STRENGTH,
    DOMAIN,
    SERVICE_POKE,
)
from .coordinator import FlyHouseCoordinator

_LOGGER = logging.getLogger(__name__)

POKE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_STRENGTH, default=DEFAULT_POKE_STRENGTH): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=5.0)
        ),
    }
)


def _merged_entry_data(entry: ConfigEntry) -> dict[str, Any]:
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fly House from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = FlyHouseCoordinator(hass, _merged_entry_data(entry), entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.BINARY_SENSOR, Platform.SENSOR]
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def async_poke(call: ServiceCall) -> None:
        strength = call.data.get(ATTR_STRENGTH, DEFAULT_POKE_STRENGTH)
        for coord in hass.data[DOMAIN].values():
            if isinstance(coord, FlyHouseCoordinator):
                coord.poke(float(strength))
                await coord.async_request_refresh()
        _LOGGER.info("Fly House poked with strength=%s", strength)

    # Register once
    if not hass.services.has_service(DOMAIN, SERVICE_POKE):
        hass.services.async_register(
            DOMAIN, SERVICE_POKE, async_poke, schema=POKE_SCHEMA
        )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator: FlyHouseCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.reconfigure(_merged_entry_data(entry))
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform.BINARY_SENSOR, Platform.SENSOR]
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_POKE):
            hass.services.async_remove(DOMAIN, SERVICE_POKE)
    return unload_ok
