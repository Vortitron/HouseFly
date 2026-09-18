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

    print("\n8. The clock makes it crepuscular without an if-statement")
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
