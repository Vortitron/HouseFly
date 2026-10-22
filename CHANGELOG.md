# Changelog

## 2.20.2 — but a person just after a restart is still a person

2.20.1 treated every change in a fly's first ten minutes as nobody's,
including a person's or an automation's. Only what nobody caused — the states
Home Assistant restores while starting, with no user and no parent context —
is ignored now; a lamp a person switches off just after a restart stays off,
and an automation's change is respected as usual. Check 10c covers both.

## 2.20.1 — a restart is nobody's decision

2.20.0 counted only states stamped *before* a fly started as the house
restoring itself. On the Swarm the template lights rendered two seconds
*after*, with no user and no parent, so every fly took that for a person and
left every light alone for an hour after each restart. Anything stamped during
the first ten minutes — the same startup grace the unusual alert already uses —
is now nobody's decision. Check 10c covers it.

## 2.20.0 — someone else's decision stands

2.19.0 let a fly see a lamp as it is, and the first thing that showed on the
demo box was a fly switching a light back on two to fourteen seconds after the
house's own automation had switched it off — four times an hour on one light.
A person turning off a lamp a fly may touch would have met the same.

A fly now leaves alone anything someone else changed recently: for an hour
after a person (a logged-in user, or a device reporting its own change, which
is what a wall switch looks like), and for ten minutes after an automation, a
script or another fly. It knows which is which from the context Home Assistant
stamps on every change; every fly registers its own, so it can tell another
fly from a person, and a restart's restored states count as nobody's.

Counted as `total_left_to_others`, apart from `total_already_as_wanted` and
from `total_blocked`. Five new checks in section 10c of `tools/validate.py`.

## 2.19.0 — it sees the lamp it lands on

On the sandboxes, a week after 2.16.0, each fly was "refused" about six
hundred times a day and acted about twice. None of those were the safety layer
protecting anything. Three things, all fixed:

- The deadband compared a wish with the fly's own last command, so it never
  noticed anyone else changing a light. It now compares with the light as it
  actually is: a fly that lands on a lamp another fly or a person has switched
  off sees it off.
- A wish that matched the lamp was counted as a safety refusal. It is now
  counted apart, as `total_already_as_wanted`; `total_blocked` means the
  safety layer said no.
- The fly's state barely moved what it asked for. At gains of 0.5 on valence
  and 0.2 on arousal every wish sat between about 0.45 and 0.6 — inside the
  0.15 deadband — so nothing it learned or felt could reach a light. At 2.0
  and 0.4, a learned valence shift of 0.1 is a change of 0.2, and its day is
  bright when it is lively and dim when it is drowsy.

A switch is now asked for as on or off rather than as a level, so "already as
it wants it" means the same thing for a switch as for a lamp. Six new checks
in section 10b of `tools/validate.py`.

## 2.18.0 — rows of numbers, one channel each

A state made of named rows of numbers, `m1:21,18,13;s1:0,0,80`, is now read as
one channel per value, and each channel adapts to its own range like any
numeric sensor. Home Assistant has no array type, so this is how a device
publishes several readings at once; FrontPath sends both radars' per-gate
energies this way, thirty-six numbers a second.

Read as one string it was a word, a new odour every second. And one shared
scale would not do either: a gate over swaying plants sits near 100 all day
while one over open path sits near 20, so a person at the quiet gate would
vanish into the noisy gate's range. Per channel, the fly learns what the wind
does to each gate and a person at an unusually quiet one is new.

A row name has to start with a letter, so a clock time such as `07:45` is
still a word. Two to sixty-four values per entity, so one sensor cannot crowd
out the house. Suspects name the row and position
(`sensor.gate_energies#s2#7`). Four new checks in section 8 of
`tools/validate.py`.

## 2.17.0 — a row of detectors is a row of detectors

A state made only of 0s and 1s, eight to sixty-four long, is now read as that
many separate detectors, one glomerulus per position. FrontPath publishes its
eighteen radar gates this way, street end to door end, and a fly watching it
was getting nonsense: `float("000011000000000000")` succeeds, so the pattern
arrived as one reading of eleven trillion, squeezed by range adaptation into a
number that meant nothing.

