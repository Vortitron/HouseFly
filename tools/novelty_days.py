#!/usr/bin/env python3
"""How long the familiarity memory should last, measured on a lived-in house.

A house with a routine -- lights morning and evening with up to a quarter of an
hour's jitter, a door twice a day, the television, two motion sensors and four
temperatures -- lived in for several days by the real brain, then two events
planted on the last day: four things that have never happened, at 14:00, and
the evening lights at 03:00. It reports false alarms after the learning day and
whether each planted event was heard, judged the way the alert judges: the
two-minute average of novelty against 0.10.

Time runs ten times fast (a tick is 20 s of the day) with habituation scaled to
match, so five days take about twenty-five minutes. From the repository root:

    python3 tools/novelty_days.py [memory hours, default the shipped one] [days, default 5]

The table in circuits.py, beside NOVELTY_MEMORY_HOURS, came from this.
"""
import hashlib, importlib.util, math, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fly_circuits", ROOT / "custom_components/fly_house/circuits.py")
c = importlib.util.module_from_spec(spec); sys.modules["fly_circuits"] = c; spec.loader.exec_module(c)

tau_h = float(sys.argv[1]) if len(sys.argv) > 1 else c.NOVELTY_MEMORY_HOURS
days = int(sys.argv[2]) if len(sys.argv) > 2 else 5
K, real_tick = 10, 2.0
c.NOVELTY_RECOVERY = 1 - (1 - real_tick / (tau_h * 3600.0)) ** K
c.NOVELTY_DEPRESSION = 1 - (1 - c.NOVELTY_DEPRESSION) ** K
per_day = int(86400 / (real_tick * K))
window = int(120 / (real_tick * K))            # the alert's two minutes
rng = np.random.default_rng(23)

b = c.FlyBrain(); b.settle(time_of_day=0.0)
usable = b.odour_channels
def ch(key):
    return usable[int.from_bytes(hashlib.blake2b(key.encode(), digest_size=4).digest(), "big") % len(usable)]

# A routine, with each day's times jittered by up to a quarter of an hour.
def routine(day):
    j = lambda: rng.uniform(-0.25, 0.25)
    return {
        "light.hall": [(7.0 + j(), 8.0 + j()), (18.0 + j(), 23.0 + j())],
        "light.lounge": [(18.5 + j(), 22.5 + j())],
        "light.kitchen": [(6.75 + j(), 7.5 + j()), (17.5 + j(), 19.0 + j())],
        "switch.tv": [(19.0 + j(), 22.0 + j())],
        "binary_sensor.front_door": [(8.1 + j(), 8.15 + j()), (17.4 + j(), 17.45 + j())],
    }

def on(spans, h):
    return any(a <= h < b for a, b in spans)

def smell(day_spans, h, extra=()):
    v = np.zeros(b.n_odour_channels, np.float32)
    for e, spans in day_spans.items():
        v[ch(e)] += 1.0 if on(spans, h) else 0.0
    awake = 7 <= h < 23
    for m in ("binary_sensor.hall_motion", "binary_sensor.kitchen_motion"):
        v[ch(m)] += 1.0 if (awake and rng.random() < 0.15) else 0.0
    for k, name in enumerate(("sensor.t_lounge", "sensor.t_kitchen", "sensor.t_bed", "sensor.t_out")):
        v[ch(name)] += 0.5 + 0.3 * math.sin(2 * math.pi * (h - 9 - k) / 24) + rng.normal(0, 0.02)
    for e in extra:
        v[ch(e)] += 1.0
    return np.clip(v, 0, 1.5)

plants = {  # last day only: (start hour, end hour) -> what is added / forced on
    "never seen, four at 14:00": (14.0, 14.33, ["switch.p1", "switch.p2", "switch.p3", "switch.p4"], {}),
    "evening lights at 03:00": (3.0, 3.33, [], {"light.hall": [(3.0, 3.33)], "light.lounge": [(3.0, 3.33)]}),
}

nov, hours, dayno = [], [], []
for d in range(days):
    spans = routine(d)
    for t in range(per_day):
        h = t / per_day * 24
        extra, today = [], spans
        if d == days - 1:
            for _, (a, z, add, force) in plants.items():
                if a <= h < z:
                    extra += add
                    today = {**today, **{k: today.get(k, []) + v for k, v in force.items()}}
        nov.append(b.step(c.Senses(time_of_day=h / 24, light=0.5, odour=smell(today, h, extra)), 40)["novelty"])
        hours.append(h); dayno.append(d)
nov = np.array(nov); hours = np.array(hours); dayno = np.array(dayno)
avg = np.array([nov[max(0, i - window + 1):i + 1].mean() for i in range(len(nov))])
above = avg >= 0.10
onsets = np.flatnonzero(above & ~np.r_[False, above[:-1]])

def in_plant(i):
    return dayno[i] == days - 1 and any(a <= hours[i] < z + 1 / 6 for a, z, _, _ in plants.values())

false = [i for i in onsets if dayno[i] >= 1 and not in_plant(i)]
print(f"tau {tau_h:g} h, {days} days: Kenyon cells habituated below 0.5 at the end: "
      f"{int((b.kc_habituation < 0.5).sum())} of {len(b.kc_habituation)}")
print(f"  false alarms after the learning day: {len(false)} "
      f"({len(false) / max(1, days - 1):.1f} a day) at {[f'd{dayno[i]+1} {hours[i]:.1f}h' for i in false][:10]}")
for name, (a, z, _, _) in plants.items():
    sel = (dayno == days - 1) & (hours >= a) & (hours < z + 1 / 6)
    print(f"  {name}: peak two-minute average {avg[sel].max():.3f} -> {'HEARD' if avg[sel].max() >= 0.10 else 'missed'}", flush=True)
