#!/usr/bin/env python3
"""A small house for the hosted public demo.

Different goals from `generate_house.py`, which builds a ten-room house for
local testing. This one is for a box strangers can poke at, so it is:

  * small enough to write over an API in one call, and to read on a phone;
  * interactive -- everything here is meant to be prodded by a visitor;
  * honest about the safety layer, with entities that exist to be refused.

The approach slider is the interesting one. It feeds HouseFly's looming input,
which is the path a real fly's LPLC2 neurons use, so dragging it down from five
metres to half a metre is the same stimulus as something lunging at it -- and
the fly bolts. That is the demo: not a picture of a fly, a fly that reacts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOMS = ["kitchen", "living_room", "hallway", "bedroom"]
TRAPS = [
    ("boiler_relay", "Boiler Relay"),
    ("freezer_socket", "Freezer Socket"),
    ("network_rack", "Network Rack"),
    ("garage_door_motor", "Garage Door Motor"),
]


def title(slug: str) -> str:
    return slug.replace("_", " ").title()


def act(service: str, entity_id: str, data=None) -> dict:
    step = {"action": service, "target": {"entity_id": entity_id}}
    if data:
        step["data"] = data
    return step


def build() -> tuple[dict, dict]:
    booleans, numbers, lights, switches, sensors, binaries = {}, {}, [], [], [], []

    for room in ROOMS:
        slug = f"{room}_light"
        booleans[slug] = {"name": f"{title(room)} light helper"}
        numbers[f"{room}_brightness"] = {
            "name": f"{title(room)} brightness",
            "min": 0, "max": 100, "step": 1, "initial": 60,
        }
        lights.append({
            "name": title(room),
            "unique_id": f"demo_{room}",
            "state": f"{{{{ is_state('input_boolean.{slug}', 'on') }}}}",
            "level": (f"{{{{ (states('input_number.{room}_brightness') "
                      f"| float(0) * 2.55) | round(0) }}}}"),
            "turn_on": [act("input_boolean.turn_on", f"input_boolean.{slug}")],
            "turn_off": [act("input_boolean.turn_off", f"input_boolean.{slug}")],
            # set_level must ALSO turn the light on. Home Assistant calls it
            # *instead of* turn_on when a brightness is supplied, so a set_level
            # that only moves the number leaves the light off while reporting a
            # brightness -- which looks like a broken light.
            "set_level": [
                act("input_number.set_value", f"input_number.{room}_brightness",
                    {"value": "{{ (brightness / 2.55) | round(0) }}"}),
                act("input_boolean.turn_on", f"input_boolean.{slug}"),
            ],
        })

        sw = f"{room}_socket"
        booleans[f"{sw}_helper"] = {"name": f"{title(room)} socket helper"}
        switches.append({
            "name": f"{title(room)} Socket",
            "unique_id": f"demo_{sw}",
            "state": f"{{{{ is_state('input_boolean.{sw}_helper', 'on') }}}}",
            "turn_on": [act("input_boolean.turn_on", f"input_boolean.{sw}_helper")],
            "turn_off": [act("input_boolean.turn_off", f"input_boolean.{sw}_helper")],
        })

        booleans[f"{room}_motion_trigger"] = {"name": f"{title(room)} motion trigger"}
        binaries.append({
            "name": f"{title(room)} Motion",
            "unique_id": f"demo_{room}_motion",
            "device_class": "motion",
            "state": f"{{{{ is_state('input_boolean.{room}_motion_trigger', 'on') }}}}",
        })

        centre = {"kitchen": 21.0, "living_room": 20.0,
                  "hallway": 18.0, "bedroom": 19.0}[room]
        sensors.append({
            "name": f"{title(room)} Temperature",
            "unique_id": f"demo_{room}_temperature",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            "state_class": "measurement",
            "state": (
                f"{{% set v = states('sensor.{room}_temperature') | float({centre}) %}}"
                f"{{% set drift = range(-100, 101) | random / 100 * 0.4 %}}"
                f"{{{{ (v + drift + ({centre} - v) * 0.05) | round(2) }}}}"
            ),
        })

    for slug, name in TRAPS:
        booleans[f"{slug}_helper"] = {"name": f"{name} helper"}
        switches.append({
            "name": name,
            "unique_id": f"demo_{slug}",
            "state": f"{{{{ is_state('input_boolean.{slug}_helper', 'on') }}}}",
            "turn_on": [act("input_boolean.turn_on", f"input_boolean.{slug}_helper")],
            "turn_off": [act("input_boolean.turn_off", f"input_boolean.{slug}_helper")],
        })

    # The interactive bit. Drag it down and the fly bolts, because closing
    # distance is what its looming detectors are built to notice.
    numbers["approach_distance"] = {
        "name": "How close you are",
        "min": 30, "max": 500, "step": 5, "initial": 500,
        "unit_of_measurement": "cm", "icon": "mdi:arrow-collapse-right",
    }
    sensors.append({
        "name": "Approach Distance",
        "unique_id": "demo_approach",
        "device_class": "distance",
        "unit_of_measurement": "cm",
        "state_class": "measurement",
        "state": "{{ states('input_number.approach_distance') | float(500) }}",
    })

    package = {
        "input_boolean": booleans,
        "input_number": numbers,
        "template": [
            {"light": lights},
            {"switch": switches},
            {"trigger": [{"trigger": "time_pattern", "seconds": "/10"}], "sensor": sensors},
            {"binary_sensor": binaries},
        ],
    }
    return package, {
        "lights": [r for r in ROOMS],
        "switches": [f"{r}_socket" for r in ROOMS],
        "traps": [s for s, _ in TRAPS],
        "motions": [f"{r}_motion_trigger" for r in ROOMS],
    }


if __name__ == "__main__":
    package, index = build()
    out = Path(__file__).parent / "demo" / "demo_house.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Generated by testbed/generate_demo_house.py -- do not hand-edit.\n"
              "# A small fake house for the public demo. Nothing here touches hardware.\n")
    out.write_text(header + yaml.safe_dump(package, sort_keys=False, width=100,
                                           allow_unicode=True))
    print(f"wrote {out}  ({out.stat().st_size} bytes)")
    print(f"  {len(index['lights'])} lights, {len(index['switches'])} switches, "
          f"{len(index['traps'])} refused traps, an approach slider")