Reading it as a word would not have been much better — every pattern its own
glomerulus, so gates 4+5 and gates 4+5+6 as unrelated as two rooms. Per
position, patterns that share gates share glomeruli, which is what lets the
mushroom body habituate to the wind's few repeated patterns while a person
walking the path still reads as new. An all-zero mask is a live channel saying
nothing is there. Suspects name the position (`sensor.gates#4`).

Four new checks in section 8 of `tools/validate.py`.

## 2.1.0 — what a real house exposed

Run against a live installation's entities rather than a generated fake house,
the sensory front end turned out to be destroying most of its input before a
single neuron saw it. Five defects, all in the same twenty lines.

- **Categorical states were flattened to a constant.** Every state that was a
  word rather than a number returned 0.35, so `Allrum`, `Loft` and `Kitchen`
  arrived as the same smell and the mushroom body could not learn that one room
  differed from another. Words now pick a *glomerulus* rather than a magnitude,
  which is how odour identity actually works — and where two collide, the
  measured projection-neuron to Kenyon-cell divergence pulls them apart
  downstream (12% code overlap, verified).
- **One fixed scale for every unit.** `tanh(value / 60)` put seven temperatures
  spanning 11–25 °C into a 0.2-wide band, pinned a 2,840 W power sensor at 1.0,
  and rendered an electricity price of 0.43 as 0.007. Each channel now learns
  its own range, the way a receptor neuron adapts its gain, and the learned
  ranges persist across restarts.
- **`abs(value)`** meant −15 °C and +15 °C were the same reading. On a Swedish
  install that is the signal.
- **`sun.sun` was unparseable**, so the sun was a constant.
- **Dead inputs were silently read as zero.** On the installation tested, four
  of nine configured inputs were `unknown` and nothing said so. Live and dead
  input counts are now attributes on the mode sensor.

Six new checks in `tools/validate.py` cover all of it; 26 total.

## 2.4.0 — install where binaries cannot reach

- **The connectome pack can be fetched at setup** if it is missing or corrupt.
  Normally a no-op: HACS, a clone and a manual copy all bring it along. It
  exists for install routes that cannot carry 432 KB of binary — a text-only
  file API, a constrained pipeline, a sandbox that strips anything but source.
  The URL is pinned to the integration's own version tag so the pack always
  matches the code reading it, and each file is checked against a compiled-in
  SHA-256 and discarded on mismatch. Running the model on an unidentified pack
  would invalidate every measured claim here, so it refuses rather than guesses.
- `tools/validate.py` now checks those checksums against the shipped pack, so
  rebuilding the connectome without regenerating them fails CI rather than
  breaking installs that need the fetch.

## 2.2.x — what a live dashboard exposed

- **Landmarks switched the compass off.** Ring neurons are GABAergic, so
  landmark input reaches the compass as inhibition — about −1.1 per EPG cell
  with 7% spatial modulation on top. Injected raw, a single visible lamp
  silenced the bump, the heading froze at 0 radians, and 0 radians points right:
  the reported symptom was a fly that flew to the right-hand edge and stayed
  there. The component carrying net drive onto EPG is now projected out.
- **The card and the brain each integrated position separately**, so the brain
  took bearings from somewhere the fly visibly was not. The card is the
  authority now.
- **Arousal read a flat 0.0** — reported as "asleep" at eight in the evening —
  because the window was calibrated without sensory input and real input shifts
  the operating point outside it. Measured with the network running instead, and
  padded. Clock cells are also charged during `settle()` rather than taking a
  quarter of an hour.
- **Approach as looming.** Ranging sensors now drive LPLC2 with θ̇ = v/r², the
  actual quantity the circuit responds to.
- **A real tripod gait** with two-link IK legs and feet planted in viewport
  coordinates: zero foot slip during stance, three legs down every frame.
- Novelty feeds goal choice, so the fly goes to look at whatever just changed.

29 checks in `tools/validate.py`.

## 2.0.0 — connectome rewrite

The reservoir is gone. The brain is now a rate model of 4,724 identified
*Drosophila* neurons connected by 126,108 measured synapses.

### Why

