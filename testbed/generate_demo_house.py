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

    # --- a simulated mmWave radar, with someone walking about in front of it --
    #
    # The slider above needs a person to drag it. This is the same signal
    # arriving on its own, so the demo does something while nobody is watching:
    # every three minutes a simulated occupant walks up to the sensor, pauses,
    # and walks away again. The fly startles at the approach and settles when it
    # leaves, all by itself.
    #
    # Modelled on the LD2410 in engineering mode, which is what a real install
    # would have: it reports the range to a *moving* target and how much energy
    # it is seeing, and that range closing is exactly the event LPLC2 is built
    # for. A 5-second cadence, because a looming detector differencing samples
    # six seconds apart is measuring nothing.

    # 0.00-0.72  far away        0.72-0.86  walking towards it
    # 0.86-1.00  walking away
    walk_phase = "{% set p = (as_timestamp(now()) % 180) / 180 %}"
    # The phase has to be set BEFORE the if/elif chain, not inside it: Jinja
    # evaluates each elif as it walks the chain, so a set placed after the first
    # branch leaves p undefined for every comparison that follows.
    radar_distance = (
        walk_phase
        + "{% if is_state('input_boolean.simulated_occupant', 'off') %}500"
        "{% elif p < 0.72 %}500"
        "{% elif p < 0.86 %}{{ (500 - (p - 0.72) / 0.14 * 450) | round(0) }}"
        "{% else %}{{ (50 + (p - 0.86) / 0.14 * 450) | round(0) }}"
        "{% endif %}"
    )
    radar_energy = (
        walk_phase
        + "{% if is_state('input_boolean.simulated_occupant', 'off') %}0"
        "{% elif p < 0.72 %}0"
        "{% else %}{{ range(60, 101) | random }}"
        "{% endif %}"
    )
    radar_sensors = [
        {
            "name": "Radar Moving Distance",
            "unique_id": "demo_radar_distance",
            "device_class": "distance",
            "unit_of_measurement": "cm",
            "state_class": "measurement",
            "state": radar_distance,
        },
        {
            "name": "Radar Moving Energy",
            "unique_id": "demo_radar_energy",
            "state_class": "measurement",
            "state": radar_energy,
        },
    ]
    radar_package = {
        "input_boolean": {
            "simulated_occupant": {"name": "Simulated occupant", "icon": "mdi:walk"},
        },
        "template": [
            {"trigger": [{"trigger": "time_pattern", "seconds": "/5"}],
             "sensor": radar_sensors},
            {"binary_sensor": [{
                "name": "Radar Presence",
                "unique_id": "demo_radar_presence",
                "device_class": "occupancy",
                "state": "{{ states('sensor.radar_moving_distance') | float(500) < 450 }}",
            }]},
        ],
    }

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
    return package, radar_package, {
        "lights": [r for r in ROOMS],
        "switches": [f"{r}_socket" for r in ROOMS],
        "traps": [s for s, _ in TRAPS],
        "motions": [f"{r}_motion_trigger" for r in ROOMS],
    }


if __name__ == "__main__":
    package, radar_package, index = build()
    out_dir = Path(__file__).parent / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    header = "# Generated by testbed/generate_demo_house.py -- do not hand-edit.\n"

    # Two package files rather than one. Home Assistant merges everything under
    # packages/, and keeping the radar separate means it can be added to or
    # replaced on a running instance without re-sending the whole house.
    for name, body, blurb in (
        ("demo_house.yaml", package,
         "# A small fake house for the public demo. Nothing here touches hardware.\n"),
        ("demo_radar.yaml", radar_package,
         "# A simulated mmWave radar with someone walking in front of it, so the\n"
         "# demo does something while nobody is watching.\n"),
    ):
        out = out_dir / name
        out.write_text(header + blurb + yaml.safe_dump(body, sort_keys=False, width=100,
                                                       allow_unicode=True))
        print(f"wrote {out}  ({out.stat().st_size} bytes)")
    print(f"  {len(index['lights'])} lights, {len(index['switches'])} switches, "
          f"{len(index['traps'])} refused traps, an approach slider")
