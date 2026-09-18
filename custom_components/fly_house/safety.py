"""What the fly is allowed to touch, and how often.

The previous version of HouseFly wrote a value to every configured output on
every tick -- 32 service calls every 10 seconds, forever, with values drawn
from what was effectively noise. On a real installation that is constant Zigbee
traffic, measurable relay wear, and an unbounded blast radius.

The model here is different in three ways:

  1. The fly has to *be somewhere* to touch something. Actuation happens when
     it lands on a device, not on a timer. A fly lands a few times a minute,
     not a hundred times a minute.
  2. Nothing is actuated unless the user put it on the allowlist, and whole
     domains are refused regardless of what the user puts there.
  3. Every call passes a rate budget and a deadband, so even a pathological
     brain state cannot produce a storm.

Default posture is observe-only: a fresh install drives nothing at all until
someone explicitly turns actuation on.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Domains the fly may never drive, whatever the configuration says. These are
# things that lock people in or out, burn energy, move heavy objects, or cost
# money -- none of them should answer to an insect.
FORBIDDEN_DOMAINS = frozenset({
    "lock",
    "alarm_control_panel",
    "cover",          # garage doors, blinds with pinch hazards
    "climate",
    "water_heater",
    "humidifier",
    "vacuum",
    "lawn_mower",
    "valve",
    "camera",
    "person",
    "device_tracker",
    "update",
    "notify",
    "script",
    "automation",
    "scene",
    "input_boolean",  # frequently wired into automations that do real things
})

# Domains the fly may drive if explicitly allowlisted.
ALLOWED_DOMAINS = frozenset({"light", "switch", "fan", "input_number", "number", "media_player"})

# Entities whose name suggests they matter, refused even inside an allowed
# domain. Cheap, but it catches the realistic accidents.
DANGEROUS_HINTS = (
    "boiler", "heater", "heating", "furnace", "immersion",
    "freezer", "fridge", "refrigerator",
    "pump", "sump", "well",
    "oven", "hob", "stove", "kettle",
    "server", "nas", "router", "modem", "network", "firewall",
    "alarm", "siren", "smoke", "security", "door", "gate", "garage",
    "medical", "oxygen", "cpap",
    "charger", "ev_", "car",
    "irrigation", "sprinkler",
)


@dataclass
class SafetyVerdict:
    allowed: bool
    reason: str = ""


@dataclass
class ActuationGovernor:
    """Rate-limits and sanity-checks everything the fly tries to do."""

    enabled: bool = False
    allowlist: set[str] = field(default_factory=set)
    max_calls_per_hour: int = 60
    min_seconds_between_calls_per_entity: float = 120.0
    deadband: float = 0.15
    quiet_hours: tuple[int, int] | None = None   # (start_hour, end_hour) local

    _recent: list[float] = field(default_factory=list, init=False)
    _last_per_entity: dict[str, float] = field(default_factory=dict, init=False)
    _last_value: dict[str, float] = field(default_factory=dict, init=False)
    _blocked_count: int = field(default=0, init=False)
    _allowed_count: int = field(default=0, init=False)

    # ------------------------------------------------------------------ vet
    @staticmethod
    def vet_entity(entity_id: str) -> SafetyVerdict:
        """Static check -- is this entity ever an acceptable target?

        Used by the config flow so bad choices are refused at setup time
        rather than silently ignored at runtime.
        """
        if "." not in entity_id:
            return SafetyVerdict(False, "not a valid entity id")
        domain = entity_id.split(".", 1)[0]
        if domain in FORBIDDEN_DOMAINS:
            return SafetyVerdict(False, f"the {domain} domain is never fly-controllable")
        if domain not in ALLOWED_DOMAINS:
            return SafetyVerdict(False, f"the {domain} domain is not supported as an output")
        lowered = entity_id.lower()
        for hint in DANGEROUS_HINTS:
            if hint in lowered:
                return SafetyVerdict(
                    False, f"name contains {hint!r}, which looks like something that matters"
                )
        return SafetyVerdict(True)

    # --------------------------------------------------------------- budget
    def _prune(self, now: float) -> None:
        cutoff = now - 3600.0
        self._recent = [t for t in self._recent if t >= cutoff]

    def check(self, entity_id: str, value: float, local_hour: int) -> SafetyVerdict:
        """Runtime check for one proposed actuation."""
        if not self.enabled:
            return SafetyVerdict(False, "actuation disabled (observe-only mode)")
        if entity_id not in self.allowlist:
            return SafetyVerdict(False, "not on the allowlist")

        verdict = self.vet_entity(entity_id)
        if not verdict.allowed:
            return verdict

        if self.quiet_hours:
            start, end = self.quiet_hours
            in_quiet = (start <= local_hour < end) if start < end \
                else (local_hour >= start or local_hour < end)
            if in_quiet:
                return SafetyVerdict(False, "inside quiet hours")

        now = time.monotonic()
        self._prune(now)
        if len(self._recent) >= self.max_calls_per_hour:
            return SafetyVerdict(False, f"hourly budget of {self.max_calls_per_hour} spent")

        last = self._last_per_entity.get(entity_id)
        if last is not None and (now - last) < self.min_seconds_between_calls_per_entity:
            wait = self.min_seconds_between_calls_per_entity - (now - last)
            return SafetyVerdict(False, f"cooling down for another {wait:.0f}s")

        # Deadband: do not issue a call that barely changes anything. This is
        # what stops a jittering brain state from producing a call storm even
        # when every other limit still has headroom.
        prev = self._last_value.get(entity_id)
        if prev is not None and abs(value - prev) < self.deadband:
            return SafetyVerdict(False, f"change of {abs(value - prev):.2f} is inside the deadband")

        return SafetyVerdict(True)

    def record(self, entity_id: str, value: float) -> None:
        """Commit an actuation against the budget. Call only after check passes."""
        now = time.monotonic()
        self._recent.append(now)
        self._last_per_entity[entity_id] = now
        self._last_value[entity_id] = value
        self._allowed_count += 1

    def record_block(self) -> None:
        self._blocked_count += 1

    # ------------------------------------------------------------ reporting
    @property
    def stats(self) -> dict[str, Any]:
        self._prune(time.monotonic())
        return {
            "enabled": self.enabled,
            "allowlisted_entities": sorted(self.allowlist),
            "calls_last_hour": len(self._recent),
            "hourly_budget": self.max_calls_per_hour,
            "total_actuations": self._allowed_count,
            "total_blocked": self._blocked_count,
        }


def describe_action(entity_id: str, value: float) -> dict[str, Any] | None:
    """Turn a [0,1] motor value into a service call for an allowed domain.

    Deliberately narrow: no domain gets a mapping here unless the worst case of
    getting it wrong is a light being the wrong brightness.
    """
    v = max(0.0, min(1.0, float(value)))
    domain = entity_id.split(".", 1)[0]
    if domain == "light":
        # A fly landing on a lamp nudges it, it does not black the room out.
        return {"service": "light.turn_on",
                "data": {"brightness_pct": max(5, int(round(v * 100)))}}
    if domain == "switch":
        return {"service": "switch.turn_on" if v >= 0.5 else "switch.turn_off", "data": {}}
    if domain == "fan":
        return {"service": "fan.set_percentage", "data": {"percentage": int(round(v * 100))}}
    if domain in ("number", "input_number"):
        return {"service": f"{domain}.set_value", "data": {"value": round(v * 100.0, 2)}}
    if domain == "media_player":
        return {"service": "media_player.volume_set",
                "data": {"volume_level": round(min(v, 0.6), 2)}}
    return None
