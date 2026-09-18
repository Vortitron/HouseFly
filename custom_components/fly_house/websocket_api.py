"""Live brain streaming for the frontend.

Home Assistant's state machine is the wrong transport for this. A fly that
walks across a dashboard needs its position 20 times a second; writing that to
an entity would produce 1.7 million state changes a day, bloat the recorder
database, and fire every automation listening for state changes. So entities
keep reporting slow, meaningful things (mode, heading, what it learned) and the
fast visual stream goes over a websocket subscription straight to the card.

Two subscriptions are offered:

  fly_house/subscribe   behavioural state at the coordinator's tick rate --
                        heading, speed, turn, mode, valence. Small.
  fly_house/neurons     per-neuron activity for the connectome view. Sent as
                        base64 bytes, one byte per neuron, because 4,724 JSON
                        numbers per frame is 60 KB and this is 6 KB.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_neurons)
    websocket_api.async_register_command(hass, ws_layout)
    websocket_api.async_register_command(hass, ws_connectome)


def _coordinator(hass: HomeAssistant, entry_id: str | None):
    entries = hass.data.get(DOMAIN, {})
    coordinators = [c for k, c in entries.items() if hasattr(c, "brain")]
    if entry_id:
        candidate = entries.get(entry_id)
        return candidate if hasattr(candidate, "brain") else None
    return coordinators[0] if coordinators else None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fly_house/subscribe",
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_subscribe(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Stream behavioural state on every coordinator tick."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No HouseFly instance is running")
        return

    @callback
    def _forward() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], coordinator.frontend_state())
        )

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(_forward)
    connection.send_result(msg["id"])
    _forward()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fly_house/neurons",
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_neurons(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Stream quantised per-neuron activity for the connectome view."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No HouseFly instance is running")
        return

    @callback
    def _forward() -> None:
        activity = bytes(coordinator.brain.activity_snapshot())
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {
                    "tick": coordinator.brain.tick,
                    "activity": base64.b64encode(activity).decode("ascii"),
                },
            )
        )

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(_forward)
    connection.send_result(msg["id"])
    _forward()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fly_house/connectome",
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_connectome(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """One-shot: the static geometry the connectome view draws.

    Soma coordinates, circuit group and transmitter per neuron. Sent once on
    card load; only the activity bytes stream after that.
    """
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No HouseFly instance is running")
        return
    connection.send_result(msg["id"], coordinator.connectome_geometry())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fly_house/layout",
        vol.Required("cards"): [
            {
                vol.Required("entity"): vol.Any(str, None),
                vol.Required("x"): vol.Coerce(float),
                vol.Required("y"): vol.Coerce(float),
                vol.Required("w"): vol.Coerce(float),
                vol.Required("h"): vol.Coerce(float),
            }
        ],
        vol.Optional("viewport"): {
            vol.Required("w"): vol.Coerce(float),
            vol.Required("h"): vol.Coerce(float),
        },
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_layout(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The card tells the brain where the dashboard's cards are on screen.

    This is what makes the dashboard a place rather than a picture: each card
    becomes a landmark with a real bearing from the fly's position, and the
    ring neurons get driven by that bearing exactly as they would be by a
    stripe on an arena wall.
    """
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No HouseFly instance is running")
        return
    coordinator.set_layout(msg["cards"], msg.get("viewport"))
    connection.send_result(msg["id"], {"landmarks": len(msg["cards"])})
