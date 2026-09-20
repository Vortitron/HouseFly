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
from dataclasses import dataclass
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
    CONF_APPROACH_ENTITIES,
    CONF_CLOCK_OFFSET,
    CONF_HOURLY_BUDGET,
    CONF_INPUT_ENTITIES,
    CONF_OUTPUT_ENTITIES,
    CONF_QUIET_HOURS_END,
    CONF_QUIET_HOURS_START,
    CONF_TICK_INTERVAL,
    CONF_WATCH_WHOLE_HOUSE,
    DEFAULT_HOURLY_BUDGET,
    DEFAULT_TICK_INTERVAL,
    MAX_WATCHED_ENTITIES,
    WATCHABLE_DOMAINS,
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

# Looming. LPLC2 responds to an object's image *expanding*, and for a target of
# size L at range r closing at speed v the angular size is theta ~ L/r, so the
# expansion rate is theta-dot = L*v/r^2. That r-squared is the whole character
# of the response: the same footstep counts for far more at one metre than at
# five, which is why a real fly leaves it so late and then goes all at once.
#
# A ranging sensor gives r directly and v by differencing, so this is the same
# quantity the circuit is built for, arriving by radar instead of by photons.
LOOM_SCALE = 0.45          # converts theta-dot into the drive LPLC2 expects
LOOM_MIN_RANGE = 0.35      # metres; closer than this the r^2 term blows up
LOOM_MAX_RANGE = 8.0       # metres; beyond this it is not looming at anything
LOOM_MAX_AGE = 6.0         # seconds; older readings cannot be differenced
DISTANCE_UNITS = {"cm": 0.01, "mm": 0.001, "m": 1.0, "km": 1000.0}

# Calling something unusual.
#
# The mushroom body reports how novel the house looks right now, and that is a
# per-tick figure that flickers. Saying "this is unusual" is a slower claim and
# needs two guards.
#
# NOVELTY_UNUSUAL   with time of day in the Kenyon code there are two kinds of
#                   strange and the line has to clear both. Measured over three
#                   patterns: familiar at most 0.029, the right house at the
#                   wrong hour at least 0.316, the wrong house at least 0.420.
#                   0.10 is the geometric middle of the narrower gap, so the
#                   margin either side is as wide as it can be.
#
#                   It used to be 0.35, from before the clock was in the code,
#                   and that number would now catch a strange house and miss a
#                   familiar one at three in the morning -- which is the case
#                   the context was added for.
# UNUSUAL_SECONDS   it has to stay there. A single odd tick is a sensor
#                   twitching; two minutes of it is the house being different.
# And the fly must have learned something first, or a fresh install cries wolf
# about a house it has never seen.
#
# That guard used to be a floor on the population-mean habituation, and it was
# a bad measure: only the active few per cent of Kenyon cells ever habituate, so
# the mean is bounded by the sparseness target and may simply never reach a
# fixed threshold. Measured on the demo it was 0.007 after an hour and 0.025
# after six, against a floor of 0.10 -- on that trajectory the alert might never
# have armed at all, and the feature would have been quietly dead.
#
# What actually has to be true is simpler and is not a magic number: the fly
# must at some point have found the house *familiar*. Until that has happened
# once, "this looks unfamiliar" carries no information, because everything does.
NOVELTY_UNUSUAL = 0.10
UNUSUAL_SECONDS = 120.0
FAMILIAR_ONCE = 0.5     # novelty below this means it has learned the place

# How long the fly has to stay on one thing before it will touch it.
#
# This replaces a speed threshold, which could not work. Forward speed here is
# essentially proportional to arousal, so "slow enough to have settled" and
# "awake" were mutually exclusive: an awake fly runs at 0.33 to 0.68 against a
# gate of 0.30, and every state that passed the gate was asleep and barred on
# mode instead. Dwell says what that gate was trying to say and says it in
# terms of where the fly is standing rather than how fast it is going. Two
# ticks at the default interval is about four seconds.
DWELL_TICKS = 2

# How long a dashboard's reported layout stays believable after the last report.
#
# The card rescans every four seconds while it is open, so silence past a few of
# those means the browser has gone. Without an expiry the flag saying "the card
# owns the body" was set once and never cleared, so closing the tab froze the
# fly where it stood -- permanently, because the coordinator had stopped
# integrating its position and nothing told it to start again. The stale card
# rectangles also stopped the headless fallback from engaging.
LAYOUT_TTL = 30.0

# Learning where this house's dawn and dusk actually are.
#
# A fixed 06:00/18:43 is nobody's daylight, and at this latitude it is not even
# close for most of the year. So watch the light and learn the crossings.
#
# PHOTOPERIOD_RATE is per observed transition, not per tick: roughly a week of
# days to move most of the way to a new schedule, which is about how fast a
# real fly's peaks track a changing photoperiod and is slow enough that one
# evening of working late in the kitchen does not redefine dusk.
LIGHT_ON = 0.55            # fraction of the learned range that counts as "day"
LIGHT_OFF = 0.35           # lower, so a flickering reading cannot ring the bell
PHOTOPERIOD_RATE = 0.18

