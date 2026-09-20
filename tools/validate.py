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
import subprocess
import sys
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
        b.settle(time_of_day=t)
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
    check("landing is what earns an action",
          "DWELL_TICKS" in gate and "_dwell_ticks" in gate,
          "it has to stay on one thing for a few seconds, not merely pass over it")

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

    stub._layout = []
    stub.output_entities = []
    check("and nothing to touch means nothing to stand on",
          ns["_C"]._effective_layout(stub) == [],
          "observe-only installs get no phantom furniture")

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

    ok = all(_results)
    print(f"\n{sum(_results)}/{len(_results)} checks passed\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
