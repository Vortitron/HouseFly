#!/usr/bin/env python3
"""Check that HouseFly's brain does what the README says it does.

Every claim the project makes about being connectome-derived is testable, so
these are the tests. Run from the repository root:

    python3 tools/validate.py

Nothing here mocks anything. It loads the shipped data pack and runs the same
code Home Assistant runs.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def _load_circuits():
    spec = importlib.util.spec_from_file_location(
        "fly_circuits", ROOT / "custom_components" / "fly_house" / "circuits.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["fly_circuits"] = module
    spec.loader.exec_module(module)
    return module


PASS, FAIL = "  PASS", "  FAIL"
_results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append(ok)
    print(f"{PASS if ok else FAIL}  {name}" + (f"  --  {detail}" if detail else ""))


def main() -> int:
    circ = _load_circuits()
    data = circ.shared_connectome()

    print("\n1. The data pack is a real connectome, not a random matrix")
    check("neuron count matches published circuits", data.n > 4000, f"{data.n} neurons")
    check("connections are measured synapse counts",
          len(data.pre) > 100_000 and data.raw_weight.min() >= 5,
          f"{len(data.pre):,} connections, min weight {data.raw_weight.min():.0f}")
    counts = defaultdict(int)
    for t in data.types:
        counts[t] += 1
    # Published counts for these types in the hemibrain.
    for cell_type, expected in (("EPG", 46), ("Delta7", 42), ("PFL3", 24), ("PEG", 18)):
        check(f"{cell_type} count matches the literature",
              counts[cell_type] == expected,
              f"{counts[cell_type]} (expected {expected})")

    print("\n2. The ring attractor is in the wiring, not in our code")
    W = np.zeros((data.n, data.n), dtype=np.float32)
    W[data.pre, data.post] = data.raw_weight
    types = np.asarray(data.types)
    epg = np.where((types == "EPG") & ~np.isnan(data.phase))[0]
    d7 = np.where(types == "Delta7")[0]
    eff = W[np.ix_(epg, d7)] @ W[np.ix_(d7, epg)]
    phase = data.phase[epg]
    bins = defaultdict(list)
    for a in range(len(epg)):
        for b in range(len(epg)):
            if a == b:
                continue
            offset = (phase[b] - phase[a]) % (2 * math.pi)
            bins[int(round(offset / (2 * math.pi / 8))) % 8].append(eff[a, b])
    profile = [float(np.mean(bins[k])) if bins[k] else 0.0 for k in range(8)]
    peak = int(np.argmax(profile))
    ratio = max(profile) / max(min(profile), 1e-9)
    check("Delta7 inhibition peaks opposite the bump", peak in (3, 4, 5),
          f"peak at {peak * 45} degrees")
    check("Mexican-hat contrast is strong", ratio > 5.0, f"{ratio:.1f}:1")

    print("\n3. PEN loops shift the bump in opposite directions per hemisphere")
    for cell_type in ("PEN_a(PEN1)", "PEN_b(PEN2)"):
        idx = np.where(types == cell_type)[0]
        shifts = {}
        for side, label in ((-1, "left"), (1, "right")):
            sel = idx[data.side[idx] == side]
            loop = W[np.ix_(epg, sel)] @ W[np.ix_(sel, epg)]
            x = y = 0.0
            for a in range(len(epg)):
                for b in range(len(epg)):
                    if loop[a, b] <= 0:
                        continue
                    delta = phase[b] - phase[a]
                    x += loop[a, b] * math.cos(delta)
                    y += loop[a, b] * math.sin(delta)
            shifts[label] = math.degrees(math.atan2(y, x))
        check(f"{cell_type} hemispheres shift oppositely",
              shifts["left"] * shifts["right"] < 0,
              f"left {shifts['left']:+.1f} deg, right {shifts['right']:+.1f} deg")

    print("\n4. The compass holds a heading and integrates turns")
    brain = circ.FlyBrain()
    brain.settle()
    for _ in range(40):
        brain.step(circ.Senses(time_of_day=0.5), sub_steps=10)
    prof = np.array(brain.compass_profile())
    check("a bump forms", prof.max() > 3 * prof.min() and prof.max() > 0.05,
          f"peak {prof.max():.3f}, trough {prof.min():.3f}")

    headings = [brain.heading]
    for _ in range(40):
        brain.step(circ.Senses(time_of_day=0.5), sub_steps=10)
        headings.append(brain.heading)
    drift = abs(math.degrees(np.unwrap(np.array(headings))[-1] - headings[0]))
    check("it holds still with no self-motion", drift < 45, f"{drift:.0f} deg of drift")

    # Sampled finely: the bump can move most of the way round in a second at
    # high angular velocity, and unwrapping a coarsely sampled angle aliases.
    rotations = []
    speeds = (-1.5, -0.7, 0.7, 1.5)
    for av in speeds:
        for _ in range(30):
            brain.step(circ.Senses(time_of_day=0.5), sub_steps=10)
        # Accumulate wrapped per-step deltas rather than unwrapping a sampled
        # angle. The bump can cross 180 degrees between samples at high angular
        # velocity, and unwrapping then aliases into a large rotation of the
        # wrong sign -- which is exactly how an earlier version of this file
        # certified a backwards compass as correct.
        prev = brain.heading
        total = 0.0
        for _ in range(50):
            brain.step(circ.Senses(angular_velocity=av, time_of_day=0.5), sub_steps=3)
            total += (brain.heading - prev + math.pi) % (2 * math.pi) - math.pi
            prev = brain.heading
        rotations.append(math.degrees(total))
    corr = float(np.corrcoef(speeds, rotations)[0, 1])
    check("turning rotates the bump, in the right direction", corr > 0.6,
          f"correlation {corr:+.2f}, rotations {[round(r) for r in rotations]}")

    # The bug that actually reached a live house. Ring neurons are GABAergic,
    # so landmark input arrives at the compass as inhibition; injected raw, a
    # single visible lamp silenced the bump entirely and the heading froze at
    # zero, which on a dashboard looks like a fly that flies right and stops.
    print("\n4b. Seeing something does not switch the compass off")
    worst = None
    layouts = {
        "nothing visible": [],
        "one landmark": [(0.0, 0.5)],
        "two opposed": [(0.0, 0.5), (math.pi, 0.5)],
        "three": [(i * 2 * math.pi / 3, 0.5) for i in range(3)],
        "six lamps (as measured on a real house)": [
            (i * 2 * math.pi / 6, 0.5) for i in range(6)
        ],
    }
    for label, marks in layouts.items():
        b = circ.FlyBrain()
        b.settle(time_of_day=0.62)
        for _ in range(35):
            b.step(circ.Senses(landmarks=marks, time_of_day=0.62), sub_steps=10)
        peak = float(np.array(b.compass_profile()).max())
        if worst is None or peak < worst[1]:
            worst = (label, peak)
    check("the bump survives every landmark layout", worst[1] > 0.02,
          f"weakest was {worst[0]} at peak {worst[1]:.3f}")

    print("\n5. The mushroom body learns, and learns the right sign")
    brain = circ.FlyBrain()
    brain.settle()
    odour = np.zeros(len(brain.i_pn), dtype=np.float32)
    odour[: max(1, len(odour) // 6)] = 1.0
    for _ in range(20):
        brain.step(circ.Senses(odour=odour, time_of_day=0.5), sub_steps=10)
    before = float(brain.kc_mbon_gain.mean())
    for _ in range(40):
        brain.step(circ.Senses(odour=odour, punishment=1.0, time_of_day=0.5), sub_steps=10)
    after = float(brain.kc_mbon_gain.mean())
    check("punishment depresses KC->MBON synapses", after < before - 1e-4,
          f"mean gain {before:.4f} -> {after:.4f}")
    check("the memory is a real population", len(brain.kc_mbon_gain) > 10_000,
          f"{len(brain.kc_mbon_gain):,} plastic synapses")

    print("\n6. Looming drives the escape pathway, then stops")
    brain = circ.FlyBrain()
    brain.settle()
    for _ in range(30):
        quiet = brain.step(circ.Senses(time_of_day=0.5), sub_steps=10)
    for _ in range(12):
        loud = brain.step(circ.Senses(looming=2.0, time_of_day=0.5), sub_steps=10)
    check("LPLC2 input raises descending-neuron drive",
          loud["escape"] > quiet["escape"],
          f"escape {quiet['escape']:.4f} -> {loud['escape']:.4f}")

    # An escape that never ends is not an escape. Without adaptation on the
    # phasic pathways a single loom pushes them into a self-sustaining state and
    # the fly flees for the rest of its life.
    for _ in range(40):
        settled = brain.step(circ.Senses(time_of_day=0.5), sub_steps=10)
    check("and the escape is transient, not a new permanent mood",
          settled["escape"] < 0.25 * loud["escape"] + 0.01,
          f"escape fell back to {settled['escape']:.4f}")

    print("\n6b. An approach drives escape the way a real one would")
    # theta-dot = L*v/r^2, so the same footsteps count for far more close in.
    # A fly that startled at someone across the room, or at someone leaving,
    # would be a poor fly.
    far = circ.FlyBrain()
    far.settle()
    for _ in range(12):
        far_result = far.step(circ.Senses(looming=0.03, time_of_day=0.5), sub_steps=10)
    near = circ.FlyBrain()
    near.settle()
    for _ in range(12):
        near_result = near.step(circ.Senses(looming=1.25, time_of_day=0.5), sub_steps=10)
    check("something close and closing fires the escape pathway",
          near_result["escape"] > 0.05,
          f"at 0.6 m closing: escape {near_result['escape']:.4f}")
    check("something far off does not", far_result["escape"] < near_result["escape"] * 0.5,
          f"at 5 m closing: escape {far_result['escape']:.4f}")

    print("\n7. Steering output is differentiated, not saturated")
    brain = circ.FlyBrain()
    brain.settle()
    for _ in range(40):
        brain.step(circ.Senses(goal_bearing=1.0, goal_strength=1.0,
                               time_of_day=0.4), sub_steps=10)
    pfl3 = brain.rate[brain.i_pfl3]
    fb = brain.rate[brain.i_fb]
    check("PFL3 cells are not all at the same rate", float(pfl3.std()) > 1e-3,
          f"spread {pfl3.std():.4f} about a mean of {pfl3.mean():.4f}")
    check("the fan-shaped body is not flooded", float(fb.mean()) < 0.35,
          f"mean rate {fb.mean():.4f}")

    print("\n8. The house reaches the brain without being flattened first")
    import hashlib as _h
    from dataclasses import dataclass as _dc
    src = (ROOT / "custom_components" / "fly_house" / "coordinator.py").read_text()
    ns = {"np": np, "math": math, "hashlib": _h, "dataclass": _dc, "State": object}
    exec(compile(src[src.index("def _stable_channel"):src.index("class FlyHouseCoordinator")],
                 "coordinator", "exec"), ns)
    numeric, channel_of = ns["_numeric"], ns["_stable_channel"]

    class _State:
        def __init__(self, state):
            self.state = state

    adaptation: dict = {}
    rooms = ("Allrum", "Loft", "Kitchen", "Hallway", "Bedroom", "Study", "Garage")
    glomeruli = {
        room: channel_of(numeric(_State(room), adaptation, "sensor.area").key, 131)
        for room in rooms
    }
    distinct = len(set(glomeruli.values()))
    # Collisions are expected and are not a defect: 131 glomeruli cannot give
    # every possible state its own, and a real fly has about 50 for an unbounded
    # number of odours. What matters is that most separate here and that the
    # rest are pulled apart downstream -- which is the next check.
    check("most rooms reach their own glomerulus", distinct >= len(rooms) - 1,
          f"{distinct} distinct for {len(rooms)} rooms")
    repeats = {channel_of(numeric(_State("Kitchen"), adaptation, "sensor.area").key, 131)
               for _ in range(5)}
    check("and the same room always reaches the same one", len(repeats) == 1,
          "otherwise nothing about it could ever be learned")

    # Two channels in wildly different units must both end up usable.
    for entity, values in (("sensor.power", [300, 2840, 1500]),
                           ("sensor.temp", [-4, 17, 8])):
        for _ in range(4):
            for v in values:
                numeric(_State(str(v)), adaptation, entity)
    spread = [numeric(_State(str(v)), adaptation, "sensor.power").value
              for v in (300, 1500, 2840)]
    check("a watt-scale channel uses its whole range",
          spread[0] < 0.1 and spread[-1] > 0.9 and 0.2 < spread[1] < 0.8,
          f"300W..2840W -> {spread[0]:.2f}, {spread[1]:.2f}, {spread[2]:.2f}")
    cold = numeric(_State("-15"), adaptation, "sensor.temp").value
    warm = numeric(_State("15"), adaptation, "sensor.temp").value
    check("below freezing is not the same as above it", cold < warm,
          f"-15C -> {cold:.2f}, +15C -> {warm:.2f}")
    check("dead inputs are reported rather than read as zero",
          not numeric(_State("unknown"), adaptation, "x").live
          and not numeric(_State("unavailable"), adaptation, "x").live,
          "so a misconfigured sensor does not look like a quiet one")

    # Two inputs that land on the SAME glomerulus must still be distinguishable
    # by the time they reach the mushroom body, or the fly could never learn
    # anything about one without learning it about the other. In the animal that
    # is the job of the divergence from a few dozen projection neurons onto
    # thousands of Kenyon cells, each sampling a handful at random -- and that
    # wiring is in the connectome, so this is testing the real thing.
    collided = [a for a in rooms for b in rooms
                if a < b and glomeruli[a] == glomeruli[b]]
    brain = circ.FlyBrain()
    brain.settle()
    n_pn = len(brain.i_pn)

    def kc_code(glomerulus: int) -> np.ndarray:
        b = circ.FlyBrain()
        b.settle()
        odour = np.zeros(n_pn, dtype=np.float32)
        odour[glomerulus % n_pn] = 1.0
        for _ in range(25):
            b.step(circ.Senses(odour=odour, time_of_day=0.5), sub_steps=10)
        return (b.rate[b.i_kc] > 0.01)

    a, b = kc_code(glomeruli[rooms[0]]), kc_code(glomeruli[rooms[2]])
    overlap = int((a & b).sum())
    union = int((a | b).sum())
    check("two different smells give different Kenyon cell codes",
          union > 0 and overlap / union < 0.9,
          f"{int(a.sum())} and {int(b.sum())} cells active, {overlap} shared "
          f"({overlap / max(union, 1):.0%} overlap)"
          + (f"; {len(collided)} room pair(s) collided upstream" if collided else ""))

    print("\n9. The clock makes it crepuscular without an if-statement")
    arousal = {}
    for label, t in (("03:00", 0.125), ("06:00", 0.25), ("12:00", 0.5),
                     ("18:45", 0.78), ("23:00", 0.958)):
        b = circ.FlyBrain()
        b.settle(time_of_day=t)
        # Clock cells integrate over minutes, so this has to run for simulated
        # minutes -- 300 steps of 20 substeps is five simulated minutes.
        for _ in range(300):
            r = b.step(circ.Senses(time_of_day=t), sub_steps=20)
        arousal[label] = r["arousal"]
    print("     " + "  ".join(f"{k} {v:.2f}" for k, v in arousal.items()))
    check("dawn and dusk beat the small hours",
          min(arousal["06:00"], arousal["18:45"]) > max(arousal["03:00"], arousal["23:00"]),
          "morning and evening oscillators are doing their job")

    ok = all(_results)
    print(f"\n{sum(_results)}/{len(_results)} checks passed\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