# How long a state change stays interesting, and how much it pulls.
NOVELTY_SECONDS = 90.0
NOVELTY_APPEAL = 0.8


def _clock_string(phase: float) -> str:
    """A fraction of a day as a wall-clock time, for people to read."""
    minutes = int(round((phase % 1.0) * 1440)) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _drag_phase(current: float, observed: float, rate: float) -> float:
    """Move a time-of-day towards another one, the short way round.

    Averaging times of day linearly is the classic way to decide that the mean
    of 23:50 and 00:10 is midday. Going round the circle avoids it.
    """
    delta = (observed - current + 0.5) % 1.0 - 0.5
    return (current + rate * delta) % 1.0


def _stable_channel(entity_id: str, channels: int) -> int:
    """Assign an entity to a projection-neuron channel, stably.

    Which odour lands in which glomerulus is arbitrary in a real fly too -- it
    is set by which receptor a neuron happens to express. What matters is that
    it never changes, so the mushroom body can learn about it.
    """
    digest = hashlib.blake2b(entity_id.encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") % max(channels, 1)


# Values that mean "this channel is telling you nothing".
DEAD_STATES = frozenset({"unknown", "unavailable", "none", ""})

# Binary-ish states worth pinning to the ends of the range rather than
# adapting, because their meaning does not drift.
TRUE_STATES = frozenset({"on", "home", "open", "unlocked", "true", "playing",
                         "above_horizon", "detected", "wet", "occupied"})
FALSE_STATES = frozenset({"off", "not_home", "closed", "locked", "false", "idle",
                          "standby", "below_horizon", "clear", "dry", "unoccupied"})


@dataclass
class SensoryAdaptation:
    """Per-entity gain control, the way a receptor neuron does it.

    A single fixed scale cannot serve a house. Measured on a real install, a
    tanh(value / 60) squash put seven temperatures spanning 11 to 25 degrees
    into a 0.2-wide band while a 2,840 W power sensor pinned at 1.0 and an
    electricity price of 0.43 arrived as 0.007. Two of those channels were
    effectively constants and the third had no resolution left.

    So each channel learns its own range instead, and reports where the current
    value sits inside it. Receptor neurons adapt their gain to the range of
    stimulus they actually receive, which is why you can see indoors and out;
    this is the same trick and it costs two floats per entity.

    The bounds relax slowly back towards the current value, so a one-off spike
    widens the range for a while and then stops flattening everything.
    """

    lo: float = 0.0
    hi: float = 0.0
    seen: int = 0

    RELAX = 0.002  # per observation; ~ half an hour at a 2 s tick

    def observe(self, value: float) -> float:
        if self.seen == 0:
            self.lo = self.hi = value
            self.seen = 1
            return 0.5
        self.seen += 1
        self.lo = min(self.lo, value)
        self.hi = max(self.hi, value)
        # Let stale extremes decay, or one cold night fixes the scale for ever.
        self.lo += (value - self.lo) * self.RELAX
        self.hi += (value - self.hi) * self.RELAX
        span = self.hi - self.lo
        if span < 1e-9:
            return 0.5
        return float(np.clip((value - self.lo) / span, 0.0, 1.0))


@dataclass
class Percept:
    """One reading, ready to be delivered to a projection neuron.

    `key` is what decides *which* glomerulus it goes to and `value` is how hard
    that glomerulus is driven. Splitting the two matters for states that are
    words rather than numbers: an odour's identity is carried by which neurons
    respond, not by how strongly one of them does. Squeezing room names onto a
    single channel by magnitude put 'Allrum' at 0.833 and 'Kitchen' at 0.825 --
    numerically almost the same smell. Giving them their own glomeruli makes
    them as different as they actually are.
    """

    key: str
    value: float
    live: bool


def _numeric(state: State | None, adaptation: dict[str, SensoryAdaptation] | None = None,
             entity_id: str = "") -> Percept:
    """Turn any Home Assistant state into a percept.

    A dead channel is not the same as a channel reading zero, and the
    difference is worth surfacing rather than silently feeding the brain
    nothing and calling it a smell.
    """
    if state is None:
        return Percept(entity_id, 0.0, False)
    raw = str(state.state).strip()
    lowered = raw.lower()
    if lowered in DEAD_STATES:
        return Percept(entity_id, 0.0, False)
    if lowered in TRUE_STATES:
        return Percept(entity_id, 1.0, True)
    if lowered in FALSE_STATES:
        return Percept(entity_id, 0.0, True)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        # A word. Its identity picks the glomerulus; it drives it fully.
        return Percept(f"{entity_id}={lowered}", 1.0, True)

    if adaptation is None:
        return Percept(entity_id, float(np.clip(value, 0.0, 1.0)), True)
    channel = adaptation.get(entity_id)
    if channel is None:
        channel = adaptation[entity_id] = SensoryAdaptation()
    # Note: no abs(). Minus fifteen degrees and plus fifteen are not the same
    # thing, and on a Swedish winter install that distinction is the signal.
    return Percept(entity_id, channel.observe(value), True)


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
        self._pending_vision = 0.0
        self._threat_bearing: float | None = None
        self._pending_reward = 0.0
        self._pending_punishment = 0.0
        self._last_motion_on: set[str] = set()
        self._last_turn = 0.0
        self._goal_entity: str | None = None
        self._goal_bearing = 0.0
        self._wander_bearing = 0.0
        self._unusual_since: float | None = None
        self._unusual = False
        self._ever_familiar = False
        # Learned photoperiod. Starts at the textbook 06:00/18:43 and moves to
        # wherever this house's light actually goes on and off.
        self._dawn_phase = 0.25
        self._dusk_phase = 0.78
        self._light = 0.0
        self._is_day: bool | None = None
        self._photoperiod_seen = 0
        self._position_from_card = False
        self._watched_cache: list[str] = list(self.input_entities)
        self._dwell_entity: str | None = None
        self._dwell_ticks = 0
        self._dwell_spent = False
        self._layout_at = 0.0
        # Where the body is pointing. The compass bump is an *estimate* of this
        # and cannot slew -- see the note on angular velocity in the README --
        # so steering has to be measured against the body, not against the
        # estimate, and the body lives in the card.
        self._body_heading = 0.0
        self._commanded_av = 0.0
        self._actions: list[dict[str, Any]] = []
        self._birth = dt_util.utcnow()
        # One adaptive gain channel per input entity.
        self._adaptation: dict[str, SensoryAdaptation] = {}
        self._ranges: dict[str, tuple[float, float]] = {}   # entity -> (metres, reading time)
        # The last looming computation, kept so it can be published as a sensor
        # rather than only consumed internally. See the Approach sensor.
        self._approach: dict[str, Any] = {
            "rate": 0.0, "entity": None, "range_m": None, "closing_ms": None,
        }
        self._dead_inputs: list[str] = []

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
        self._watch_whole_house = bool(entry_data.get(CONF_WATCH_WHOLE_HOUSE, False))
        # Fractions of a day, not hours, because that is what everything
        # downstream speaks.
        self._clock_offset = (float(entry_data.get(CONF_CLOCK_OFFSET, 0)) / 24.0) % 1.0
        # Ranging sensors -- mmWave radar, ultrasonic, BLE distance. Anything
        # that reports how far away a moving thing is.
        self.approach_entities: list[str] = list(entry_data.get(CONF_APPROACH_ENTITIES, []))
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

    def see(self, expansion: float, azimuth: float = 0.0) -> None:
        """Optic expansion from the card's visual front end.

        Kept apart from loom() on purpose. loom() is somebody hitting a button
        and it carries a punishment signal with it, because being swatted at
        ought to teach the fly something about where it was standing. This is
        the eye simply working, and an eye that punished the fly every time it
        saw anything would give it a uniformly miserable opinion of the world.

        The peak between ticks is what survives, not the latest value: the card
        reports around ten times a second and the brain thinks every two, so
        taking the most recent sample would usually mean sampling the moment
        after the interesting one.
        """
        value = float(expansion)
        if value > self._pending_vision:
            self._pending_vision = value
            self._threat_bearing = float(azimuth)

    def feed(self, amount: float = 1.0) -> None:
        """Sugar. Drives the PAM dopaminergic neurons, which is what makes a
        memory positive rather than merely strong."""
        self._pending_reward = max(self._pending_reward, float(amount))
        self.brain.hunger = max(0.0, self.brain.hunger - float(amount) * 0.6)

    def set_layout(self, cards: list[dict[str, Any]], viewport: dict[str, Any] | None,
                   fly: dict[str, Any] | None = None) -> None:
        self._layout = cards
        if viewport:
            self._viewport = (float(viewport["w"]) or 1.0, float(viewport["h"]) or 1.0)
        self._layout_at = dt_util.utcnow().timestamp()
        if fly:
            # Adopt the card's position. Two independent integrations of the
            # same body is one too many: the brain would be working out which
            # way the kitchen light is from somewhere the fly visibly is not.
            self.pos[0] = float(np.clip(fly["x"], 0.0, 1.0))
            self.pos[1] = float(np.clip(fly["y"], 0.0, 1.0))
            self._position_from_card = True
            # And which way it is pointing, for the same reason. The goal
            # controller has to measure its error against the heading the body
            # is actually holding, or it commands a turn the body already made
            # and never settles.
            if fly.get("heading") is not None:
                self._body_heading = float(fly["heading"]) % (2 * math.pi)

    def _watched(self) -> list[str]:
        """Everything the fly can smell this tick.

        Watching costs nothing and cannot break anything, so when whole-house
        mode is on this is most of the house -- which matters now that
        familiarity is the point: a novelty detector fed six sensors can only
        notice six kinds of strange.

        Touching is the opposite, and stays exactly where it was: an explicit,
        short, vetted list. The two are deliberately not the same question, and
        this is the only place that is allowed to blur the first one.
        """
        if not self._watch_whole_house:
            return self.input_entities
        chosen = list(self.input_entities)
        seen = set(chosen)
        for state in self.hass.states.async_all():
            if len(chosen) >= MAX_WATCHED_ENTITIES:
                break
            entity_id = state.entity_id
            if entity_id in seen:
                continue
            if entity_id.split(".", 1)[0] not in WATCHABLE_DOMAINS:
                continue
            # Its own entities are not news about the house, and feeding them
            # back would make the fly smell itself thinking.
            if entity_id.startswith(("sensor.housefly", "binary_sensor.housefly")):
                continue
            chosen.append(entity_id)
            seen.add(entity_id)
        # Sorted, because which glomerulus an entity lands in is decided by a
        # hash of its name and must not depend on the order Home Assistant
        # happens to return things in -- otherwise the mushroom body relearns
        # the house on every restart.
        return sorted(chosen)

    # ----------------------------------------------------------------- sense
    def _build_senses(self) -> Senses:
        self._expire_layout()
        now = dt_util.now()
        senses = Senses()
        senses.time_of_day = self._subjective_day(now)

        watched = self._watched()
        self._watched_cache = watched
        states = {eid: self.hass.states.get(eid) for eid in watched}

        # --- odour: the house's chemical signature ---------------------------
        channels = self.brain.n_odour_channels
        dead: list[str] = []
        if channels:
            odour = np.zeros(channels, dtype=np.float32)
            for eid, st in states.items():
                percept = _numeric(st, self._adaptation, eid)
                if not percept.live:
                    dead.append(eid)
                    continue
                odour[_stable_channel(percept.key, channels)] += percept.value
            senses.odour = np.clip(odour, 0.0, 1.5)
        self._dead_inputs = dead

        # --- looming: something moved suddenly -------------------------------
        #
        # Only entities somebody *listed*. Whole-house watching means "smell
        # everything", not "be startled by everything", and conflating the two
        # undoes the fix two sections down: a motion or occupancy flag arrives
        # as a flat 0.9, which is over the escape threshold on its own, so any
        # presence sensor derived from a ranging sensor fires the escape before
        # the graded looming pathway gets a look at it.
        #
        # Measured on the demo after whole-house watching went in: the sweep
        # pulled in binary_sensor.radar_presence and four simulated-occupancy
        # sensors, and the fly bolted three times per ninety-second cycle all
        # night instead of once per approach.
        #
        # Listing a motion sensor by hand says "startle the fly with this".
        # Sweeping the house says nothing of the kind.
        motion_now = set()
        for eid in self.input_entities:
            st = states.get(eid)
            if st is None or st.state != "on":
                continue
            if st.attributes.get("device_class") in MOTION_CLASSES:
                motion_now.add(eid)
        fresh = motion_now - self._last_motion_on
        self._last_motion_on = motion_now
        senses.looming = max(self._pending_loom,
                             self._pending_vision,
                             0.9 if fresh else 0.0,
                             self._approach_looming())
        self._pending_loom = 0.0
        self._pending_vision = 0.0

        # --- teaching signals ------------------------------------------------
        senses.reward = self._pending_reward
        senses.punishment = self._pending_punishment
        self._pending_reward = 0.0
        self._pending_punishment = 0.0

        # --- light, and where this house's day actually starts and ends -------
        senses.light = self._observe_light(states)
        senses.dawn_phase = self._dawn_phase
        senses.dusk_phase = self._dusk_phase

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
        # Measure the error against the body, not the bump. Using the compass
        # here is what kept the fly pinned: the bump shifts by a few tens of
        # degrees and then stops (it does not integrate a sustained turn), so
        # the error never closed and the commanded turn never changed sign. The
        # fly held one heading, crossed the screen, and sat against the edge.
        # Always the body, never the bump.
        #
        # This was conditional on a dashboard being open, and that made sense
        # when the headless path also flew on the compass heading. It does not
        # now: _advance_position integrates the commanded turn into
        # _body_heading, so measuring the error against brain.heading left the
        # controller nulling against one angle while the body flew on another.
        # They drift apart and the goal is never reached -- which is why the
        # headless fly still would not land even once it could steer.
        facing = self._body_heading
        error = math.atan2(
            math.sin(self._goal_bearing - facing),
            math.cos(self._goal_bearing - facing),
        )
        controller = GOAL_GAIN * error * senses.goal_strength
        senses.angular_velocity = float(np.clip(pfl3 + controller, -2.0, 2.0))
        self._commanded_av = senses.angular_velocity

        return senses

    def _approach_looming(self) -> float:
        """Turn ranging sensors into the expansion rate LPLC2 responds to.

        Only closing counts. Something walking away is not looming at anything,
        and a fly that startled at departures would be a poor fly.
        """
        strongest = 0.0
        detail: dict[str, Any] = {
            "rate": 0.0, "entity": None, "range_m": None, "closing_ms": None,
        }
        for entity_id in self.approach_entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            try:
                raw = float(state.state)
            except (TypeError, ValueError):
                self._ranges.pop(entity_id, None)
                continue
            unit = str(state.attributes.get("unit_of_measurement") or "m").lower()
            metres = raw * DISTANCE_UNITS.get(unit, 1.0)

            # Difference against the sensor's own timestamps, not against the
            # times we happened to look. A ranging sensor reports on its own
            # cadence, and our tick has no relation to it: a tick that straddles
            # a reading sees a whole sampling interval of movement but only one
            # tick of elapsed time, so the velocity comes out inflated by
            # whatever the ratio happens to be, while a tick that falls between
            # two readings sees no movement at all. Measured on the demo box at
            # a 5 s cadence and a 2 s tick, one approach produced escape at 4.0 m
            # and then nothing at 3.1 m or 2.2 m -- an ordering that is not
            # distance at all, it is sampling jitter.
            reading_at = state.last_changed.timestamp()
            previous = self._ranges.get(entity_id)
            if previous is not None and reading_at == previous[1]:
                continue                       # same reading; nothing new to difference
            self._ranges[entity_id] = (metres, reading_at)
            if previous is None:
                continue
            last_metres, last_at = previous
            dt = reading_at - last_at
            if dt <= 0.0 or dt > LOOM_MAX_AGE:
                continue
            if not (LOOM_MIN_RANGE <= metres <= LOOM_MAX_RANGE):
                continue

            closing = (last_metres - metres) / dt          # metres per second
            if closing <= 0.0:
                continue
            expansion = closing / (metres * metres)
            value = float(np.clip(expansion * LOOM_SCALE, 0.0, 3.0))
            if value >= strongest:
                strongest = value
                detail = {
                    "rate": round(expansion, 4),
                    "entity": entity_id,
                    "range_m": round(metres, 3),
                    "closing_ms": round(closing, 3),
                }
        self._approach = detail
        return strongest

    def _subjective_day(self, now) -> float:
        """What time of day it is *for this fly*, 0..1.

        With no offset this is the wall clock. With one, the fly's whole day
        moves: its clock drive, the hour it habituates against, and the phase
        it records when it sees dawn. Everything stays in one frame, so a night
        fly is not a day fly that has been told to stay up -- it has its own
        morning, and it has lived through hundreds of them.
        """
        wall = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
        return (wall + self._clock_offset) % 1.0

    def _expire_layout(self) -> None:
        """Forget a dashboard that has stopped reporting.

        The card rescans every four seconds while it is open, so silence past
        LAYOUT_TTL means the tab is gone and the coordinator has to take the
        body back. Nothing did that before, and the flag is one-way, so one
        visitor opening the demo once was enough to stop the fly moving for
        good.
        """
        if not self._layout:
            return
        if dt_util.utcnow().timestamp() - self._layout_at <= LAYOUT_TTL:
            return
        _LOGGER.debug("HouseFly: no dashboard for %.0fs, taking the body back", LAYOUT_TTL)
        self._layout = []
        self._position_from_card = False

    def _effective_layout(self) -> list[dict[str, Any]]:
        """Where the fly thinks things are.

        A browser with the dashboard open reports real card rectangles, and
        those are much the better answer: the fly is genuinely walking on the
        things you can see.

        With no browser open there is no layout at all, and that used to mean
        the fly could neither choose a goal nor land on anything -- the
        actuation gate returns early without one. Measured on the demo: zero
        actuations in eight hours of running, and nothing even reaching the
        safety layer to be refused. Correct by the letter of the code and
        useless, because a Home Assistant integration that only does anything
        while somebody is watching it is a screensaver.

        So when nobody is looking, the things it may touch are laid out on a
        notional grid and it walks among those instead. Same rules on top --
        it still has to settle, still has to be over one, the governor still
        has to agree.
        """
        if self._layout:
            return self._layout
        if not self.output_entities:
            return []
        vw, vh = self._viewport
        columns = max(1, int(math.ceil(math.sqrt(len(self.output_entities)))))
        rows = max(1, int(math.ceil(len(self.output_entities) / columns)))
        # Inset from the edges, so the wall-avoidance reflex is not permanently
        # arguing with a goal sitting in a corner.
        pad_x, pad_y = vw * 0.12, vh * 0.12
        cell_w = (vw - 2 * pad_x) / columns
        cell_h = (vh - 2 * pad_y) / rows
        grid: list[dict[str, Any]] = []
        for i, entity in enumerate(sorted(self.output_entities)):
            col, row = i % columns, i // columns
            grid.append({
                "entity": entity,
                "x": pad_x + col * cell_w,
                "y": pad_y + row * cell_h,
                "w": cell_w * 0.7,
                "h": cell_h * 0.7,
            })
        return grid

    def _landmarks(self) -> list[tuple[float, float]]:
        """Bearings to the cards on screen, or to lit lights if there is no UI."""
        out: list[tuple[float, float]] = []
        layout = self._effective_layout()
        if layout:
            vw, vh = self._viewport
            fx, fy = self.pos[0] * vw, self.pos[1] * vh
            for card in layout[:24]:
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

    def _observe_light(self, states: dict[str, State | None]) -> float:
        """Ambient light, 0..1, and the dawn/dusk times it implies.

        Any light-ish input will do: an illuminance sensor if the house has
        one, otherwise the sun's own position, which every install has. The
        level is adapted per channel like every other input, so a lux sensor
        reading 40,000 at noon and a percentage reading 90 both end up as
        "bright" without anyone configuring a scale.
        """
        best = None
        for entity_id in self._watched_cache:
            st = states.get(entity_id)
            if st is None:
                continue
            klass = st.attributes.get("device_class")
            if klass == "illuminance" or entity_id.startswith("sensor.light"):
                best = _numeric(st, self._adaptation, entity_id)
                break
        if best is None:
            sun = self.hass.states.get("sun.sun")
            if sun is not None:
                # Elevation rather than above/below the horizon: the boolean
                # steps, and a step tells you nothing about where dawn is
                # except on the tick it happens.
                elev = float(sun.attributes.get("elevation", 0.0) or 0.0)
                best = Percept("sun.sun", float(np.clip((elev + 6.0) / 24.0, 0.0, 1.0)), True)
        if best is None or not best.live:
            return self._light

        self._light = float(best.value)

        # A crossing, with hysteresis, is dawn or dusk.
        now = dt_util.now()
        phase = self._subjective_day(now)
        if self._is_day is None:
            self._is_day = self._light >= LIGHT_ON
        elif not self._is_day and self._light >= LIGHT_ON:
            self._is_day = True
            self._dawn_phase = _drag_phase(self._dawn_phase, phase, PHOTOPERIOD_RATE)
            self._photoperiod_seen += 1
            _LOGGER.debug("HouseFly saw dawn at %.3f; learned dawn now %.3f",
                          phase, self._dawn_phase)
        elif self._is_day and self._light <= LIGHT_OFF:
            self._is_day = False
            self._dusk_phase = _drag_phase(self._dusk_phase, phase, PHOTOPERIOD_RATE)
            self._photoperiod_seen += 1
            _LOGGER.debug("HouseFly saw dusk at %.3f; learned dusk now %.3f",
                          phase, self._dusk_phase)
        return self._light

    def _wander(self) -> float:
        """A heading to hold when there is nothing in particular to go to.

        This used to return 0.0, and 0.0 radians is not "no preference" -- it
        is due east. With a goal strength of 0.25 to 0.65 behind it, the
        controller then steered hard for due east and held it, so the fly flew
        to the right-hand edge of the screen and stayed there pressed against
        it. Two people reported that as "it just flies to the right and bounces
        off the side", which is exactly what it was.

        A wander is a slow random walk in heading, which is roughly what a fly
        does in still air with nothing to aim at: it keeps a heading for a
        while and then picks another.
        """
        self._wander_bearing += float(np.random.default_rng().normal(0.0, 0.25))
        self._wander_bearing %= 2 * math.pi
        return self._wander_bearing

    def _choose_goal(self, states: dict[str, State | None]) -> tuple[float, float, str | None]:
        """Pick something to walk towards.

        A hungry fly goes to the brightest thing it can see. A fly that has
        learned something good about a place goes there instead. With nothing
        to go on it wanders, which is a real behaviour and not a fallback.
        """
        layout = self._effective_layout()
        if not layout:
            return self._wander(), 0.25 + 0.4 * self.brain.hunger, None

        vw, vh = self._viewport
        fx, fy = self.pos[0] * vw, self.pos[1] * vh
        now = dt_util.utcnow()
        best = None
        best_score = -1e9
        for card in layout:
            entity = card.get("entity")
            st = self.hass.states.get(entity) if entity else None
            appeal = _numeric(st, self._adaptation, entity or "").value if st else 0.15

            # Something that just changed is worth going to look at. Novelty is
            # most of what makes a real animal's path look purposeful rather
            # than random, and without it the fly drifts towards whatever
            # happens to be brightest and then stays there for ever.
            if st is not None:
                age = (now - st.last_changed).total_seconds()
                if age < NOVELTY_SECONDS:
                    appeal += NOVELTY_APPEAL * (1.0 - age / NOVELTY_SECONDS)

            if entity and entity in self.governor.allowlist:
                appeal += 0.3          # things it can actually play with
            appeal += self.brain.valence * 0.5

            cx = card["x"] + card["w"] * 0.5
            cy = card["y"] + card["h"] * 0.5
            dist = max(60.0, math.hypot(cx - fx, cy - fy))
            # Somewhere it is already standing is not somewhere to travel to.
            if dist < 90.0:
                appeal -= 0.5
            score = appeal * (1.0 + self.brain.hunger) - dist / max(vw, vh)
            if score > best_score:
                best_score, best = score, (cx, cy, entity)
        if best is None:
            return self._wander(), 0.3, None
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
        time_of_day = self._subjective_day(now)
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
            # Whether those landmarks are real cards or the notional grid it
            # falls back to with no dashboard open. Worth distinguishing: one
            # of them is the fly walking on things you can see.
            result["seeing_dashboard"] = bool(self._layout)
            result["body_owner"] = "dashboard" if self._position_from_card else "coordinator"
            result["dwell"] = {"entity": self._dwell_entity, "ticks": self._dwell_ticks,
                               "spent": self._dwell_spent}
            result["safety"] = self.governor.stats
            result["dead_inputs"] = self._dead_inputs
            result["approach_sensors"] = len(self.approach_entities)
            result["approach"] = self._approach
            result["unusual"] = self._assess_novelty(result)
            result["photoperiod"] = {
                "shift_hours": round(self._clock_offset * 24.0, 1),
                "dawn": _clock_string(self._dawn_phase),
                "dusk": _clock_string(self._dusk_phase),
                "light": round(self._light, 3),
                "transitions_seen": self._photoperiod_seen,
                "daylight_hours": round(
                    ((self._dusk_phase - self._dawn_phase) % 1.0) * 24.0, 1),
            }
            result["goal_bearing_deg"] = round(math.degrees(self._goal_bearing), 1)
            result["live_inputs"] = len(self._watched_cache) - len(self._dead_inputs)
            result["watching"] = len(self._watched_cache)
            result["recent_actions"] = self._actions[-5:]
            result["age_seconds"] = int((dt_util.utcnow() - self._birth).total_seconds())
            return result
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"HouseFly tick failed: {err}") from err

    def _assess_novelty(self, result: dict[str, Any]) -> dict[str, Any]:
        """Turn the per-tick novelty figure into a claim worth making.

        This is the closest thing the fly has to a purpose, and it is not one
        that was grafted on: telling familiar from unfamiliar is what the
        mushroom body is *for*. It needs no training data, no labels and no
        cloud, because it is unsupervised by construction -- it learns what your
        house is like by living in it, and says so when the house stops looking
        like that.
        """
        novelty = float(result.get("novelty", 0.0))
        settled = float(result.get("settled", 0.0))
        now = dt_util.utcnow().timestamp()
        fired_before = self._unusual

        if novelty <= FAMILIAR_ONCE:
            self._ever_familiar = True
        if not self._ever_familiar:
            self._unusual_since = None
            self._unusual = False
            return {"unusual": False, "reason": "still learning what normal looks like",
                    "novelty": round(novelty, 4), "settled": round(settled, 4),
                    "learned_the_place": False, "for_seconds": 0}

        if novelty >= NOVELTY_UNUSUAL:
            if self._unusual_since is None:
                self._unusual_since = now
            held = now - self._unusual_since
            self._unusual = held >= UNUSUAL_SECONDS
        else:
            self._unusual_since = None
            self._unusual = False
            held = 0.0

        report = {
            "unusual": self._unusual,
            "novelty": round(novelty, 4),
            "settled": round(settled, 4),
            "learned_the_place": True,
            "for_seconds": int(held),
            "suspects": self._suspects() if self._unusual else [],
            "reason": ("the house does not look like itself" if self._unusual
                       else "nothing it has not seen before"),
        }

        # Fire once on the rising edge, not every tick. The point of this event
        # is to be the cheap thing that decides when to run the expensive thing:
        # a sparse hash ticking twice a second costs nothing, and asking a
        # language model to go and look at the whole house costs real money, so
        # let the fly decide when it is worth asking.
        if self._unusual and not fired_before:
            self.hass.bus.async_fire(f"{DOMAIN}_unusual", {
                **report,
                "entry_id": self.entry_id,
                "at": dt_util.utcnow().isoformat(),
            })
            _LOGGER.info(
                "HouseFly: something unusual (novelty %.2f for %ds); suspect channels %s",
                novelty, int(held), ", ".join(x["entity_id"] for x in report["suspects"]) or "none")
        return report

    def _suspects(self) -> list[dict[str, Any]]:
        """Which configured inputs the surprise is arriving through.

        Emphatically not "what is wrong". The Kenyon code is a hash and does
        not invert; this follows the measured PN->KC wiring backwards to the
        input channels feeding the cells that are active and have not
        habituated. Channels collide -- a random projection with more entities
        than glomeruli must -- so more than one entity can share a channel and
        all of them are listed.

        It is a shortlist for whatever looks next, which is the job.
        """
        channels = self.brain.n_odour_channels
        if not channels:
            return []
        by_channel: dict[int, list[str]] = {}
        for entity_id in self._watched_cache:
            by_channel.setdefault(_stable_channel(entity_id, channels), []).append(entity_id)
        out: list[dict[str, Any]] = []
        for channel, share in self.brain.novel_channels():
            for entity_id in by_channel.get(channel, []):
                st = self.hass.states.get(entity_id)
                out.append({
                    "entity_id": entity_id,
                    "state": st.state if st else None,
                    "share": share,
                })
        return out[:6]

    def _advance_position(self, result: dict[str, Any]) -> None:
        """Move the body the way the motor output says to.

        Skipped entirely while a dashboard is reporting where the fly is: the
        card integrates the same motion at display rate, and doing it twice
        makes the two disagree.
        """
        if self._position_from_card:
            return

        # Integrate the commanded turn, the same rule the card uses.
        #
        # This used to steer on result["heading"], the compass bump, and that
        # is the headless half of the bug fixed in the card a version ago: the
        # bump is an estimate that cannot slew, so the body flew one fixed
        # direction for ever, bouncing between walls on a billiard path that
        # never had to cross anything it could land on. Goal seeking could not
        # reach it, so with no dashboard open the fly had a goal, a grid to
        # stand on, and no way to steer towards either.
        self._body_heading = (
            self._body_heading + self._commanded_av * self._tick_interval
        ) % (2 * math.pi)
        heading = self._body_heading
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
        if not self.governor.enabled or not self._effective_layout():
            return
        if result["mode"] in ("escape", "sleep"):
            self._dwell_entity, self._dwell_ticks = None, 0
            self._dwell_spent = False
            return

        entity = self._entity_under_fly()
        if entity is None or entity not in self.governor.allowlist:
            self._dwell_entity, self._dwell_ticks = None, 0
            self._dwell_spent = False
            return

        # Landing, rather than passing overhead.
        if entity == self._dwell_entity:
            self._dwell_ticks += 1
        else:
            self._dwell_entity, self._dwell_ticks = entity, 1
            self._dwell_spent = False
        if self._dwell_ticks < DWELL_TICKS:
            return

        # One landing, one decision. Whether the governor says yes or no, this
        # visit is finished with -- the fly has to leave and come back before it
        # gets another opinion.
        #
        # Without this the counter reset after acting and re-armed two ticks
        # later on the same entity, so a fly that settled somewhere comfortable
        # asked again every four seconds for as long as it stayed. Measured on
        # the demo: three actions and a hundred and fifteen refusals in seven
        # minutes. The refusals were correct -- deadband and cooldown doing
        # their job -- but a safety layer being asked the same question a
        # hundred times is a safety layer whose log tells you nothing.
        if self._dwell_spent:
            return
        self._dwell_spent = True

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
        for card in self._effective_layout():
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
            # The angular velocity actually being commanded: the PFL3 steering
            # output plus the goal controller. This is what the body should
            # integrate, and it is a rate rather than a direction, which is the
            # whole difference from "heading" above.
            "turn_rate": round(float(self._commanded_av), 4),
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
                # The learned sensory ranges are part of what the fly knows
                # about the house; throwing them away every restart means it
                # spends its first half hour with no resolution on any channel.
                # Dawn and dusk take days to learn. Relearning them from
                # scratch after every Home Assistant update would mean never
                # actually having them.
                "photoperiod": [self._dawn_phase, self._dusk_phase,
                                self._photoperiod_seen],
                "ever_familiar": bool(self._ever_familiar),
                "adaptation": {
                    eid: [c.lo, c.hi, c.seen] for eid, c in self._adaptation.items()
                },
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
            self._ever_familiar = bool(saved.get("ever_familiar", False))
            if saved.get("photoperiod"):
                dawn, dusk, seen = saved["photoperiod"]
                self._dawn_phase, self._dusk_phase = float(dawn), float(dusk)
                self._photoperiod_seen = int(seen)
            for eid, (lo, hi, seen) in (saved.get("adaptation") or {}).items():
                self._adaptation[eid] = SensoryAdaptation(float(lo), float(hi), int(seen))

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
