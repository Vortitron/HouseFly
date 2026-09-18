#!/usr/bin/env python3
"""Generate a fake house for the HouseFly testbed.

Produces a Home Assistant package with enough rooms, lights, switches, sensors
and motion detectors to give the fly something to look at -- and deliberately
includes a handful of entities the safety layer must refuse, so that "the
refusal actually works" is something you can see rather than take on trust.

The config is built as Python structures and dumped with PyYAML rather than
assembled from strings. An earlier version concatenated YAML by hand and
emitted the long-removed `light: - platform: template` form, which parses
perfectly well as YAML and is rejected by Home Assistant at startup -- the kind
of mistake that only shows up when you actually boot the thing.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import yaml

ROOMS = [
    "kitchen", "living_room", "hallway", "bedroom", "bathroom",
    "study", "garage", "landing", "conservatory", "utility",
]
LIGHT_KINDS = ["ceiling", "lamp", "strip", "spots"]
APPLIANCES = ["fan", "humidifier_plug", "speaker_plug", "desk_socket", "lamp_socket"]

# Entities that exist purely so you can watch HouseFly refuse to touch them.
TRAPS = [
    ("boiler_relay", "Boiler Relay"),
    ("freezer_socket", "Freezer Socket"),
    ("network_rack", "Network Rack"),
    ("sump_pump", "Sump Pump"),
    ("garage_door_motor", "Garage Door Motor"),
    ("immersion_heater", "Immersion Heater"),
]

SENSOR_KINDS = [
    ("temperature", "°C", 16.0, 24.0, 0.4),
    ("humidity", "%", 35.0, 65.0, 0.6),
    ("illuminance", "lx", 0.0, 900.0, 40.0),
]


def title(slug: str) -> str:
    """Name whose Home Assistant slug is exactly `slug` again."""
    return slug.replace("_", " ").title()


def action(service: str, entity_id: str, data: dict[str, Any] | None = None) -> dict:
    step: dict[str, Any] = {"action": service, "target": {"entity_id": entity_id}}
    if data:
        step["data"] = data
    return step


def main() -> None:
    rng = random.Random(1975)
    here = Path(__file__).parent
    out = here / "config" / "packages"
    out.mkdir(parents=True, exist_ok=True)

    booleans: dict[str, dict] = {}
    numbers: dict[str, dict] = {}
    lights: list[dict] = []
    switches: list[dict] = []
    sensors: list[dict] = []
    binaries: list[dict] = []
    light_slugs: list[str] = []
    switch_slugs: list[str] = []
    motion_slugs: list[str] = []

    for room in ROOMS:
        for kind in rng.sample(LIGHT_KINDS, rng.randint(1, 3)):
            slug = f"{room}_{kind}"
            light_slugs.append(slug)
            booleans[f"{slug}_light"] = {"name": f"{title(slug)} light helper"}
            numbers[f"{slug}_brightness"] = {
                "name": f"{title(slug)} brightness",
                "min": 0, "max": 100, "step": 1,
                "initial": rng.randint(0, 100),
            }
            lights.append({
                "name": title(slug),
                "unique_id": f"fake_{slug}",
                "state": f"{{{{ is_state('input_boolean.{slug}_light', 'on') }}}}",
                "level": (f"{{{{ (states('input_number.{slug}_brightness') "
                          f"| float(0) * 2.55) | round(0) }}}}"),
                "turn_on": [action("input_boolean.turn_on", f"input_boolean.{slug}_light")],
                "turn_off": [action("input_boolean.turn_off", f"input_boolean.{slug}_light")],
                "set_level": [action(
                    "input_number.set_value", f"input_number.{slug}_brightness",
                    {"value": "{{ (brightness / 2.55) | round(0) }}"},
                )],
            })

        for appliance in rng.sample(APPLIANCES, rng.randint(1, 2)):
            slug = f"{room}_{appliance}"
            switch_slugs.append(slug)
            booleans[f"{slug}_sw"] = {"name": f"{title(slug)} helper"}
            switches.append({
                "name": title(slug),
                "unique_id": f"fake_{slug}",
                "state": f"{{{{ is_state('input_boolean.{slug}_sw', 'on') }}}}",
                "turn_on": [action("input_boolean.turn_on", f"input_boolean.{slug}_sw")],
                "turn_off": [action("input_boolean.turn_off", f"input_boolean.{slug}_sw")],
            })

        for device_class, unit, lo, hi, jitter in SENSOR_KINDS:
            slug = f"{room}_{device_class}"
            centre = round(rng.uniform(lo, hi), 1)
            sensors.append({
                "name": title(slug),
                "unique_id": f"fake_{slug}",
                "device_class": device_class,
                "unit_of_measurement": unit,
                "state_class": "measurement",
                # Mean-reverting random walk. A plain walk wanders off over a
                # few hours and the testbed ends up reporting -40 in the kitchen.
                "state": (
                    f"{{% set now_value = states('sensor.{slug}') | float({centre}) %}}"
                    f"{{% set drift = range(-100, 101) | random / 100 * {jitter} %}}"
                    f"{{{{ (now_value + drift + ({centre} - now_value) * 0.05) | round(2) }}}}"
                ),
            })

        for device_class in (["motion", "door"] if rng.random() < 0.4 else ["motion"]):
            slug = f"{room}_{device_class}"
            if device_class == "motion":
                motion_slugs.append(slug)
            booleans[f"{slug}_trigger"] = {"name": f"{title(slug)} trigger"}
            binaries.append({
                "name": title(slug),
                "unique_id": f"fake_{slug}",
                "device_class": device_class,
                "state": f"{{{{ is_state('input_boolean.{slug}_trigger', 'on') }}}}",
            })

    for slug, name in TRAPS:
        switch_slugs.append(slug)
        booleans[f"{slug}_sw"] = {"name": f"{name} helper"}
        switches.append({
            "name": name,
            "unique_id": f"fake_{slug}",
            "state": f"{{{{ is_state('input_boolean.{slug}_sw', 'on') }}}}",
            "turn_on": [action("input_boolean.turn_on", f"input_boolean.{slug}_sw")],
            "turn_off": [action("input_boolean.turn_off", f"input_boolean.{slug}_sw")],
        })

    package = {
        "input_boolean": booleans,
        "input_number": numbers,
        # Everything template-based lives under the one `template:` key. The
        # per-platform `light: - platform: template` form was removed.
        "template": [
            {"light": lights},
            {"switch": switches},
            {"trigger": [{"trigger": "time_pattern", "seconds": "/10"}], "sensor": sensors},
            {"binary_sensor": binaries},
        ],
    }

    header = ("# Generated by testbed/generate_house.py -- do not hand-edit.\n"
              "# A fake house: every entity here is a helper, nothing talks to hardware.\n")
    (out / "fake_house.yaml").write_text(
        header + yaml.safe_dump(package, sort_keys=False, width=120, allow_unicode=True)
    )
    print(f"wrote {out / 'fake_house.yaml'}")
    print(f"  {len(lights)} lights, {len(switches)} switches, "
          f"{len(sensors)} sensors, {len(binaries)} binary sensors")
    print(f"  including {len(TRAPS)} entities HouseFly is required to refuse")

    _write_dashboard(here / "config" / "housefly-dashboard.yaml",
                     light_slugs, switch_slugs, motion_slugs)


def _write_dashboard(path: Path, lights: list[str], switches: list[str],
                     motions: list[str]) -> None:
    """Emit the dashboard from the entities we actually generated.

    Hand-written and generated config drift apart the moment the generator's
    seed picks a different set of rooms, and a dashboard full of "Entity not
    found" is a bad first impression.
    """
    traps = [slug for slug, _ in TRAPS]
    safe_switches = [s for s in switches if s not in traps]

    view_fly = {
        "title": "The fly", "path": "fly", "icon": "mdi:bee",
        "cards": [
            # Mounting this card is what lets the fly out. It draws nothing
            # itself; it reports where every card on screen is and paints the
            # fly over the top of them.
            {"type": "custom:housefly-overlay", "show_debug": True},
            {"type": "custom:housefly-brain-card"},
            {"type": "entities", "title": "What the fly is doing", "entities": [
                "sensor.housefly_mode", "sensor.housefly_heading",
                "sensor.housefly_arousal", "sensor.housefly_hunger",
                "sensor.housefly_valence", "sensor.housefly_memory",
                "sensor.housefly_kenyon_cells_active",
                "sensor.housefly_network_activity",
                "binary_sensor.housefly_awake", "binary_sensor.housefly_escaping",
            ]},
            {"type": "entities", "title": "Interfere with it", "entities": [
                {"type": "call-service", "name": "Loom at it",
                 "icon": "mdi:hand-back-right", "service": "fly_house.loom",
                 "service_data": {"strength": 2.0}},
                {"type": "call-service", "name": "Feed it", "icon": "mdi:candy",
                 "service": "fly_house.feed", "service_data": {"amount": 1.0}},
                {"type": "call-service", "name": "Wipe its memory",
                 "icon": "mdi:delete-sweep", "service": "fly_house.reset_memory"},
            ]},
            {"type": "entities", "title": "Safety budget",
             "entities": ["sensor.housefly_actuations_this_hour"]},
        ],
    }
    view_house = {
        "title": "The house", "path": "house", "icon": "mdi:home",
        "cards": [
            {"type": "custom:housefly-overlay"},
            {"type": "light", "entity": f"light.{lights[0]}"},
            {"type": "entities", "title": "Lights",
             "entities": [f"light.{s}" for s in lights[:8]]},
            {"type": "entities", "title": "Switches",
             "entities": [f"switch.{s}" for s in safe_switches[:8]]},
            {"type": "entities", "title": "HouseFly must refuse these",
             "entities": [f"switch.{s}" for s in traps]},
            {"type": "entities", "title": "Motion -- toggle to startle it",
             "entities": [f"input_boolean.{s}_trigger" for s in motions[:6]]},
        ],
    }
    header = "# Generated by testbed/generate_house.py -- do not hand-edit.\n"
    path.write_text(header + yaml.safe_dump(
        {"title": "HouseFly", "views": [view_fly, view_house]},
        sort_keys=False, width=120,
    ))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
