#!/usr/bin/env python3
"""What a HouseFly tick costs on this machine.

The README's figure comes from a desktop i7, and most Home Assistant installs
run on something much smaller. This runs the same brain Home Assistant runs,
with nothing but numpy, so it can be tried on a Raspberry Pi or a spare board
before installing anything. From the repository root:

    python3 tools/bench.py

An installed fly reports the same number live, as its "Tick cost" diagnostic
sensor, which also counts the time spent reading the house.
"""

from __future__ import annotations

import importlib.util
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TICKS = 30


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "fly_circuits", ROOT / "custom_components" / "fly_house" / "circuits.py")
    circ = importlib.util.module_from_spec(spec)
    sys.modules["fly_circuits"] = circ
    spec.loader.exec_module(circ)

    started = time.perf_counter()
    data = circ.shared_connectome()
    load_s = time.perf_counter() - started

    fly = circ.FlyBrain()
    started = time.perf_counter()
    fly.settle(time_of_day=0.5)
    settle_s = time.perf_counter() - started

    print(f"machine      {platform.machine()}, {platform.processor() or 'cpu unknown'}")
    print(f"python       {platform.python_version()}, numpy {np.__version__}")
    print(f"connectome   {data.n} neurons, {len(data.pre)} synapses, "
          f"loaded in {load_s:.2f} s")
    print(f"settle       {settle_s:.2f} s (once, at startup, off the event loop)")
    print()

    # The interval a fly ticks at, and the sub-steps the coordinator runs for
    # it: int(clip(interval * 20, 10, 60)). The cap means a tick never
    # simulates more than three seconds, so a longer interval is cheaper and
    # the brain runs slower than real time.
    for interval in (2, 3, 6):
        sub_steps = int(np.clip(interval * 20, 10, 60))
        senses = circ.Senses(time_of_day=0.5, light=0.5)
        for _ in range(3):
            fly.step(senses, sub_steps)        # warm the caches first
        times = []
        for _ in range(TICKS):
            started = time.perf_counter()
            fly.step(senses, sub_steps)
            times.append(time.perf_counter() - started)
        mean = statistics.fmean(times)
        lived = sub_steps * circ.DT
        print(f"every {interval} s     {1000 * mean:6.1f} ms a tick "
              f"(slowest {1000 * max(times):.1f}), "
              f"{100 * mean / interval:.1f}% of one core per fly, "
              f"living {lived / interval:.0%} of real time")

    print("\nSeveral flies share one connectome, so each extra fly adds its "
          "tick, not its memory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