The 256-unit reservoir had random recurrent weights, random input projections
and random readouts, none of which ever changed. Every motor channel was a
fixed random projection of a random projection of the sensors, so nothing the
fly did depended on anything. Every observable behaviour — mode, hunger,
phototaxis — was a hand-written conditional sitting beside the reservoir rather
than emerging from it. The reservoir could have been deleted without changing
what the integration appeared to do.

It also cited the connectome in its docstring and then declined to use it, and
wrote a service call to every configured output on every tick with a value that
was noise.

### Added

- **Connectome data pack** (450 KB): Janelia hemibrain v1.2 connectivity joined
  to FlyWire transmitter predictions and soma positions, both CC-BY 4.0, both
  fetched at build time by `tools/build_connectome.py`.
- **Circuits with known function** — central complex compass (EPG/PEN/PEG/Δ7),
  PFL3 steering, mushroom body with real anti-Hebbian plasticity on 20,391
  KC→MBON synapses, LPLC2 looming → descending escape, olfactory projection
  neurons, and the circadian morning and evening oscillators.
- **`housefly-overlay`** — the fly walks over your actual Lovelace dashboard.
  Cards are found by walking the shadow DOM and reported to the brain as
  landmarks with real bearings. Click it to swat at it.
- **`housefly-brain-card`** — the connectome rendered at real soma positions
  with live per-neuron activity, plus the heading bump drawn on the ellipsoid
  body. No WebGL, no CDN.
- **`safety.py`** — domain blocklist, name-based refusal, allowlist, hourly
  budget, per-entity cooldown, deadband, quiet hours. Bad outputs are refused in
  the config flow.
- **Websocket streaming** (`fly_house/subscribe`, `/neurons`, `/connectome`,
  `/layout`) so the visuals run at display rate without writing 1.7 million
  state changes a day to the recorder.
- **`tools/validate.py`** — 17 checks against the shipped brain covering every
  claim in the README.
- **`testbed/`** — a throwaway Home Assistant with a fake ten-room house, plus
  six entities that exist to demonstrate the safety refusals. Verified against
  Home Assistant 2026.9.2: 92 entities register and every trap is refused.
- Learned synaptic weights persist across restarts.

### Changed

- **Actuation is off by default.** A fresh install watches and walks.
- The fly acts by landing on something, not on a timer.
- `poke` became `loom`, because the circuit it drives is a looming detector.
- Sensors report heading, valence, memory, arousal, Kenyon cell sparseness and
  the safety budget instead of ASCII art.

### Removed

- The reservoir, the 16×16 "compound eye" that fed 16 of its 256 values to the
  brain, and the synthetic visual field that placed lights by string hash.
- `cover` as an output domain. It is now permanently blocked.

### Fixed during development, worth recording

- FlyWire's `known_nt` column is free text containing co-transmitters and
  explicit negatives. Reading it literally assigned a synaptic sign of zero to
  EPG — silencing the compass's main excitatory cell. Now parsed properly.
- Ring neurons came back cholinergic from FlyWire's classifier; they are
  GABAergic. The literature overrides the prediction, and every override is
  listed in `tools/build_connectome.py`.
- Normalising each cell's input regardless of sign let Delta7's mutual
  inhibition swallow its EPG drive, so no bump could form. Excitatory and
  inhibitory budgets are now normalised separately.
- Both halves of the protocerebral bridge were given the same angular order.
  The real bridge is a mirror-symmetric double map; correcting it sharpened the
  ring-attractor signature from 2.7:1 to 23:1.
- Measuring bump rotation by unwrapping a coarsely sampled heading aliased past
  180° and certified a backwards compass as correct. Now measured as summed
  wrapped per-step deltas.
- The testbed generator emitted the long-removed `light: - platform: template`
  form. It is valid YAML, so it passed every check short of actually starting
  Home Assistant, which rejects it. The generator now builds Python structures
  and dumps them with PyYAML instead of concatenating strings, and emits the
  modern `template:` schema.
- `testbed/up.sh` now falls back to `sudo docker` and pulls Home Assistant
  through a throwaway client config: a stale `ghcr.io` login is offered for what
  is a public image, and the registry answers `denied: denied`, which reads like
  a missing image rather than a credentials problem.

## 1.0.1 and earlier

See git history. Those releases describe the reservoir implementation, which no
longer exists.
