# Changelog

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
  six entities that exist to demonstrate the safety refusals.
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

## 1.0.1 and earlier

See git history. Those releases describe the reservoir implementation, which no
longer exists.
