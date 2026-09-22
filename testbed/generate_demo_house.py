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
    # every ninety seconds a simulated occupant walks up to the sensor, stands
    # there a moment, and walks away again. The fly startles at the approach and
    # settles when they leave, all by itself.
    #
    # Modelled on the LD2410 in engineering mode, which is what a real install
    # would have: it reports the range to a *moving* target and how much energy
    # it is seeing, and that range closing is exactly the event LPLC2 is built
    # for.
    #
    # One second per sample, not five. A real mmWave module reports at around
    # 10 Hz and this is as fast as a Home Assistant time_pattern trigger goes,
    # but the reason matters more than the number: looming is a *derivative*, so
    # the sample interval sets the shortest approach that can be measured at
    # all. At five seconds a walking person crossed the useful range inside a
    # single sample.
    #
    # And the walker walks at 0.75 m/s, which is a human being. The first
    # version covered 4.5 m in twenty-five seconds -- 18 cm/s, a crawl -- which
    # put theta-dot below the escape threshold at every range that mattered and
    # made the circuit look broken when it was in fact working.
    #
    #   t < 60   nobody there             60-66  walking in, 5.0 m -> 0.5 m
    #   66-69    standing still           69-75  walking away
    #
    # Ninety seconds, not three minutes. Nobody watches a demo for three
    # minutes to find out whether it does anything.
    #
    # But not *every* ninety seconds on the dot, which is what this used to be:
    # `as_timestamp(now()) % 90`, locked to the wall clock, someone walking up
    # at t=60 and away by t=75, for ever. A house that runs on a metronome makes
    # the fly look like one too -- it startled at the same offset in every
    # minute and a half of its life, which reads as a loop rather than an
    # animal.
    #
    # So the slot is a hundred seconds, the walk starts somewhere inside it, and
    # roughly one slot in six nobody comes at all. The offset is hashed from the
    # slot number rather than drawn at random, which matters: this template is
    # re-evaluated every second, so a per-tick `random` would make the approach
    # jitter *within itself* and destroy the smooth ramp that looming is a
    # derivative of. Hashing the slot gives a figure that is fixed for the whole
    # cycle and unpredictable from one cycle to the next.
    #
    # Gaps between approaches then run from about forty seconds to about four
    # minutes. What this does *not* do is make the approach more novel to the
    # mushroom body: familiarity is about the pattern, not its schedule, and
    # "someone at two metres" is the same smell whenever it happens.
    walk_time = (
        "{% set n = as_timestamp(now()) | int %}"
        "{% set slot = (n / 100) | int %}"
        "{% set h = (slot * 1103515245 + 12345) % 2147483648 %}"
        "{% set t = n % 100 - (10 + (h // 7) % 50) %}"
        "{% if h % 6 == 0 %}{% set t = -1 %}{% endif %}"
    )
    # `t` has to be set BEFORE the if/elif chain, not inside it: Jinja evaluates
    # each elif as it walks the chain, so a set placed after the first branch
    # leaves t undefined for every comparison that follows.
    nobody = "{% if is_state('input_boolean.simulated_occupant', 'off') %}"
    #   t < 0    nobody there          0-6    walking in, 5.0 m -> 0.5 m
    #   6-9      standing still        9-15   walking away
    radar_distance = (
        walk_time + nobody + "500"
        + "{% elif t < 0 %}500"
        "{% elif t < 6 %}{{ (500 - t / 6 * 450) | round(0) }}"
        "{% elif t < 9 %}50"
        "{% elif t < 15 %}{{ (50 + (t - 9) / 6 * 450) | round(0) }}"
        "{% else %}500"
        "{% endif %}"
    )
    radar_energy = (
        walk_time + nobody + "0"
        + "{% elif t < 0 or t > 15 %}0"
        "{% elif t < 9 %}{{ range(70, 101) | random }}"
        "{% else %}{{ range(40, 71) | random }}"
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
            {"trigger": [{"trigger": "time_pattern", "seconds": "/1"}],
             "sensor": radar_sensors},
            {"binary_sensor": [{
                "name": "Radar Presence",
                "unique_id": "demo_radar_presence",
                "device_class": "occupancy",
                "state": "{{ states('sensor.radar_moving_distance') | float(500) < 450 }}",
            }]},
        ],
    }

    # --- somebody moving about the house ---------------------------------
    #
    # The motion toggles above need a person to press them. This walks one
    # through the house on its own so the floor plan has something happening in
    # it: a room at a time, a minute or two in each, with the hallway between
    # rooms because that is where the hallway is.
    #
    # Derived from the clock rather than stored in a state machine, so it
    # survives a restart mid-walk and cannot get stuck in a room -- the same
    # reason the radar's walker is written this way.
    #
    #   540 s cycle, 90 s per step: kitchen, hallway, living room, hallway,
    #   bedroom, hallway. Then round again.
    WALK = ["kitchen", "hallway", "living_room", "hallway", "bedroom", "hallway"]
    occupancy = []
    for i, room in enumerate(ROOMS):
        # Which slots of the cycle have the occupant in this room.
        slots = [str(n) for n, r in enumerate(WALK) if r == room]
        if not slots:
            continue
        occupancy.append({
            "name": f"{title(room)} Occupied",
            "unique_id": f"demo_{room}_occupied",
            "device_class": "occupancy",
            "state": (
                "{% if is_state('input_boolean.simulate_people', 'off') %}false"
                "{% else %}{% set slot = ((as_timestamp(now()) % 540) / 90) | int %}"
                f"{{{{ slot in [{', '.join(slots)}] }}}}"
                "{% endif %}"
            ),
        })

    people_package = {
        "input_boolean": {
            "simulate_people": {"name": "Simulate people", "icon": "mdi:account-group"},
        },
        "template": [
            {"trigger": [{"trigger": "time_pattern", "seconds": "/10"}],
             "binary_sensor": occupancy},
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
    return package, radar_package, people_package, {
        "lights": [r for r in ROOMS],
        "switches": [f"{r}_socket" for r in ROOMS],
        "traps": [s for s, _ in TRAPS],
        "motions": [f"{r}_motion_trigger" for r in ROOMS],
    }


if __name__ == "__main__":
    package, radar_package, people_package, index = build()
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
        ("demo_people.yaml", people_package,
         "# Somebody walking round the house, so the floor plan has a person in\n"
         "# it. Room at a time, hallway in between, on a nine-minute cycle.\n"),
    ):
        out = out_dir / name
        out.write_text(header + blurb + yaml.safe_dump(body, sort_keys=False, width=100,
                                                       allow_unicode=True))
        print(f"wrote {out}  ({out.stat().st_size} bytes)")
    print(f"  {len(index['lights'])} lights, {len(index['switches'])} switches, "
          f"{len(index['traps'])} refused traps, an approach slider")
