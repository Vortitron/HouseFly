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
import hashlib
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    """Import a module of the integration without importing Home Assistant."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def coord_const_int(name: str) -> int:
    """Read an int constant from coordinator.py, or const.py where it lives."""
    for module in ("coordinator.py", "const.py"):
        src = (ROOT / "custom_components" / "fly_house" / module).read_text()
        for line in src.splitlines():
            if line.startswith(f"{name} ="):
                return int(line.split("=")[1].split("#")[0].strip())
    raise AssertionError(f"{name} not found in coordinator.py or const.py")


def watchable_domains():
    """WATCHABLE_DOMAINS out of const.py, without importing Home Assistant."""
    src = (ROOT / "custom_components" / "fly_house" / "const.py").read_text()
    start = src.index("WATCHABLE_DOMAINS = (")
    end = src.index(")", start) + 1
    return eval(src[start + len("WATCHABLE_DOMAINS = "):end])


def coord_const(name: str) -> float:
    """Read a float constant out of coordinator.py without importing Home
    Assistant, which is not installed where these checks run."""
    src = (ROOT / "custom_components" / "fly_house" / "coordinator.py").read_text()
    for line in src.splitlines():
        if line.startswith(f"{name} ="):
            return float(line.split("=")[1].split("#")[0].strip())
    raise AssertionError(f"{name} not found in coordinator.py")


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

    # If the pack is ever rebuilt, the checksums compiled into connectome_fetch
    # must be regenerated with it. Otherwise an install that has to fetch the
    # pack refuses the very file this repository ships.
    import hashlib as _hashlib
    import re as _re
    fetch_src = (ROOT / "custom_components" / "fly_house"
                 / "connectome_fetch.py").read_text()
    declared = dict(_re.findall(r'"(core\.npz|meta\.json\.gz)":\s*"([0-9a-f]{64})"',
                                fetch_src))
    pack_dir = ROOT / "custom_components" / "fly_house" / "connectome"
    mismatched = [
        name for name, expected in declared.items()
        if _hashlib.sha256((pack_dir / name).read_bytes()).hexdigest() != expected
    ]
    check("the fetcher's checksums match the shipped pack",
          len(declared) == 2 and not mismatched,
          f"{len(declared)} declared, mismatched: {mismatched or 'none'}")

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

    print("\n3b. What the data pack cannot do, stated as a number")
    # The README claims a directed escape is impossible with this pack. That is
    # a claim about the data and it should be checked like any other, not least
    # so that it stops being true the day someone builds a pack from a
    # whole-brain reconstruction.
    def sides(idx):
        s = data.side[idx]
        return int((s < 0).sum()), int((s > 0).sum()), int((s == 0).sum())

    loom_l, loom_r, loom_u = sides(data.group_index["loom"])
    dn_l, dn_r, _ = sides(data.group_index["descending"])
    check("the looming pathway has no left hemisphere to compare against",
          loom_l == 0 and loom_r > 0,
          f"LPLC2/LC: {loom_l} left, {loom_r} right, {loom_u} unlabelled -- "
          "the hemibrain is a hemibrain, so escape stays undirected")
    check("and the descending neurons are too few and too one-sided",
          dn_l + dn_r > 0 and min(dn_l, dn_r) < 2,
          f"DNp: {dn_l} left, {dn_r} right")
    # Repairing the hemisphere labels must not have disturbed the circuits that
    # already had them, because the compass depends on their balance.
    pen_idx = np.where(np.isin(types, ["PEN_a(PEN1)", "PEN_b(PEN2)"]))[0]
    for name, idx in (("EPG", np.where(types == "EPG")[0]),
                      ("PEN", pen_idx),
                      ("PFL3", np.where(types == "PFL3")[0])):
        left, right, unknown = sides(idx)
        check(f"{name} is still balanced across hemispheres",
              left == right and left > 0 and unknown == 0,
              f"{left} left, {right} right")

    print("\n4. The compass holds a heading and responds to turns")
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
    # A change in turn command rotates the bump; a *constant* one does not keep
    # rotating it. That distinction is the difference between an integrator and
    # a displacement, and the check above only ever exercised the first, which
    # is how the README came to claim the second. Measure it directly.
    sustained = {}
    for av in (-1.5, 0.0, 1.5):
        b = circ.FlyBrain()
        b.settle()
        prev = b.heading
        total = 0.0
        for _ in range(60):
            b.step(circ.Senses(angular_velocity=av, time_of_day=0.4), sub_steps=10)
            total += math.atan2(math.sin(b.heading - prev), math.cos(b.heading - prev))
            prev = b.heading
        sustained[av] = math.degrees(total)
    held = abs(sustained[0.0])
    turned = max(abs(sustained[-1.5]), abs(sustained[1.5]))
    check("a constant turn command does not keep rotating the bump",
          turned < 360.0,
          f"60 ticks at -1.5 rad/s moved it {sustained[-1.5]:+.0f} deg and at +1.5 "
          f"{sustained[1.5]:+.0f} deg -- an offset, not a velocity. Documented, not fixed.")
    check("and with no turn command it does not drift",
          held < 5.0,
          f"{held:.1f} deg over 60 ticks")

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

    print("\n5b. It can tell familiar from unfamiliar, with nobody labelling anything")
    # The claim behind binary_sensor.housefly_unusual. The Kenyon layer is a
    # locality-sensitive hash (Dasgupta, Stevens & Navlakha 2017) and the
    # alpha'3 compartment habituates to whatever it has met before (Hattori et
    # al. 2017), so novelty falls with exposure and rises for something new --
    # with no teaching signal anywhere, which is what separates this from the
    # valence memory above.
    def smell(seed):
        rng = np.random.default_rng(seed)
        v = np.zeros(40, dtype=np.float32)
        v[rng.choice(40, 8, replace=False)] = rng.uniform(0.5, 1.2, 8)
        return v

    nov = circ.FlyBrain()
    nov.settle()
    first = nov.step(circ.Senses(odour=smell(1), time_of_day=0.4))["novelty"]
    for _ in range(400):
        out = nov.step(circ.Senses(odour=smell(1), time_of_day=0.4))
    learned = out["novelty"]
    stranger = nov.step(circ.Senses(odour=smell(2), time_of_day=0.4))["novelty"]
    for _ in range(300):
        nov.step(circ.Senses(odour=smell(2), time_of_day=0.4))
    back = nov.step(circ.Senses(odour=smell(1), time_of_day=0.4))["novelty"]

    check("something new registers as novel", first > 0.8,
          f"first sight {first:.3f}")
    check("and stops being novel once it has been around a while",
          learned < 0.15, f"after 400 ticks {learned:.3f}")
    check("a pattern it has never met reads as more novel than one it knows",
          stranger > back * 2.0,
          f"stranger {stranger:.3f} against the familiar one at {back:.3f}")
    check("none of which needed a teaching signal",
          abs(nov.kc_mbon_gain.mean() - 1.0) < 1e-3,
          "the valence memory is untouched -- this is unsupervised habituation")

    print("\n5c. Familiar is a question about the hour as well as the house")
    # Without time in the Kenyon code there is one habituation trace for all
    # hours, so the fly learns "lights on" and then finds lights on at three in
    # the morning perfectly ordinary. Measured before the fix: 400 evenings of a
    # pattern gave novelty 0.025, and the same pattern at 03:00 gave 0.025 --
    # the same number, because the code was identical.
    def house_n(seed, width, n=8):
        rng = np.random.default_rng(seed)
        v = np.zeros(width, dtype=np.float32)
        v[rng.choice(width, n, replace=False)] = rng.uniform(0.5, 1.2, n)
        return v

    def house(seed, width):
        return house_n(seed, width)

    width = circ.FlyBrain().n_odour_channels
    evening, night = 0.80, 0.125
    known, stranger = house(1, width), house(51, width)

    ctx = circ.FlyBrain()
    ctx.settle(time_of_day=evening)
    for _ in range(400):
        out = ctx.step(circ.Senses(odour=known, time_of_day=evening))
    familiar = out["novelty"]
    wrong_hour = max(ctx.step(circ.Senses(odour=known, time_of_day=night))["novelty"]
                     for _ in range(6))
    for _ in range(60):
        ctx.step(circ.Senses(odour=known, time_of_day=evening))
    wrong_house = max(ctx.step(circ.Senses(odour=stranger, time_of_day=evening))["novelty"]
                      for _ in range(6))

    check("a house it has lived in reads as familiar",
          familiar < 0.10, f"novelty {familiar:.3f}")
    check("the same house at the wrong hour does not",
          wrong_hour > familiar * 4, f"{wrong_hour:.3f} at 03:00 against {familiar:.3f} in the evening")
    check("and a strange house is still strange",
          wrong_house > familiar * 4, f"novelty {wrong_house:.3f}")
    # The threshold has to clear both, which the old 0.35 did not.
    import importlib.util as _il
    _sp = _il.spec_from_file_location(
        "fly_coord_consts", ROOT / "custom_components" / "fly_house" / "coordinator.py")
    unusual = float([ln.split("=")[1].split("#")[0].strip()
                     for ln in (ROOT / "custom_components" / "fly_house" / "coordinator.py")
                     .read_text().splitlines()
                     if ln.startswith("NOVELTY_UNUSUAL")][0])
    check("and the alert threshold sits between familiar and both of them",
          familiar < unusual < min(wrong_hour, wrong_house),
          f"{familiar:.3f} < {unusual} < {min(wrong_hour, wrong_house):.3f}")

    # The arming guard has to sit low enough that crossing it means something.
    # It was 0.5, and a fresh brain crosses 0.5 while novelty is still five
    # times the alert line -- so the guard let go before the fly knew anything
    # and the alert armed into a stretch that was unfamiliar by construction.
    src = (ROOT / "custom_components" / "fly_house" / "coordinator.py").read_text()
    familiar_once = float(unusual if "FAMILIAR_ONCE = NOVELTY_UNUSUAL" in src else
                          [ln.split("=")[1].split("#")[0].strip()
                           for ln in src.splitlines()
                           if ln.startswith("FAMILIAR_ONCE")][0])
    check("the alert will not arm until the fly has seen the place look familiar",
          familiar_once <= wrong_house,
          f"arms at {familiar_once} against {wrong_house:.3f} for a house it has never seen")
    check("but it does arm once the fly has settled in",
          familiar_once >= familiar,
          f"arms at {familiar_once} against {familiar:.3f} for a house it knows")

    # And the reason the old 0.5 was wrong, measured rather than asserted: watch
    # a brand-new brain come down and see where it crosses each line.
    def settle_in(n_live, ticks=150):
        b = circ.FlyBrain()
        b.settle(time_of_day=evening)
        pat = house_n(7, width, n_live)
        cross_half = cross_alert = None
        for i in range(1, ticks + 1):
            nv = b.step(circ.Senses(odour=pat, time_of_day=evening))["novelty"]
            if cross_half is None and nv <= 0.5:
                cross_half = i
            if cross_alert is None and nv <= unusual:
                cross_alert = i
                break
        return cross_half, cross_alert

    small_half, small_alert = settle_in(8)
    big_half, big_alert = settle_in(min(101, width))
    check("a new fly crosses the old 0.5 guard long before it knows the place",
          small_half is not None and small_alert is not None and small_half < small_alert / 2,
          f"0.5 at tick {small_half}, {unusual} at tick {small_alert}")
    check("and territory size barely changes how long settling in takes",
          big_alert is not None and abs(big_alert - small_alert) < 0.25 * small_alert,
          f"8 entities settle at tick {small_alert}, {min(101, width)} at tick {big_alert}")

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

    # The check above holds the stimulus on for twelve steps, so a weak one
    # adapts away. A real approach is a *transient*, and that is where this
    # pathway went wrong: with a resting drive parked exactly at the firing
    # threshold, a looming input of 1e-5 fired the same full escape as one of
    # 1.25, so theta-dot = v/r^2 was computed and then discarded. Measure the
    # onset response directly, across four decades.
    def first_burst(loom: float) -> float:
        b = circ.FlyBrain()
        b.settle()
        peak = 0.0
        for _ in range(12):
            peak = max(peak, b.step(circ.Senses(looming=loom, time_of_day=0.5))["escape"])
        return peak

    trivial = max(first_burst(v) for v in (1e-5, 1e-3, 1e-2))
    real = first_burst(0.5)
    check("a trivial expansion rate does not trigger anything",
          trivial < 0.05,
          f"strongest burst from 1e-5..1e-2 was {trivial:.4f}")
    check("so the escape has a real threshold, not a nominal one",
          real > 0.15 and real > trivial * 4,
          f"1e-2 -> {first_burst(1e-2):.4f}, 0.5 -> {real:.4f}")

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

    print("\n10. The safety layer's quiet hours mean what they say")
    safety = load("safety", ROOT / "custom_components" / "fly_house" / "safety.py")
    gov = safety.ActuationGovernor(allowlist={"light.a"}, enabled=True)

    def quiet_at(window, hours):
        gov.quiet_hours = window
        out = []
        for h in hours:
            gov._recent.clear()
            out.append(not gov.check("light.a", 1.0, local_hour=h).allowed)
        return out

    check("a normal window is quiet inside it and not outside",
          quiet_at((4, 5), [3, 4, 5, 12]) == [False, True, False, False],
          "04:00-05:00 -> quiet at 04 only")
    check("a window across midnight wraps",
          quiet_at((22, 6), [21, 22, 0, 5, 6, 12]) == [False, True, True, True, False, False],
          "22:00-06:00 -> quiet through the night, awake by 06")
    check("an empty window means no quiet hours, not every hour",
          quiet_at((4, 4), [0, 4, 5, 12, 23]) == [False] * 5,
          "start == end used to read 'hour >= 4 or hour < 4', which is every hour")

    print("\n11. The eye")
    # The visual front end is JavaScript, because it runs where the frames are.
    # Its checks live in tools/test_vision.mjs and are run here so that one
    # command still covers every claim in the README.
    vision = ROOT / "tools" / "test_vision.mjs"
    try:
        proc = subprocess.run(["node", str(vision)], capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired) as err:
        check("the visual front end's own checks pass", False,
              f"could not run node: {err}. Install Node, or run {vision} yourself.")
    else:
        tail = [ln for ln in proc.stdout.splitlines() if "vision checks passed" in ln]
        for line in proc.stdout.splitlines():
            if line.strip().startswith(("PASS", "FAIL")):
                print(f"  {line.strip()}")
        check("the visual front end's own checks pass", proc.returncode == 0,
              tail[0].strip() if tail else proc.stderr.strip()[:200])

    print("\n11. Every constant the code uses actually exists")
    # A tuning constant that is referenced but never defined is a NameError
    # waiting for the one branch that reaches it, and that branch can be rare:
    # DWELL_TICKS shipped undefined and did not raise, because the fly was
    # frozen by a second bug and never stood on anything long enough to hit the
    # line. Two faults hiding each other. This is cheap and catches the class.
    import ast as _ast
    for module in ("coordinator.py", "circuits.py", "safety.py", "sensor.py",
                   "binary_sensor.py", "websocket_api.py", "config_flow.py"):
        tree = _ast.parse((ROOT / "custom_components" / "fly_house" / module).read_text())
        defined = set()
        for node in tree.body:
            if isinstance(node, _ast.Assign):
                defined |= {t.id for t in node.targets if isinstance(t, _ast.Name)}
            elif isinstance(node, _ast.AnnAssign):
                # SENSORS: tuple[...] = (...) is still a definition.
                if isinstance(node.target, _ast.Name):
                    defined.add(node.target.id)
            elif isinstance(node, (_ast.Import, _ast.ImportFrom)):
                defined |= {a.asname or a.name.split(".")[0] for a in node.names}
            elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                defined.add(node.name)
        used = {n.id for n in _ast.walk(tree)
                if isinstance(n, _ast.Name) and isinstance(n.ctx, _ast.Load)
                and n.id.isupper() and len(n.id) > 3}
        missing = sorted(used - defined)
        check(f"{module} defines every constant it uses",
              not missing,
              "none dangling" if not missing else f"undefined: {', '.join(missing)}")

    print("\n11a. Being awake and being able to act are not mutually exclusive")
    # The bug this exists to catch: the actuation gate refused anything above
    # speed 0.30, and forward speed here is essentially proportional to arousal.
    # So every state slow enough to pass was asleep and barred on mode instead,
    # and the path could never fire at any hour of any day. Measured on the demo
    # over nineteen hours: zero actuations *and* zero blocks, because nothing
    # ever reached the safety layer to be refused.
    awake_hours = []
    for hour in range(0, 24, 3):
        t = hour / 24.0
        b = circ.FlyBrain()
        # Long enough to earn a sleep bout, or every hour reads awake: sleep is
        # five minutes of quiescence, not an instantaneous comparison.
        b.settle(time_of_day=t, seconds=circ.SLEEP_BOUT_SECONDS + 120.0)
        b.hunger = 0.97
        strength = float(np.clip(0.3 + 0.5 * b.hunger, 0.0, 1.0))
        for _ in range(40):
            r = b.step(circ.Senses(time_of_day=t, goal_bearing=1.0,
                                   goal_strength=strength), sub_steps=20)
        if r["mode"] not in ("sleep", "escape"):
            awake_hours.append((hour, r["arousal"], r["speed"]))
    check("there are hours when it is awake at all",
          len(awake_hours) > 0,
          f"{len(awake_hours)} of 8 sampled hours awake")
    # Whatever gates actuation must be satisfiable while awake. Dwell is, by
    # construction -- it depends on where the fly is standing, not how fast it
    # is. A gate on speed was not, and that is the regression being fenced off.
    coord_src = (ROOT / "custom_components" / "fly_house" / "coordinator.py").read_text()
    gate = coord_src[coord_src.index("    async def _maybe_act"):
                     coord_src.index("    def _entity_under_fly")]
    check("and nothing gates actuation on forward speed",
          'result["speed"]' not in gate,
          "speed tracks arousal, so a speed gate can only ever admit a sleeping fly"
          + (f" -- awake speeds here were {min(x[2] for x in awake_hours):.2f}"
             f"-{max(x[2] for x in awake_hours):.2f}" if awake_hours else ""))
    # Third heading regression in a row, so it gets a check of its own: the
    # goal error must be measured against the body's heading, never against the
    # compass bump. Measured with the real control law over 100 simulated
    # minutes, against the bump gives 83 landings and against the body 1500,
    # because the controller nulls one angle while the body flies on another.
    senses_src = coord_src[coord_src.index("        # --- self-motion"):
                           coord_src.index("    def _approach_looming")]
    check("steering error is measured against the body, not the bump",
          "facing = self._body_heading" in senses_src
          and "else self.brain.heading" not in senses_src,
          "the bump is an estimate and cannot slew; nulling against it never converges")

    check("landing is what earns an action",
          "DWELL_TICKS" in gate and "_dwell_ticks" in gate,
          "it has to stay on one thing for a few seconds, not merely pass over it")

    print("\n11d. One landing, one decision")
    # A fly that settles somewhere comfortable used to ask again every two
    # ticks for as long as it stayed. The refusals were correct -- deadband and
    # cooldown doing their job -- but the demo logged three actions against a
    # hundred and fifteen refusals in seven minutes, and a safety layer asked
    # the same question a hundred times tells you nothing.
    act_src = coord_src[coord_src.index("    async def _maybe_act"):
                        coord_src.index("    def _entity_under_fly")]
    check("staying put does not ask again",
          "_dwell_spent" in act_src and "self._dwell_spent = True" in act_src,
          "the visit is finished with, whether the governor said yes or no")
    check("and leaving re-arms it",
          "self._dwell_spent = False" in act_src,
          "it has to go away and come back to get another opinion")

    # Count the decisions a settled fly would ask for, the way the loop runs.
    spent, entity_prev, ticks, asks = False, None, 0, 0
    visit = ["light.a"] * 20 + [None] * 3 + ["light.a"] * 20
    for here in visit:
        if here is None:
            entity_prev, ticks, spent = None, 0, False
            continue
        if here == entity_prev:
            ticks += 1
        else:
            entity_prev, ticks, spent = here, 1, False
        if ticks < 2 or spent:
            continue
        spent = True
        asks += 1
    check("two visits to the same light ask twice, not twenty times",
          asks == 2, f"{asks} decisions across a 43-tick stay broken by one departure")

    print("\n11c. A closed browser gives the body back")
    # One-way flags are how a fly gets frozen. The card said "I own the body",
    # nothing ever said otherwise, so closing the tab stopped the coordinator
    # integrating position -- permanently -- and the stale card rectangles kept
    # the headless fallback from engaging either.
    src = (ROOT / "custom_components" / "fly_house" / "coordinator.py").read_text()
    expire = src[src.index("    def _expire_layout"):src.index("    def _effective_layout")]
    check("there is something that expires a stale layout",
          "_position_from_card = False" in expire and "LAYOUT_TTL" in expire,
          "a browser that stops reporting hands the body back to the coordinator")
    check("and it is actually called on the way into a tick",
          "self._expire_layout()" in src[src.index("    def _build_senses"):
                                         src.index("    def _approach_looming")],
          "an expiry nothing invokes is a comment")
    # The card rescans every four seconds, so the timeout has to sit clear of
    # that without being so long the fly sits still after someone closes a tab.
    ttl = float(src.split("LAYOUT_TTL = ")[1].split("\n")[0])
    scan_ms = float((ROOT / "custom_components" / "fly_house" / "www"
                     / "housefly-overlay.js").read_text()
                    .split("this._scanTimer = setInterval(() => this._scanSoon(), ")[1]
                    .split(")")[0])
    check("the timeout clears the card's own rescan interval",
          ttl > 3 * (scan_ms / 1000.0) and ttl <= 120.0,
          f"{ttl:.0f}s against a {scan_ms / 1000.0:.0f}s rescan")

    print("\n11b. It can still act with nobody watching")
    # The actuation gate needs a layout, and a layout only exists while a
    # browser has the dashboard open. Measured on the demo: zero actuations in
    # eight hours, and nothing reaching the safety layer to be refused. Correct
    # by the letter of the code and useless -- an integration that only does
    # anything while somebody looks at it is a screensaver.
    coord_src = (ROOT / "custom_components" / "fly_house" / "coordinator.py").read_text()
    start = coord_src.index("    def _effective_layout")
    end = coord_src.index("    def _landmarks")
    ns = {"math": math, "Any": object}
    exec(compile(
        "class _C:\n" + coord_src[start:end] + "\n", "coordinator", "exec"), ns)

    stub = ns["_C"].__new__(ns["_C"])
    stub._layout = []
    stub._viewport = (1920.0, 1080.0)
    stub.output_entities = [f"light.room_{i}" for i in range(5)]
    grid = ns["_C"]._effective_layout(stub)
    check("with no dashboard open it still has somewhere to land",
          len(grid) == 5 and all(c.get("entity") for c in grid),
          f"{len(grid)} notional places for {len(stub.output_entities)} outputs")
    check("and they sit inside the viewport, off the walls",
          all(c["x"] > 0 and c["y"] > 0
              and c["x"] + c["w"] < 1920.0 and c["y"] + c["h"] < 1080.0 for c in grid),
          "so the wall reflex is not permanently arguing with a goal in a corner")

    stub._layout = [{"entity": "light.real", "x": 10, "y": 10, "w": 100, "h": 100}]
    check("but a real dashboard always wins",
          ns["_C"]._effective_layout(stub) is stub._layout,
          "the fly walks on things you can actually see when there are any")

    # And it has to be able to reach them. Steering on the compass bump instead
    # of on the commanded turn leaves the body flying one fixed direction for
    # ever, bouncing between walls on a billiard path that need never cross
    # anything it can land on. Same walk, same speed, both ways:
    def landings(steer: bool) -> int:
        cells, hit, dwell = grid, 0, 0
        pos = [0.5, 0.5]
        head = 0.0
        goal = cells[0]
        for _ in range(3000):
            gx = (goal["x"] + goal["w"] / 2) / 1920.0
            gy = (goal["y"] + goal["h"] / 2) / 1080.0
            if steer:
                bearing = math.atan2(gy - pos[1], gx - pos[0])
                err = math.atan2(math.sin(bearing - head), math.cos(bearing - head))
                head = (head + max(-2.0, min(2.0, 1.2 * err * 0.785)) * 0.3) % (2 * math.pi)
            step = 0.67 * 0.02 * 2
            pos[0] += math.cos(head) * step
            pos[1] += math.sin(head) * step
            for a in (0, 1):
                if pos[a] < 0.02:
                    pos[a] = 0.04 - pos[a]
                elif pos[a] > 0.98:
                    pos[a] = 1.96 - pos[a]
                pos[a] = min(1.0, max(0.0, pos[a]))
            fx, fy = pos[0] * 1920.0, pos[1] * 1080.0
            on = any(c["x"] <= fx <= c["x"] + c["w"] and c["y"] <= fy <= c["y"] + c["h"]
                     for c in cells)
            dwell = dwell + 1 if on else 0
            if dwell == 2:
                hit += 1
                goal = cells[hit % len(cells)]
                dwell = 0
        return hit

    steered, drifting = landings(True), landings(False)
    check("and steering towards them actually gets it there",
          steered > drifting * 10,
          f"{steered} landings in 100 simulated minutes, against {drifting} while "
          "flying a fixed heading")

    # Nothing to touch means nothing to stand on.
    stub._layout = []
    stub.output_entities = []
    check("and nothing to touch means nothing to stand on",
          ns["_C"]._effective_layout(stub) == [],
          "observe-only installs get no phantom furniture")

    print("\n11e. Shifts: six hours, not twelve")
    # The obvious way to put a fly on nights is to move its day by twelve
    # hours, and for a crepuscular animal that is the one number that does not
    # work: the two peaks are already about twelve hours apart, so shifting by
    # twelve maps morning onto evening and leaves it awake at the same times.
    def awake_hours(offset_h):
        out = []
        for hour in (0, 6, 12, 18):
            subjective = ((hour + offset_h) % 24) / 24.0
            b = circ.FlyBrain()
            b.settle(time_of_day=subjective,
                     seconds=circ.SLEEP_BOUT_SECONDS + 120.0)
            for _ in range(120):
                r = b.step(circ.Senses(time_of_day=subjective), sub_steps=20)
            if r["mode"] != "sleep":
                out.append(hour)
        return out

    base, six, twelve = awake_hours(0), awake_hours(6), awake_hours(12)
    check("a six-hour shift covers the hours the others sleep through",
          six and not (set(six) & set(base)),
          f"+0h awake at {base}, +6h awake at {six}")
    check("and twelve hours is very nearly a copy",
          set(twelve) == set(base),
          f"+12h awake at {twelve}, against {base} unshifted -- "
          "the peaks are already twelve apart")

    print("\n12. It learns where this house's day actually is")
    # A fixed 06:00/18:43 is nobody's daylight. The peaks move to wherever the
    # light says dawn and dusk are, which is photoperiod tracking rather than
    # entrainment -- there is no free-running oscillator here to entrain, and
    # the README says so.
    def peak_hour(dawn, dusk, hours):
        best_h, best_a = None, -1.0
        for hh in hours:
            t = hh / 24.0
            b = circ.FlyBrain()
            b.settle(time_of_day=t)
            for _ in range(200):
                r = b.step(circ.Senses(time_of_day=t, dawn_phase=dawn, dusk_phase=dusk),
                           sub_steps=20)
            if r["arousal"] > best_a:
                best_a, best_h = r["arousal"], hh
        return best_h, best_a

    morning_default, _ = peak_hour(0.25, 0.78, (4, 6, 8))
    morning_early, _ = peak_hour(4 / 24, 22 / 24, (4, 6, 8))
    check("a house whose dawn is at 04:00 gets a fly that wakes at 04:00",
          morning_early == 4 and morning_default == 6,
          f"peak moved from {morning_default:02d}:00 to {morning_early:02d}:00")

    # The wrap case. A dusk learned at 23:30 against a time of 00:15 is 45
    # minutes apart, not three quarters of a day, and the naive squared
    # difference gets that wrong in exactly the season it matters.
    near = circ._circadian_bump(0.25 / 24, 23.5 / 24, 0.006)
    far = circ._circadian_bump(12.0 / 24, 23.5 / 24, 0.006)
    check("a dusk near midnight still counts just after midnight",
          near > 0.5 and far < 0.01,
          f"00:15 against a 23:30 dusk scores {near:.3f}, midday scores {far:.4f}")

    # Acute light on l-LNv: a light switched on at night should rouse it,
    # without being able to hold it awake against the clock all day.
    dark = circ.FlyBrain()
    dark.settle(time_of_day=0.02)
    for _ in range(200):
        quiet = dark.step(circ.Senses(time_of_day=0.02), sub_steps=20)
    lit = circ.FlyBrain()
    lit.settle(time_of_day=0.02)
    for _ in range(200):
        bright = lit.step(circ.Senses(time_of_day=0.02, light=1.0), sub_steps=20)
    check("a light switched on in the small hours rouses it",
          bright["arousal"] > quiet["arousal"] + 0.05,
          f"arousal {quiet['arousal']:.2f} in the dark, {bright['arousal']:.2f} with the light on")

    print("\n13. Where it runs, and what that costs")
    # The project page has a diagram of this, and every number in it is here.
    pack_dir = ROOT / "custom_components" / "fly_house" / "connectome"
    on_disk = sum(f.stat().st_size for f in pack_dir.iterdir())
    check("the pack is small enough to ship inside the integration",
          380_000 < on_disk < 480_000, f"{on_disk / 1024:.0f} KiB on disk")

    # One copy per process, shared by every fly. This is why a second or third
    # fly costs almost nothing: the connectome is read-only, so they share it.
    arrays = sum(v.nbytes for v in vars(data).values()
                 if isinstance(v, np.ndarray))
    fly = circ.FlyBrain()
    per_fly = sum(v.nbytes for v in vars(fly).values()
                  if isinstance(v, np.ndarray))
    check("the connectome is loaded once and shared by every fly",
          circ.shared_connectome() is data and fly.data is data
          and circ.FlyBrain().data is data,
          f"{arrays / 1024:.0f} KiB of arrays, {per_fly / 1024:.0f} KiB per fly")

    # The tick has to finish well inside the interval it simulates, or the model
    # is not running in real time at all. It runs in an executor thread, so the
    # event loop never waits on it -- but if this ratio ever approached 1, the
    # honest thing would be to say so rather than to quietly fall behind.
    fly.settle(time_of_day=0.5)
    senses = circ.Senses(time_of_day=0.5, light=0.5)
    for _ in range(3):
        fly.step(senses, 40)          # warm the caches, don't time the first
    started = time.perf_counter()
    for _ in range(10):
        fly.step(senses, 40)
    per_tick = (time.perf_counter() - started) / 10
    simulated = 40 * circ.DT
    check("a tick costs a small fraction of the time it simulates",
          per_tick < 0.25 * simulated,
          f"{per_tick * 1000:.0f} ms of CPU for {simulated:.1f} s of fly, "
          f"{100 * per_tick / simulated:.1f}% of one core")

    # "No cloud" is a claim about the source, not a promise in a paragraph.
    # connectome_fetch is the one exception and runs only at setup, only when
    # the pack is missing, and only against a version-pinned URL.
    forbidden = ("aiohttp", "urllib", "requests.", "http.client", "socket.")
    offenders = {
        path.name: [t for t in forbidden if t in path.read_text()]
        for path in sorted((ROOT / "custom_components" / "fly_house").glob("*.py"))
        if path.name != "connectome_fetch.py"
    }
    offenders = {k: v for k, v in offenders.items() if v}
    check("nothing but the pack fetcher can reach the network",
          not offenders, f"{len(offenders)} offenders: {offenders or 'none'}")

    # Loading the pack is 428 KB of np.load plus a gzip open, which are blocking
    # calls. Done inside the event loop they stall everything else that is
    # starting, and Home Assistant detects it and asks for a bug report -- it
    # did, on all three live boxes. It is cached per process, so only the first
    # fly would ever pay it, but that is not a defence.
    init_src = (ROOT / "custom_components" / "fly_house" / "__init__.py").read_text()
    warmed = init_src.find("async_add_executor_job(shared_connectome)")
    built = init_src.find("FlyHouseCoordinator(hass")
    check("and the pack is loaded off the event loop, before any brain is built",
          warmed != -1 and built != -1 and warmed < built,
          "warmed in an executor first" if warmed != -1 and warmed < built
          else "a blocking np.load inside the loop")

    print("\n13a. A service can address one fly")
    # With one fly it never mattered which fly a call meant. With four, a feed
    # that reaches all of them is not a reward, it is weather -- and there is
    # no way to teach one fly that one place is good. Checked structurally,
    # because Home Assistant is not installed where this runs: every service
    # declares a target, the handlers route through the config-entry
    # extractor, and an untargeted call still reaches every fly as it did.
    import yaml as _yaml
    services = _yaml.safe_load(
        (ROOT / "custom_components" / "fly_house" / "services.yaml").read_text())
    init_src = (ROOT / "custom_components" / "fly_house" / "__init__.py").read_text()
    check("every service declares a target",
          all("target" in services[k] for k in ("loom", "feed", "reset_memory")),
          f"{[k for k in services if 'target' in services[k]]}")
    check("and the target is limited to this integration's own entities",
          all(services[k]["target"]["entity"].get("integration") == "fly_house"
              for k in ("loom", "feed", "reset_memory")),
          "so the picker cannot offer a light as a fly")
    check("handlers resolve the target to config entries",
          "async_extract_config_entry_ids" in init_src
          and init_src.count("await _addressed(call)") == 3,
          "all three handlers go through _addressed()")
    check("and no target still means every fly",
          "if not wanted:\n            return flies" in init_src,
          "the one-fly behaviour is unchanged")

    print("\n13b. A whole-house fly does not smell itself")
    # Watching everything means the sweep will pick up the fly's own sensors
    # unless something stops it, and feeding a fly its own arousal is a loop.
    # The guard used to be a "housefly" name prefix, which the multi-fly rename
    # silently defeated: a fly called The Watcher owns sensor.the_watcher_*,
    # matched nothing, and spent its life smelling itself think. It is asked of
    # the entity registry now, so the name cannot matter.
    w_start = coord_src.index("    def _watched")
    w_end = coord_src.index("    # ----------------------------------------------------------------- sense")
    wns = {
        "MAX_WATCHED_ENTITIES": coord_const_int("MAX_WATCHED_ENTITIES"),
        "WATCHABLE_DOMAINS": watchable_domains(),
    }
    exec(compile("class _W:\n" + coord_src[w_start:w_end] + "\n",
                 "coordinator", "exec"), wns)

    class _FakeState:
        def __init__(self, entity_id): self.entity_id = entity_id

    house = ["light.kitchen", "binary_sensor.hall_motion", "sensor.porch_temperature"]
    mine = ["sensor.the_watcher_arousal", "binary_sensor.the_watcher_awake"]
    theirs = ["sensor.day_fly_mode", "binary_sensor.day_fly_escaping"]

    watcher = wns["_W"].__new__(wns["_W"])
    watcher.input_entities = []
    watcher._watch_whole_house = True
    watcher._own_entities = lambda: frozenset(mine)
    watcher.hass = type("H", (), {"states": type("S", (), {
        "async_all": staticmethod(lambda: [_FakeState(e)
                                           for e in house + mine + theirs])})()})()
    seen = wns["_W"]._watched(watcher)

    check("a whole-house fly watches the house",
          set(house) <= set(seen), f"{len(seen)} entities watched")
    check("but not one of its own entities, whatever it is called",
          not (set(mine) & set(seen)),
          f"own entities in the sweep: {sorted(set(mine) & set(seen)) or 'none'}")
    check("and another fly's entities are still news",
          set(theirs) <= set(seen),
          "one fly turning a light on is how the others find out")

    print("\n13c. Changing what it can smell disarms the alert")
    # "It has looked familiar before" is a claim about one set of senses.
    # Remap the odour channels by changing the watched entities and novelty
    # jumps to near 1.0, so an armed alert fires about the reconfiguration
    # rather than about the house. Measured live: switching whole-house
    # watching on took novelty from 0.06 to 0.98 and fired inside a minute.
    f_start = coord_src.index("    def _nose_fingerprint")
    f_end = coord_src.index("    def _own_entities")
    fns = {"hashlib": hashlib}
    exec(compile("class _N:\n" + coord_src[f_start:f_end] + "\n",
                 "coordinator", "exec"), fns)

    def fingerprint(entities, whole_house):
        stub = fns["_N"].__new__(fns["_N"])
        stub.input_entities = list(entities)
        stub._watch_whole_house = whole_house
        return fns["_N"]._nose_fingerprint(stub)

    base = fingerprint(["sensor.a", "sensor.b"], False)
    check("the same senses fingerprint the same, whatever order they are listed in",
          base == fingerprint(["sensor.b", "sensor.a"], False),
          "order must not matter, or every restart looks like a new nose")
    check("adding an entity changes it",
          base != fingerprint(["sensor.a", "sensor.b", "sensor.c"], False),
          "a wider nose is a different nose")
    check("and so does switching whole-house watching on",
          base != fingerprint(["sensor.a", "sensor.b"], True),
          "which is the change that actually fired the false alarm")
    check("and the restore path compares it before trusting the guard",
          'saved.get("nose")' in coord_src and "_ever_familiar = False" in coord_src,
          "a fingerprint nothing compares is a comment")
    # State saved before the fingerprint existed could have been learned with
    # any nose at all, so "no fingerprint" must disarm too. Writing that
    # comparison as `not in (None, fp)` left the alert armed across the very
    # upgrade meant to fix it -- seen on a live house.
    check("and state with no fingerprint at all disarms it as well",
          'saved.get("nose") != self._nose_fingerprint()' in coord_src,
          "an unknown nose is the least trustworthy one, not an exemption")

    print("\n14. Sleep is a bout, and hunger comes back down")
    # Both of these were found by leaving three flies running overnight rather
    # than by reading the code, and both were invisible to every check above.

    # Quiescence has to be sustained before it counts as sleep, and any rousing
    # ends the bout at once. A bare threshold on a continuous signal chatters:
    # live, one fly's awake sensor toggled eight times in eighty seconds.
    sleepy = circ.FlyBrain()
    sleepy.settle(time_of_day=0.375)          # 09:00, a fly's subjective midday
    early, asleep_at = None, None
    for i in range(1, 400):
        out = sleepy.step(circ.Senses(time_of_day=0.375), sub_steps=20)
        if sleepy.arousal >= circ.SLEEP_BELOW:
            break
        if early is None and out["mode"] != "sleep":
            early = round(sleepy._quiet_for, 1)
        if asleep_at is None and out["mode"] == "sleep":
            asleep_at = round(sleepy._quiet_for, 1)
            break
    check("being quiet for a moment is not yet sleep",
          early is not None and early < circ.SLEEP_BOUT_SECONDS,
          f"still awake {early}s into the quiet, against a {circ.SLEEP_BOUT_SECONDS:.0f}s criterion")
    check("but staying quiet is",
          asleep_at is not None and asleep_at >= circ.SLEEP_BOUT_SECONDS,
          f"asleep once quiet for {asleep_at}s")

    # And waking does not need another five minutes. It is not instant either:
    # arousal is carried by the l-LNv cells, which integrate over minutes, so
    # the light has to be on a little while before it clears the line. What the
    # bout criterion guarantees is that once it does clear, sleep ends at once
    # rather than being averaged away.
    woke_after = None
    for i in range(1, 400):
        r = sleepy.step(circ.Senses(time_of_day=0.375, light=1.0), sub_steps=20)
        if r["mode"] != "sleep":
            woke_after = i
            break
    check("a light gets it up again, and in well under a sleep bout",
          woke_after is not None and woke_after < circ.SLEEP_BOUT_SECONDS,
          f"awake {woke_after}s after the light came on, against a "
          f"{circ.SLEEP_BOUT_SECONDS:.0f}s bout")
    check("and waking clears the bout rather than averaging it away",
          sleepy._quiet_for == 0.0, f"bout counter {sleepy._quiet_for}s")

    # Hunger has to cycle. Pinned at its maximum it is not a drive, and it takes
    # "walk" and "groom" out of the mode vocabulary entirely, because mode asks
    # about hunger before it asks about speed.
    rise, fall = coord_const("HUNGER_RISE"), coord_const("HUNGER_FALL")
    to_full = (1.0 - 0.2) / rise / 3600.0
    to_empty = 1.0 / fall / 3600.0
    check("hunger takes hours to build, not minutes",
          to_full > 4.0, f"{to_full:.1f} h awake to go from its default to full")
    check("and a night discharges it",
          to_empty < 24.0, f"{to_empty:.1f} h asleep to go from full to empty")
    # The rates have to balance against a 9-up/15-down day, not an even one.
    up, down = rise * 9 * 3600, fall * 15 * 3600
    check("a day's waking hours carry it across the forage line",
          0.2 + up > 0.5, f"+{up:.2f} over 9 h up, from a 0.2 default")
    check("and a night carries it back under",
          1.0 - down < 0.5, f"-{down:.2f} over 15 h asleep")
    check("so it cycles instead of drifting to a rail",
          abs(up - down) < 0.1 * up, f"+{up:.2f} a day against -{down:.2f} a night")

    # The regression that actually bit: with hunger latched high, an awake fly
    # can only ever forage, because mode asks about hunger before speed. Drive
    # the selector from both sides and see that hunger still decides.
    def mode_at(hunger):
        b = circ.FlyBrain()
        b.settle(time_of_day=0.25)            # 06:00, the morning peak
        b._quiet_for = 0.0
        seen = set()
        for _ in range(40):
            b.hunger = hunger                 # hold it, the coordinator owns drift
            out = b.step(circ.Senses(time_of_day=0.25), sub_steps=20)
            seen.add(out["mode"])
        return seen

    hungry, fed = mode_at(0.9), mode_at(0.1)
    check("a hungry fly forages",
          "forage" in hungry, f"modes seen at hunger 0.9: {sorted(hungry)}")
    check("and a fed one does not -- walk and groom are live, not dead branches",
          "forage" not in fed and bool(fed & {"walk", "groom"}),
          f"modes seen at hunger 0.1: {sorted(fed)}")

    ok = all(_results)
    print(f"\n{sum(_results)}/{len(_results)} checks passed\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
