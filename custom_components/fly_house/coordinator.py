"""Wires a house into a fly, and a fly into a house.

The interesting part of this file is the mapping, not the plumbing. Every input
is delivered to the neurons that in the real animal carry that kind of
information -- brightness to ring neurons as a bearing, not as a number; a
sudden motion event to LPLC2 as a looming stimulus, not as a boolean; the actual
time of day to the actual clock cells. The brain is then left alone to do what
it does, and we read its motor output the way an experimenter would.

Angular velocity closes the loop: the fly's own steering command is fed back as
self-motion on the next tick, so the compass is tracking movement the fly
itself produced. That feedback is the difference between a heading signal and
a heading *estimate*, and it is why the bump drifts if the fly cannot see a
landmark, exactly as a real one does.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
from datetime import timedelta
from typing import Any

import numpy as np
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .circuits import FlyBrain, Senses, shared_connectome
from .const import (
    CONF_ACTUATION_ENABLED,
    CONF_HOURLY_BUDGET,
    CONF_INPUT_ENTITIES,
    CONF_OUTPUT_ENTITIES,
    CONF_QUIET_HOURS_END,
    CONF_QUIET_HOURS_START,
    CONF_TICK_INTERVAL,
    DEFAULT_HOURLY_BUDGET,
    DEFAULT_TICK_INTERVAL,
    DOMAIN,
)
from .safety import ActuationGovernor, describe_action

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}_state"

# Numeric state domains we can read a "brightness" from for phototaxis.
LIGHT_DOMAINS = ("light",)
MOTION_CLASSES = ("motion", "occupancy", "moving", "vibration")

# Proportional gain of the goal-seeking controller. Explicitly a controller:
# see the comment in _build_senses.
GOAL_GAIN = 1.2


def _stable_channel(entity_id: str, channels: int) -> int:
    """Assign an entity to a projection-neuron channel, stably.

    Which odour lands in which glomerulus is arbitrary in a real fly too -- it
    is set by which receptor a neuron happens to express. What matters is that
    it never changes, so the mushroom body can learn about it.
    """
    digest = hashlib.blake2b(entity_id.encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") % max(channels, 1)


def _numeric(state: State | None) -> float:
    """Squash any HA state into 0..1 for use as a sensory magnitude."""
    if state is None or state.state in ("unknown", "unavailable", "", None):
        return 0.0
    raw = state.state
    if raw in ("on", "home", "open", "unlocked", "true", "playing"):
        return 1.0
    if raw in ("off", "not_home", "closed", "locked", "false", "idle", "standby"):
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.35
    # Percentages, temperatures and lux all land somewhere sane under a squash.
    return float(np.clip(math.tanh(abs(value) / 60.0), 0.0, 1.0))


class FlyHouseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Runs the brain, feeds it the house, and lets it act -- carefully."""

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any], entry_id: str) -> None:
        self.entry_id = entry_id
        self.brain = FlyBrain()
        self.governor = ActuationGovernor()
        self._apply_config(entry_data)

        # The fly lives in a unit square. When a dashboard reports its layout
        # that square is the viewport; otherwise it is an abstract room.
        self.pos = np.array([0.5, 0.5], dtype=np.float64)
        self._layout: list[dict[str, Any]] = []
        self._viewport = (1920.0, 1080.0)
        self._pending_loom = 0.0
        self._pending_reward = 0.0
        self._pending_punishment = 0.0
        self._last_motion_on: set[str] = set()
        self._last_turn = 0.0
        self._goal_entity: str | None = None
        self._goal_bearing = 0.0
        self._actions: list[dict[str, Any]] = []
        self._birth = dt_util.utcnow()

        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(1, self._tick_interval)),
        )

    # ----------------------------------------------------------------- config
    def _apply_config(self, entry_data: dict[str, Any]) -> None:
        self.input_entities: list[str] = list(entry_data.get(CONF_INPUT_ENTITIES, []))
        self.output_entities: list[str] = list(entry_data.get(CONF_OUTPUT_ENTITIES, []))
        self._tick_interval = int(entry_data.get(CONF_TICK_INTERVAL, DEFAULT_TICK_INTERVAL))

        self.governor.enabled = bool(entry_data.get(CONF_ACTUATION_ENABLED, False))
        self.governor.allowlist = {
            e for e in self.output_entities
            if ActuationGovernor.vet_entity(e).allowed
        }
        self.governor.max_calls_per_hour = int(
            entry_data.get(CONF_HOURLY_BUDGET, DEFAULT_HOURLY_BUDGET)
        )
        start = entry_data.get(CONF_QUIET_HOURS_START)
        end = entry_data.get(CONF_QUIET_HOURS_END)
        self.governor.quiet_hours = (int(start), int(end)) if start is not None and end is not None else None

        refused = set(self.output_entities) - self.governor.allowlist
        if refused:
            _LOGGER.warning(
                "HouseFly refused %d configured output(s) on safety grounds: %s",
                len(refused), ", ".join(sorted(refused)),
            )

    def reconfigure(self, entry_data: dict[str, Any]) -> None:
        self._apply_config(entry_data)
        self.update_interval = timedelta(seconds=max(1, self._tick_interval))

    # -------------------------------------------------------------- stimuli
    def loom(self, strength: float = 1.0) -> None:
        """Something rushed at the fly. This is what LPLC2 exists to detect."""
        self._pending_loom = max(self._pending_loom, float(strength))
        self._pending_punishment = max(self._pending_punishment, float(strength) * 0.7)

    def feed(self, amount: float = 1.0) -> None:
        """Sugar. Drives the PAM dopaminergic neurons, which is what makes a
        memory positive rather than merely strong."""
        self._pending_reward = max(self._pending_reward, float(amount))
        self.brain.hunger = max(0.0, self.brain.hunger - float(amount) * 0.6)

    def set_layout(self, cards: list[dict[str, Any]], viewport: dict[str, Any] | None) -> None:
        self._layout = cards
        if viewport:
            self._viewport = (float(viewport["w"]) or 1.0, float(viewport["h"]) or 1.0)

    # ----------------------------------------------------------------- sense
    def _build_senses(self) -> Senses:
        now = dt_util.now()
        senses = Senses()
        senses.time_of_day = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0

        states = {eid: self.hass.states.get(eid) for eid in self.input_entities}

        # --- odour: the house's chemical signature ---------------------------
        channels = len(self.brain.i_pn)
        if channels:
            odour = np.zeros(channels, dtype=np.float32)
            for eid, st in states.items():
                odour[_stable_channel(eid, channels)] += _numeric(st)
            senses.odour = np.clip(odour, 0.0, 1.5)

        # --- looming: something moved suddenly -------------------------------
        motion_now = set()
        for eid, st in states.items():
            if st is None or st.state != "on":
                continue
            if st.attributes.get("device_class") in MOTION_CLASSES:
                motion_now.add(eid)
        fresh = motion_now - self._last_motion_on
        self._last_motion_on = motion_now
        senses.looming = max(self._pending_loom, 0.9 if fresh else 0.0)
        self._pending_loom = 0.0

        # --- teaching signals ------------------------------------------------
        senses.reward = self._pending_reward
        senses.punishment = self._pending_punishment
        self._pending_reward = 0.0
        self._pending_punishment = 0.0

        # --- landmarks: bearings to things the fly can see --------------------
        senses.landmarks = self._landmarks()

        # --- goal: where it currently wants to be ----------------------------
        bearing, strength, target = self._choose_goal(states)
        senses.goal_bearing = bearing
        senses.goal_strength = strength
        self._goal_bearing = bearing
        self._goal_entity = target

        # --- self-motion --------------------------------------------------
        # Two things are added together here, and they are not the same kind of
        # thing.
        #
        # The first is the fly's own PFL3 steering command from last tick, fed
        # back as self-motion. That feedback is what turns the compass into a
        # heading *estimate* rather than a readout of an angle we handed it,
        # and it is why the bump drifts when the fly cannot see a landmark,
        # exactly as a real one does.
        #
        # The second is an explicit goal-seeking controller. It is not
        # biology. The real animal does this with PFL3, and this model does not
        # reproduce that computation reliably -- see the note in circuits.py.
        # So the fly holds a heading using a connectome-derived ring attractor,
        # which is real, and chooses which heading to hold using four lines of
        # proportional control, which is not. Keeping the two visibly separate
        # is the point.
        pfl3 = self._last_turn * 3.0
        error = math.atan2(
            math.sin(self._goal_bearing - self.brain.heading),
            math.cos(self._goal_bearing - self.brain.heading),
        )
        controller = GOAL_GAIN * error * senses.goal_strength
        senses.angular_velocity = float(np.clip(pfl3 + controller, -2.0, 2.0))

        return senses

    def _landmarks(self) -> list[tuple[float, float]]:
        """Bearings to the cards on screen, or to lit lights if there is no UI."""
        out: list[tuple[float, float]] = []
        if self._layout:
            vw, vh = self._viewport
            fx, fy = self.pos[0] * vw, self.pos[1] * vh
            for card in self._layout[:24]:
                cx = card["x"] + card["w"] * 0.5
                cy = card["y"] + card["h"] * 0.5
                dx, dy = cx - fx, cy - fy
                dist = math.hypot(dx, dy)
                if dist < 1.0:
                    continue
                # Nearer cards subtend a larger visual angle, so they are a
                # stronger stimulus. That is just optics.
                size = math.hypot(card["w"], card["h"])
                out.append((math.atan2(dy, dx) % (2 * math.pi),
                            float(np.clip(size / dist * 0.35, 0.02, 1.0))))
            return out

        for state in self.hass.states.async_all():
            if state.domain in LIGHT_DOMAINS and state.state == "on":
                brightness = (state.attributes.get("brightness") or 180) / 255.0
                angle = _stable_channel(state.entity_id, 360) * math.pi / 180.0
                out.append((angle, float(brightness)))
                if len(out) >= 16:
                    break
        return out

    def _choose_goal(self, states: dict[str, State | None]) -> tuple[float, float, str | None]:
        """Pick something to walk towards.

        A hungry fly goes to the brightest thing it can see. A fly that has
        learned something good about a place goes there instead. With nothing
        to go on it wanders, which is a real behaviour and not a fallback.
        """
        if not self._layout:
            return 0.0, 0.25 + 0.4 * self.brain.hunger, None

        vw, vh = self._viewport
        fx, fy = self.pos[0] * vw, self.pos[1] * vh
        best = None
        best_score = -1e9
        for card in self._layout:
            entity = card.get("entity")
            st = self.hass.states.get(entity) if entity else None
            appeal = _numeric(st) if st else 0.15
            if entity and entity in self.governor.allowlist:
                appeal += 0.3          # things it can actually play with
            appeal += self.brain.valence * 0.5
            cx = card["x"] + card["w"] * 0.5
            cy = card["y"] + card["h"] * 0.5
            dist = max(60.0, math.hypot(cx - fx, cy - fy))
            score = appeal * (1.0 + self.brain.hunger) - dist / max(vw, vh)
            if score > best_score:
                best_score, best = score, (cx, cy, entity)
        if best is None:
            return 0.0, 0.3, None
        cx, cy, entity = best
        return (math.atan2(cy - fy, cx - fx) % (2 * math.pi),
                float(np.clip(0.3 + 0.5 * self.brain.hunger, 0.0, 1.0)),
                entity)

    # ------------------------------------------------------------------ tick
    async def async_settle(self) -> None:
        """Let the homeostatic gains converge before the first real tick.

        Takes a couple of seconds of CPU, so it runs in an executor rather than
        on the event loop. Without it the first few minutes after a restart have
        half the circuits either silent or saturated, which looks exactly like a
        broken model.
        """
        now = dt_util.now()
        time_of_day = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
        await self.hass.async_add_executor_job(self.brain.settle, time_of_day)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            senses = self._build_senses()
            sub_steps = int(np.clip(self._tick_interval * 20, 10, 60))
            result = await self.hass.async_add_executor_job(
                self.brain.step, senses, sub_steps
            )

            self._last_turn = float(result["turn"])
            self._advance_position(result)

            self.brain.hunger = float(np.clip(
                self.brain.hunger + 0.0006 * self._tick_interval, 0.0, 1.0
            ))

            await self._maybe_act(result)

            if self.brain.tick % 40 == 0:
                await self.async_save_state()

            result["position"] = [round(float(self.pos[0]), 4), round(float(self.pos[1]), 4)]
            result["hunger"] = round(self.brain.hunger, 3)
            result["goal_entity"] = self._goal_entity
            result["landmarks"] = len(senses.landmarks)
            result["safety"] = self.governor.stats
            result["recent_actions"] = self._actions[-5:]
            result["age_seconds"] = int((dt_util.utcnow() - self._birth).total_seconds())
            return result
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"HouseFly tick failed: {err}") from err

    def _advance_position(self, result: dict[str, Any]) -> None:
        """Move the body the way the motor output says to."""
        heading = float(result["heading"])
        speed = float(result["speed"]) * (1.0 + 4.0 * float(result["escape"]))
        step = speed * 0.02 * self._tick_interval
        self.pos[0] += math.cos(heading) * step
        self.pos[1] += math.sin(heading) * step
        # Reflect off the walls rather than clamping, so it does not stick.
        for axis in (0, 1):
            if self.pos[axis] < 0.02:
                self.pos[axis] = 0.04 - self.pos[axis]
            elif self.pos[axis] > 0.98:
                self.pos[axis] = 1.96 - self.pos[axis]
        np.clip(self.pos, 0.0, 1.0, out=self.pos)

    # ---------------------------------------------------------------- action
    async def _maybe_act(self, result: dict[str, Any]) -> None:
        """A fly changes something by landing on it, not by ticking.

        The gate is deliberately narrow: it has to be settled (not flying, not
        escaping), it has to be on top of the thing, and the governor still has
        to agree. In practice that is a few interactions an hour.
        """
        if not self.governor.enabled or not self._layout:
            return
        if result["mode"] in ("escape", "sleep") or result["speed"] > 0.3:
            return

        entity = self._entity_under_fly()
        if entity is None or entity not in self.governor.allowlist:
            return

        # What it does is set by how it feels about the place: a positive
        # mushroom-body valence turns things up, a negative one turns them down.
        value = float(np.clip(0.5 + 0.5 * result["valence"] + 0.2 * (result["arousal"] - 0.5), 0.05, 1.0))

        local_hour = dt_util.now().hour
        verdict = self.governor.check(entity, value, local_hour)
        if not verdict.allowed:
            self.governor.record_block()
            _LOGGER.debug("HouseFly wanted %s -> %.2f but: %s", entity, value, verdict.reason)
            return

        action = describe_action(entity, value)
        if action is None:
            return
        domain, service = action["service"].split(".", 1)
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity, **action["data"]}, blocking=False
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HouseFly failed to act on %s", entity)
            return

        self.governor.record(entity, value)
        self._actions.append({
            "entity": entity,
            "service": action["service"],
            "value": round(value, 3),
            "at": dt_util.utcnow().isoformat(),
        })
        self._actions = self._actions[-30:]
        _LOGGER.info("HouseFly landed on %s and set it to %.0f%%", entity, value * 100)

    def _entity_under_fly(self) -> str | None:
        vw, vh = self._viewport
        fx, fy = self.pos[0] * vw, self.pos[1] * vh
        for card in self._layout:
            if (card["x"] <= fx <= card["x"] + card["w"]
                    and card["y"] <= fy <= card["y"] + card["h"]):
                return card.get("entity")
        return None

    # -------------------------------------------------------------- frontend
    def frontend_state(self) -> dict[str, Any]:
        data = self.data or {}
        return {
            "heading": self.brain.heading,
            "turn": self.brain.turn,
            "speed": self.brain.speed,
            "mode": data.get("mode", "groom"),
            "escape": data.get("escape", 0.0),
            "valence": data.get("valence", 0.0),
            "arousal": data.get("arousal", 0.5),
            "hunger": round(self.brain.hunger, 3),
            "kc_active": data.get("kc_active", 0),
            "memory_depression": data.get("memory_depression", 0.0),
            "compass": self.brain.compass_profile(),
            "goal_entity": self._goal_entity,
            "tick": self.brain.tick,
        }

    def connectome_geometry(self) -> dict[str, Any]:
        """Static geometry for the connectome card, sent once.

        Neurons whose hemibrain type has no FlyWire counterpart have no measured
        soma position. Rather than drop them, they are placed at their circuit's
        centroid with a little scatter, and the count of those is reported so
        the figure is not quietly overstating what is real.
        """
        data = shared_connectome()
        pos = data.pos.copy()
        missing = np.isnan(pos[:, 0])
        groups = np.asarray(data.groups)
        rng = np.random.default_rng(7)
        for group in np.unique(groups):
            in_group = groups == group
            have = in_group & ~missing
            if not np.any(have):
                continue
            centroid = pos[have].mean(axis=0)
            spread = np.nanstd(pos[have], axis=0) * 0.4 + 1.0
            need = in_group & missing
            pos[need] = centroid + rng.normal(0.0, 1.0, (int(need.sum()), 3)) * spread

        return {
            "n": int(data.n),
            "n_connections": int(len(data.pre)),
            "positions": base64.b64encode(
                np.ascontiguousarray(pos, dtype=np.float32).tobytes()
            ).decode("ascii"),
            "groups": list(data.groups),
            "types": list(data.types),
            "transmitters": list(data.transmitters),
            "estimated_positions": int(missing.sum()),
            "sources": data.sources,
        }

    # ------------------------------------------------------------ persistence
    async def async_save_state(self) -> None:
        """Persist what the fly has learned, not just what it is doing.

        The KC->MBON gains *are* the memory. Losing them on restart would mean
        a fly that forgets your house every time Home Assistant updates.
        """
        try:
            await self._store.async_save({
                "hunger": float(self.brain.hunger),
                "birth": self._birth.isoformat(),
                "tick": int(self.brain.tick),
                "position": [float(self.pos[0]), float(self.pos[1])],
                "kc_mbon_gain": base64.b64encode(
                    self.brain.kc_mbon_gain.astype(np.float32).tobytes()
                ).decode("ascii"),
            })
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("HouseFly could not save state: %s", err)

    async def async_restore_state(self) -> None:
        try:
            saved = await self._store.async_load()
            if not saved:
                return
            self.brain.hunger = float(saved.get("hunger", 0.2))
            self.brain.tick = int(saved.get("tick", 0))
            if saved.get("birth"):
                self._birth = dt_util.parse_datetime(saved["birth"]) or self._birth
            if saved.get("position"):
                self.pos = np.asarray(saved["position"], dtype=np.float64)
            blob = saved.get("kc_mbon_gain")
            if blob:
                gains = np.frombuffer(base64.b64decode(blob), dtype=np.float32)
                if gains.shape == self.brain.kc_mbon_gain.shape:
                    self.brain.kc_mbon_gain = gains.copy()
                    _LOGGER.info(
                        "HouseFly restored %d learned synapses (mean depression %.1f%%)",
                        len(gains), (1.0 - float(gains.mean())) * 100,
                    )
                else:
                    _LOGGER.warning(
                        "HouseFly memory was saved for a different connectome "
                        "(%d synapses, now %d) -- starting naive",
                        len(gains), len(self.brain.kc_mbon_gain),
                    )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("HouseFly had nothing to restore: %s", err)
