# HouseFly 🪰

[![Validate](https://github.com/Vortitron/HouseFly/actions/workflows/validate.yml/badge.svg)](https://github.com/Vortitron/HouseFly/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)
[![project page](https://img.shields.io/badge/write--up-housefly.vome.io-5ad7ff.svg)](https://housefly.vome.io)

**A fruit fly lives in your Home Assistant. Its brain is the real one.**

HouseFly runs a rate model of 4,724 identified *Drosophila melanogaster* neurons
wired together by 126,108 measured synaptic connections, taken from the Janelia
hemibrain reconstruction and the FlyWire whole-brain dataset. Your sensors are
delivered to the neurons that carry that kind of information in the animal. Its
motor output moves a fly across your dashboard. It learns which parts of your
house it likes.

It is about 450 KB of connectome, a few milliseconds of numpy per tick, and no
GPU.

---

## Why this was rewritten

The previous version described itself as a "leaky reservoir inspired by
fruit-fly motifs". Looking at it honestly, that framing was doing a lot of
work, and three things were wrong at the root.

**The brain was a random number generator with a theme.** A 256-unit reservoir
with `rng.gauss` recurrent weights, `rng.gauss` input projections and
`rng.gauss` readouts, none of which ever changed. Every motor channel was a
fixed random projection of a random projection of your sensors, so each one was
a smoothed Gaussian hovering near 0.5. Nothing the fly did depended on anything.
Every behaviour you could actually observe — the mode classifier, hunger,
phototaxis — was a hand-written `if` statement sitting *beside* the reservoir,
not emerging from it. The reservoir was decorative, and could have been deleted
without changing what the integration appeared to do.

**It advertised the connectome and then declined to use it.** The docstring
named MaleCNS and immediately said it wasn't loading it. That was the one
genuinely interesting thing available, and the data is public, small when
subset, and runs fine in pure numpy. There was no reason not to.

**It sprayed service calls at real hardware.** Every configured output got a
call every tick — 32 entities every 10 seconds, forever, with a value that was
noise. On a real installation that is continuous Zigbee traffic, measurable
relay wear, and an unbounded blast radius with no deadband, no rate limit, no
domain blocklist and no off switch. `cover` was a supported output domain,
which means the documented configuration surface included your garage door.

Smaller things that told the same story: the 16×16 compound eye computed 256
values and fed 16 of them to the brain, discarding 94% of the pipeline; the
"visual field" placed each light by `sum(ord(c)) % 256`, so two lamps in the
same room landed in random opposite corners and the word "visual" meant nothing;
the "spectral radius" was a comment admitting it was a guess; and the card found
its entities by string-replacing `binary_sensor.fly_house_active`, so renaming
one entity broke it.

So the question isn't how to improve the reservoir. It's why there is one.

---

## What it does instead

Replace the random matrix with circuits that have a known function, and give
each one the input it actually carries.

| Circuit | What it does in the animal | What it gets from your house |
|---|---|---|
| **EPG / PEN / PEG / Δ7** | Ring attractor holding heading | Integrates the fly's own turns into a compass |
| **ER ring neurons** | Visual bearing into the ellipsoid body | Bearing to every card on your dashboard |
| **PFL3** | Compares heading against goal, commands a turn | Steers it towards whatever it currently wants |
| **Kenyon cells → MBONs** | Associative memory, with real plasticity | Learns which parts of your house are good |
| **PAM / PPL1 dopaminergic** | Reward and punishment teaching signals | `fly_house.feed` and swatting at it |
| **LPLC2 / LC4 → DNp09/10** | Looming detection → escape | Ranging sensors closing on it; motion; your cursor |
| **Projection neurons** | Odour identity | The state of your house as a smell |
| **s-LNv / LNd / DN1** | Morning and evening circadian oscillators | Real local time |

Everything else follows from those. There is no rule anywhere that says "be
active at dawn" — the morning cells are driven by morning, and arousal is read
off their firing rate.

---

## The parts that are genuinely interesting

### The ring attractor is in the wiring, not in the code

Nobody wrote a ring attractor. The connectome contains one. Bin the effective
EPG → Δ7 → EPG coupling by heading offset, using only measured synapse counts
and the bridge-glomerulus labels:

```
  0 deg          89  #
 45 deg         181  ###
 90 deg         919  #################
135 deg        1791  #################################
180 deg        2025  #####################################
225 deg        1827  ##################################
270 deg         921  #################
315 deg         208  ###
```

Δ7 is inhibitory, so this is local excitation with long-range inhibition — a
Mexican hat, 23:1 — and that is exactly and only what a ring attractor needs.
Run `python3 tools/build_connectome.py` and it prints this from the raw data.

This also caught a mistake. Originally both halves of the protocerebral bridge
were given the same angular order, which produced a much weaker 2.7:1 profile
and a compass that held a heading perfectly well but would only ever turn one
way. The real bridge is a *mirror-symmetric* double map. Correcting it sharpened
the signature to 23:1 — the data told us the anatomy was wrong before any
simulation ran.

### The direction of turning is measured, not assumed

Which way does exciting one hemisphere's PEN cells push the bump? You can read
it straight out of the connectome:

```
EPG -> LEFT  PEN1 -> EPG loop shift:  +12.5 deg
EPG -> RIGHT PEN1 -> EPG loop shift:  -11.5 deg
EPG -> LEFT  PEG  -> EPG loop shift:   -5.6 deg
EPG -> RIGHT PEG  -> EPG loop shift:   +0.9 deg
```

PEN loops shift the bump in opposite directions per hemisphere; PEG loops don't
shift it at all. That is the textbook split between the loop that *moves* the
bump and the loop that *holds* it, and it fell out of the synapse counts.

### Approach, measured properly

LPLC2 fires at an object *expanding* in the visual field. For a target of size
L at range r closing at speed v the angular size is θ ≈ L/r, so the expansion
rate is **θ̇ = L·v/r²**. That r² is the whole character of the response: the same
footsteps count for far more at one metre than at five, which is why a real fly
leaves it so late and then goes all at once.

A ranging sensor — mmWave radar, ultrasonic, BLE distance — gives r directly and
v by differencing, so it delivers exactly the quantity the circuit is built for,
by radar instead of by photons. Point HouseFly at one and someone walking up to
the door produces a genuine looming response:

```
 5.3 m closing   θ̇ 0.022   escape 0.0000
 2.5 m closing   θ̇ 0.101   escape 0.1931
 1.1 m closing   θ̇ 0.521   escape 0.2217
 0.6 m closing   θ̇ 1.250   escape 0.2381
```

Walking away produces nothing, because receding is not looming.

**A camera is usually the wrong source.** Optic flow needs frames close enough
together to correspond. The first install this was tried on had one camera, a
traffic camera whose own `photo_time` showed it updating *every five minutes* —
at that spacing there is no correspondence between frames at all, so flow would
be noise and a looming detector fed from it would fire constantly and mean
nothing.

### It has a memory, and the memory is synapses

Learning in *Drosophila* happens at Kenyon cell → MBON synapses: a Kenyon cell
active at the same moment as a dopaminergic neuron in that MBON's compartment
gets **depressed**. That is the whole rule, it is anti-Hebbian, and it is why a
fly stops approaching things that turned out to be bad.

HouseFly implements exactly that, on 20,391 real KC→MBON connections, and each
MBON's compartment valence is derived from which dopaminergic class dominates
its input rather than hard-coded. Those gains are what gets persisted across
restarts — the fly does not forget your house when Home Assistant updates.

### What the connectome does not contain

Two things were expected to fall out of the wiring and did not. Both are worth
stating plainly, because "we tried to derive it and could not" is a result.

**PFL3's steering computation.** In the animal, PFL3 compares the heading bump
against a goal and its left-right imbalance is the turn command. That works
because each cell's fan-shaped-body arbor sits about a quarter turn from its
bridge arbor, in opposite directions per hemisphere. We tried it both ways --
feeding the goal into the fan-shaped body and letting the connectome do the
rest, and imposing the quarter-turn offset on PFL3 explicitly. Neither gave
reliable goal-following: the correlation between turn command and the sine of
the heading error ranged from +0.03 to -0.54 depending on the trajectory, and
the closed loop never converged. That offset is *where the arbors physically
sit*, and synapse counts between cell types do not carry it.

So the goal-seeking controller lives in `coordinator.py`, four lines of
proportional control, labelled as a controller. The fly holds a heading using a
connectome-derived ring attractor, which is real, and chooses which heading to
hold using arithmetic, which is not. Keeping those visibly separate matters more
than having one more thing to claim.

### The map of your house is *not* in the connectome either

The original plan was to read the landmark-bearing → heading mapping off the
ER → EPG connectivity. It isn't there: that projection is near-uniform, with
about 7% modulation depth and no consistent phase. This is not a gap in the
data. In the real animal that map is **learned**, in plastic ER→EPG synapses
(Fisher et al. 2019; Kim et al. 2019) — a naive fly does not have one.

So HouseFly doesn't fake it. The compass is driven by integrating the fly's own
turns, exactly as a real one is in the dark, and it drifts when it cannot see.

---

## Honest limits

This is a real model of real circuits, and it is still a model.

- **4,724 neurons of about 25,000** in the central brain, and no body, no
  muscles, no proprioception. Most of the input these cells really receive comes
  from neurons that are not here at all, which is why there is a tonic drive
  term standing in for the rest of the brain. That term is an assumption.
- **A rate model, not spikes.** One leaky rate unit per neuron, following the
  approach of Shiu et al. 2024. No dendrites, no delays, no channel dynamics.
- **Synaptic sign comes from predicted transmitter.** Mostly reliable, but
  FlyWire's classifier returns acetylcholine for most ring neurons, which is
  wrong — they are GABAergic. Where the literature is settled it overrides the
  prediction, and every such override is listed in `tools/build_connectome.py`.
- **Roughly six free parameters** — global gains, time constants, an
  excitation/inhibition ratio — tuned so the network sits in a regime where the
  bump is stable. The *connectivity* is untouched; the operating point is not
  derived from anything.
- **Two brains, spliced.** Connectivity is hemibrain (a female fly's central
  brain); positions and transmitters are FlyWire (a different female fly).
  Joined by cell type, which is standard practice and still an approximation.
- **Angular-velocity integration is monotonic and correctly signed** over
  roughly ±2 rad/s and degrades outside it. `tools/validate.py` reports the
  measured correlation rather than a claim.
- **Two circuits needed a static gain constant** (`CIRCUIT_GAIN` in
  `circuits.py`). The fan-shaped body and the Kenyon cells are large and almost
  entirely excitatory with no matching inhibitory population inside the modelled
  subnetwork, so without it they flood. An attempt to have every circuit
  regulate its own gain homeostatically fixed that but destabilised the compass,
  and is written up in the changelog rather than quietly dropped.
- **Adaptation is applied to two circuits, not the network.** Without it the
  looming and descending pathways latch and the fly flees permanently after one
  startle; with it applied everywhere, the compass bump decays.
- **Sensory channels adapt to their own observed range**, so a channel that has
  only ever seen a narrow band will read as more dramatic than it is until it
  has seen a wider one. That is the price of not having to tell it the units.
- **131 glomeruli cannot give every state its own.** Collisions happen, as they
  do in a real fly with ~50 glomeruli, and are resolved downstream by the
  divergence onto Kenyon cells rather than avoided.

It is not conscious, it is not an agent, it does not understand your house, and
it is not a scientific instrument. It is a small animal's wiring diagram with
your sensors plugged into it.

---

## Installation

HACS → ⋮ → Custom repositories → `https://github.com/Vortitron/HouseFly`, category
**Integration**. Install, restart, then **Settings → Devices & Services → Add
Integration → HouseFly**.

Every push runs HACS's own validation action and Home Assistant's hassfest, so
whether this is installable is upstream's verdict rather than ours — currently
9/9 and passing.

Actuation is **off by default**. A fresh install watches and walks; it touches
nothing until you deliberately turn it on.

### Cards

Both register themselves, so no resource setup is needed.

```yaml
# Lets the fly out onto this dashboard. Draws nothing itself: it reports where
# your cards are and paints the fly over the top of them.
- type: custom:housefly-overlay
  show_debug: true      # card outlines and a live brain readout

# The connectome, with live activity in it.
- type: custom:housefly-brain-card
```

### Services

| Service | Effect |
|---|---|
| `fly_house.loom` | Drives LPLC2 → escape. Also punishment, so it learns to dislike where it was. |
| `fly_house.feed` | Drives the PAM dopaminergic neurons. Reward, and reduces hunger. |
| `fly_house.reset_memory` | Every KC→MBON synapse back to its measured strength. |

Clicking the fly on the dashboard calls `loom` with a strength set by how close
you got.

---

## Safety

The fly can only touch things you allowlisted, and only some of what you
allowlist. See [`safety.py`](custom_components/fly_house/safety.py).

- **Never, regardless of configuration:** `lock`, `alarm_control_panel`,
  `cover`, `climate`, `water_heater`, `humidifier`, `valve`, `vacuum`,
  `lawn_mower`, `script`, `automation`, `scene`, `input_boolean`.
- **Refused by name** even in an allowed domain: anything containing `boiler`,
  `freezer`, `pump`, `oven`, `server`, `alarm`, `garage`, `charger`,
  `irrigation` and about twenty more.
- **It has to land on something to touch it.** Actuation is triggered by the
  fly settling on a card, not by a timer — a few interactions an hour.
- **Hourly budget**, per-entity cooldown, a deadband so a jittering brain
  cannot produce a call storm, and optional quiet hours.
- Bad choices are refused in the config flow, while you are still looking at it.

Start it on a spare lamp.

---

## Try it without risking anything

`testbed/` brings up a throwaway Home Assistant containing a fake ten-room
house — 17 lights, 15 switches, 30 drifting sensors, 13 motion detectors, all
template helpers with nothing behind them — plus six entities that exist purely
so you can watch the safety layer refuse them.

```bash
cd testbed && ./up.sh        # http://localhost:8124
```

The dashboard is generated from the same entity list as the house, so it cannot
drift into a wall of "entity not found". Safe to hand to other people.

Booted and verified against Home Assistant 2026.9.2: 92 entities register
cleanly (24 lights, 23 switches, 30 drifting sensors, 15 binary sensors), and
all six trap entities are refused by name — `boiler`, `freezer`, `network`,
`pump`, `door`, `heater`.

---

## Verifying the claims

```bash
python3 tools/validate.py          # runs the shipped brain, checks every claim above
python3 tools/build_connectome.py  # rebuilds the data pack from the public sources
```

CI runs `validate.py` on every push, so these numbers are checked rather than
asserted. A longer write-up lives at **[housefly.vome.io](https://housefly.vome.io)**.

Twenty checks. Cell counts against the literature; the Mexican hat; PEN
hemispheres shifting oppositely; the bump forming, holding still and integrating
turns with the right sign; punishment depressing KC→MBON synapses; looming
raising descending drive *and then stopping*; PFL3 not being saturated flat; and
arousal peaking at dawn and dusk. It prints the numbers, including the marginal
ones. Current output:

```
  a bump forms                              peak 0.223, trough 0.000
  it holds still with no self-motion        0 deg of drift
  turning rotates the bump, right direction correlation +0.99
  escape is transient, not a permanent mood escape fell back to 0.0000
  arousal   03:00 0.17  06:00 1.00  12:00 0.08  18:45 1.00  23:00 0.10
```

---

## Data and credit

Both datasets are CC-BY 4.0 and are fetched at build time, not vendored.

- **Connectivity, cell types, columnar labels** — Janelia hemibrain v1.2.
  Scheffer, Xu, Januszewski, Lu, Takemura, Hayworth et al. (2020),
  *A connectome and analysis of the adult Drosophila central brain*, eLife 9:e57443.
- **Soma positions, transmitter predictions** — FlyWire FAFB.
  Schlegel, Yin, Bates, Dorkenwald, Eichler, Brooks et al. (2024),
  *Whole-brain annotation and multi-connectome cell typing of Drosophila*,
  Nature 634:139–152.

Modelling approach after Shiu, Sterne, Spiller, Franconville, Sandoval,
Zhou et al. (2024), *A leaky integrate-and-fire computational model based on
the connectome of the entire adult Drosophila brain*, Nature 634:210–219.

The flies did the hard part.

---

## Licence

MIT. See [LICENSE](LICENSE).
