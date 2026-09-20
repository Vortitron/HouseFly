"""Connectome-constrained rate model of the circuits HouseFly actually uses.

This is not a metaphor and not a random reservoir. The recurrent weight matrix
is 126,108 measured synaptic connections between 4,724 identified neurons of
Drosophila melanogaster, taken from the Janelia hemibrain (Scheffer et al.
2020) with transmitter identity from FlyWire (Schlegel et al. 2024). Nothing
in the connectivity is invented; the only free parameters are the global
gains, time constants, and how house sensors are mapped onto sensory neurons.

The modelling approach -- a leaky rate unit per neuron, synaptic sign from
predicted transmitter, weights normalised by each cell's total input -- follows
Shiu et al. 2024 (Nature 634:210-219), who showed this is enough to reproduce
real behaviour from connectome structure alone.

Circuits modelled
-----------------
compass     EPG / PEN / PEG / Delta7  -- ring attractor holding heading
ring        ER / ExR                  -- visual landmark bearing into the EB
steer       PFL3 / PFN / hDelta / FC  -- heading-vs-goal comparison, turn command
mb_*        KC / MBON / DAN / APL     -- associative learning, with real plasticity
olfactory   projection neurons        -- the "smell" of the house
loom        LPLC2 / LC4 / LC6         -- looming detection
descending  DNp09 / DNp10 / DNa02     -- escape and steering commands
clock       s-LNv / LNd / DN1         -- circadian morning + evening oscillators
"""

from __future__ import annotations

import gzip
import json
import re
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

CONNECTOME_DIR = Path(__file__).parent / "connectome"

# Rate-model constants. Time constants are in seconds.
TAU_FAST = 0.05     # descending neurons, looming -- reflexes are quick
TAU_DEFAULT = 0.12
TAU_CLOCK = 180.0   # clock neurons integrate over minutes, not milliseconds
DT = 0.05           # internal integration step (20 Hz)

# How hard the recurrent connectome drives the network. Tuned so the compass
# holds a single stable bump without the whole network saturating.
RECURRENT_GAIN = 5.0
ACTIVATION_THRESHOLD = 0.10   # below this a unit is silent, which is what lets a bump form
# Per-circuit gain, applied as a divisor *after* rectification.
#
# Almost every circuit is left at 1.0 and governed only by the global
# normalisation above. Two are not, and the reason is worth stating.
#
# The fan-shaped body columnar network (`steer`) is 1,531 neurons and almost
# entirely excitatory, with no large inhibitory population of its own in this
# subnetwork. Left alone it floods: every PFL3 cell saturates at the same rate,
# the left-right difference that *is* the steering command goes to zero, and the
# fly can only fly in a straight line. The Kenyon cells have the same problem
# for the same reason, though their sparseness control masks it.
#
# An earlier attempt let every circuit regulate its own gain homeostatically.
# That fixed the flooding and made escape properly transient, but it also
# destabilised the compass -- a bump has most of its cells at zero, so the
# circuit's mean activity is set by a handful of neurons, and feeding that back
# as a gain signal made the bump wander 429 degrees with no self-motion at all.
# Two static constants on the two circuits that actually need them cost less and
# break nothing.
CIRCUIT_GAIN = {"steer": 7.0, "mb_kc": 3.0}

# Circuits whose activity is phasic -- a burst, not a mood -- and which get
# spike-frequency adaptation so they cannot latch.
#
# The looming and descending pathways are strongly convergent and, without this,
# a single loom pushes them into a self-sustaining state they never leave: the
# fly is startled once and then flees for the rest of its life. Adaptation is
# applied only here rather than network-wide, because the compass bump depends
# on exactly the kind of sustained activity that adaptation removes.
ADAPTING_CIRCUITS = ("loom", "descending")
SATURATION_RATE = 1.0         # maximum sustained rate, in normalised units
NORMALISATION_GAIN = 0.5      # global gain control standing in for widefield inhibition

# How strongly inhibitory synapses are weighted relative to excitatory ones,
# after each cell's two input budgets are normalised separately. This is the
# model's single most important free parameter: below about 4 the ellipsoid
# body has no bump, above about 8 the network falls silent. GABA-A and GluCl
# conductances in fly neurons are genuinely larger and longer-lasting than
# nicotinic ACh currents, so inhibition-dominance is the expected regime.
INHIBITORY_GAIN = 5.0

# Tonic background excitation. We model 4,724 neurons out of roughly 25,000 in
# the central brain, so most of the input these cells actually receive comes
# from neurons that are not in the subnetwork at all. Without a stand-in for
# that missing drive the excised circuit simply sits at zero. This is the price
# of modelling a piece of a brain rather than all of it, and it is a real
# assumption rather than a fitted constant.
TONIC_DRIVE = 0.10

# How hard angular velocity drives the PEN cells that shift the bump.
PEN_GAIN = 9.0

# How hard a visible landmark modulates the ring neurons, about their mean.
#
# Swept against thirteen landmark layouts, including the awkward ones (a single
# lamp, two opposed, and randomly scattered): at 0.1 and above the bump still
# collapsed on some of them, and at 0.02 the landmarks barely moved the heading.
# 0.05 holds the bump on every layout while still swinging the settled heading
# by about 94 degrees across them, which is the point of having landmarks.
RING_GAIN = 0.05

# How hard the goal bearing is written into the fan-shaped body columns. The
# columnar network is large and mostly excitatory, so this has to stay small or
# it floods and every PFL3 cell ends up at the same rate.
FB_GOAL_GAIN = 0.12


# Converts summed clock-neuron firing into an arousal level in 0..1.
#
# Measured across a simulated day, the summed clock rate runs 0.601 at its
# quietest to 0.743 at its peak. The morning cells peak at 06:00 and the evening
# cells at 18:00, with nothing anywhere telling them to. It is a narrow band
# because 27 cells inside a 4,724-neuron network is a narrow thing; the shape is
# what matters, not the amplitude.
#
# The window is deliberately wider than that measured swing. An earlier version
# fitted it tightly, and on a live house the readout sat flat at 0.0 -- reported
# as "asleep" at eight in the evening -- because real sensory input shifts the
# operating point and anything outside a 0.058-wide window clips. A wider window
# costs contrast and buys never lying.
#
# An adaptive window was tried instead and removed: it works over a real day,
# but a brain held at a single time of day has no range to learn from, so the
# window collapses and every hour reads 1.00. Not everything should adapt.
AROUSAL_LO = 0.565
AROUSAL_HI = 0.779

# Below this fraction of the arousal range, the fly is asleep.
SLEEP_BELOW = 0.34

# Spike-frequency adaptation. Every neuron accumulates a slow self-inhibition
# in proportion to how much it has recently been firing.
#
# This is not decoration. Without it the strongly recurrent excitatory parts of
# the connectome latch: a single looming stimulus pushes the escape pathway into
# a self-sustaining state it never leaves, so the fly flees forever; and the
# fan-shaped body saturates uniformly, so every PFL3 cell sits at the same rate,
# the left-right difference is zero, and the fly can only fly in a straight
# line. Adaptation is also simply what real neurons do, and it is why a real
# escape response is a burst rather than a new permanent mood.
TAU_ADAPT = 1.2
ADAPT_GAIN = 3.0
KC_SPARSENESS_TARGET = 0.05   # ~5% of Kenyon cells active, as measured in vivo

# Familiarity, in the alpha'3 compartment.
#
# This is the one part of the fly that answers "what is it *for*". The mushroom
# body's job is not to control anything -- it is to tell the animal whether it
# has met this situation before. Dasgupta, Stevens & Navlakha (2017, Science)
# showed the Kenyon cell layer is a locality-sensitive hash: a sparse random
# projection whose codes stay close for similar inputs and separate for
# different ones, which is an efficient novelty detector and was published as
# one. Hattori et al. (2017, Cell) found the circuit that reads it out --
# repeated exposure to an odour depresses KC->MBON-alpha'3 synapses whether or
# not anything good or bad happened, so those cells fire hard for something new
# and barely at all for something the fly has met many times.
#
# The compartment matters. Depressing the valence MBONs would confound "I have
# seen this" with "this was bad", and they are genuinely separate compartments
# in the animal: alpha'3 is MBON16, MBON17 and MBON28 in the hemibrain naming,
# and none of them is one of the approach/avoid cells.
#
# Timescales are set for a house rather than for an odour-delivery rig. A
# pattern that persists for a few minutes stops being news; six hours of not
# seeing it makes it news again.
NOVELTY_COMPARTMENT = ("MBON16", "MBON17", "MBON28")
NOVELTY_DEPRESSION = 0.02     # per tick, at full presynaptic activity
NOVELTY_RECOVERY = 1.2e-4     # per tick, back towards naive
# A Kenyon cell counts as part of the code only above this rate. Without a
# floor, the whole population habituates: every cell carries a little activity,
# and over a few hundred ticks that is enough to make nothing novel ever again.
# Measured with a graded trace, a genuinely new pattern sharing 12% of its cells
# with a familiar one still read 0.386 instead of the ~0.88 the overlap implies.
# The floor is the same one the sparse-code readout uses, which is the point --
# it is the code, or it is not.
KC_ACTIVE_FLOOR = 0.05

# How many projection-neuron channels carry the time of day rather than a smell.
#
# Familiarity without context is the wrong question. A single habituation trace
# learns "lights on" and then finds lights on at three in the morning perfectly
# ordinary, because the Kenyon code for it is identical at every hour.
# Measured: 400 evenings of a pattern gave novelty 0.025, and the same pattern
# presented at 03:00 gave 0.025. The fly had no idea what time it was.
#
# The fix costs nothing structural, because the Kenyon layer is a random
# projection of whatever reaches it: give it the clock and the code for
# "lights on at 3am" stops being the code for "lights on at 7pm", so
# habituation becomes time-local on its own and "unusual" starts meaning
# unusual *for this hour*.
#
# The channels are driven by the modelled clock cells themselves rather than by
# a synthetic ramp, so they inherit the learned photoperiod for free -- move
# the house's dawn and the context moves with it.
#
# What is a modelling choice and not a finding: that the clock reaches the
# Kenyon layer at all. Drosophila Kenyon cells are predominantly olfactory,
# with some visual and thermo/hygro input, and the mushroom body is known to be
# state-modulated -- but "DN1 projects to KCs" is not a claim being made here.
# What reaches the code is our decision, as it is for every other input.
CLOCK_CHANNELS = 8

# How hard the clock drives its channels, relative to a smell at full strength.
# Enough to change the code, not so much that the hour drowns out the house.
CLOCK_CONTEXT_GAIN = 0.55

# How hard ambient light drives l-LNv. Small on purpose: this should be able to
# rouse a sleeping fly when someone turns a light on, and should not be able to
# hold it awake all day against a clock that says otherwise.
LIGHT_AROUSAL = 0.45


def _circadian_bump(t: float, centre: float, width: float) -> float:
    """A Gaussian on a circle.

    The day wraps, and the plain squared difference does not. With dusk learned
    at 23:30 and the time 00:15 the naive form measures three quarters of a day
    of separation and reports no evening at all, which is a bug that only shows
    up in winter or on a late-rising house.
    """
    d = (t - centre) % 1.0
    if d > 0.5:
        d -= 1.0
    return math.exp(-(d * d) / width)


def _threshold(x: np.ndarray) -> np.ndarray:
    """Threshold-linear rectification.

    The threshold is what makes a bump possible: units that lose the local
    competition must go to exactly zero, not merely to a smaller number, or the
    Delta7 ring inhibition has nothing to bite on and the whole ellipsoid body
    settles into one flat, uniformly active blob.
    """
    return np.maximum(x - ACTIVATION_THRESHOLD, 0.0)


def _saturate(pos: np.ndarray) -> np.ndarray:
    """Cap the firing rate.

    Threshold-linear alone is unbounded above, so cells with a lot of
    converging input -- the descending neurons especially -- run away to rates
    of 5 or 10 while everything else sits near 0.1, which makes every readout
    meaningless. Below SATURATION_RATE this is still linear, so the competition
    that builds the bump is untouched; above it, it flattens.
    """
    pos *= SATURATION_RATE / (SATURATION_RATE + pos)
    return pos


# A bare hemisphere suffix in a hemibrain instance name, as on DNp09_R. The
# negative lookahead stops it matching the L in a name like _Lo.
_BARE_SIDE_RE = re.compile(r"_([LR])(?![a-zA-Z])")


@dataclass
class ConnectomeData:
    """The shipped data pack, loaded once and shared between instances."""

    pre: np.ndarray
    post: np.ndarray
    weight: np.ndarray          # normalised, signed
    raw_weight: np.ndarray      # original synapse counts
    sign: np.ndarray
    phase: np.ndarray
    side: np.ndarray
    glomerulus: np.ndarray
    column: np.ndarray
    pos: np.ndarray
    types: list[str]
    instances: list[str]
    groups: list[str]
    transmitters: list[str]
    group_index: dict[str, np.ndarray]
    sources: list[dict[str, Any]]
    n: int

    @classmethod
    def load(cls, directory: Path | None = None) -> "ConnectomeData":
        d = directory or CONNECTOME_DIR
        core = np.load(d / "core.npz")
        with gzip.open(d / "meta.json.gz", "rt") as fh:
            meta = json.load(fh)

        n = int(meta["n_neurons"])

        # Hemisphere, repaired for packs built before the name parser learned
        # about bare _L / _R suffixes. It only ever recognised the
        # protocerebral-bridge form (EPG(PB08)_L4), so the central complex had
        # a side and nothing else did: every LC, LPLC2 and DNp cell in the pack
        # read as side 0. Filling the gaps at load costs nothing and changes no
        # existing behaviour -- the cells that already had a side get the same
        # answer from both routes, which tools/validate.py checks -- and the
        # whole block becomes a no-op once a pack is rebuilt.
        side = core["side"].astype(np.int8)
        missing = side == 0
        if missing.any():
            for i in np.flatnonzero(missing):
                bare = _BARE_SIDE_RE.search(meta["instances"][i])
                if bare:
                    side[i] = -1 if bare.group(1) == "L" else 1
        pre = core["pre"].astype(np.int32)
        post = core["post"].astype(np.int32)
        raw = core["weight"].astype(np.float32)
        sign = core["sign"].astype(np.float32)

        # Normalise excitatory and inhibitory input separately, per cell.
        #
        # The obvious thing -- divide by each cell's total input regardless of
        # sign -- does not work, and the failure is instructive. Delta7 cells
        # get 580 inhibitory synapses from each other against 386 excitatory
        # ones from EPG, so a sign-blind normalisation lets their mutual
        # inhibition swallow the EPG drive, the ring inhibition never engages,
        # and the ellipsoid body settles into a uniformly active blob with no
        # bump at all. Measured on the real matrix, the uniform Fourier mode
        # beats the cosine mode 0.021 to 0.018, and a ring attractor needs the
        # opposite.
        #
        # Normalising the two budgets separately says instead: every cell
        # receives unit excitatory and unit inhibitory drive when its inputs
        # fire at unit rate, and the excitation/inhibition balance becomes one
        # interpretable global parameter rather than an accident of synapse
        # counts. At INHIBITORY_GAIN 5 the cosine mode leads the uniform mode
        # by roughly 1.6x and the bump is stable.
        is_exc = sign[pre] > 0
        is_inh = sign[pre] < 0
        exc_in = np.bincount(post, weights=raw * is_exc, minlength=n).astype(np.float32)
        inh_in = np.bincount(post, weights=raw * is_inh, minlength=n).astype(np.float32)
        exc_in[exc_in == 0.0] = 1.0
        inh_in[inh_in == 0.0] = 1.0
        w = np.where(
            is_exc,
            raw / exc_in[post],
            np.where(is_inh, -INHIBITORY_GAIN * raw / inh_in[post], 0.0),
        )

        return cls(
            pre=pre,
            post=post,
            weight=w.astype(np.float32),
            raw_weight=raw,
            sign=sign,
            phase=core["phase"].astype(np.float32),
            side=side,
            glomerulus=core["glomerulus"].astype(np.int8),
            column=core["column"].astype(np.int8),
            pos=core["pos"].astype(np.float32),
            types=meta["types"],
            instances=meta["instances"],
            groups=meta["groups"],
            transmitters=meta["transmitters"],
            group_index={k: np.asarray(v, dtype=np.int32)
                         for k, v in meta["group_index"].items()},
            sources=meta["sources"],
            n=n,
        )


_SHARED: ConnectomeData | None = None


def shared_connectome() -> ConnectomeData:
    """Load the data pack once per process; it is read-only and ~450 KB."""
    global _SHARED
    if _SHARED is None:
        _SHARED = ConnectomeData.load()
    return _SHARED


def _typed(data: ConnectomeData, *prefixes: str) -> np.ndarray:
    """Indices of neurons whose hemibrain type starts with any prefix."""
    return np.asarray(
        [i for i, t in enumerate(data.types) if t.startswith(prefixes)],
        dtype=np.int32,
    )


@dataclass
class FlyBrain:
    """A running fly. One per config entry."""

    data: ConnectomeData = field(default_factory=shared_connectome)

    # State
    rate: np.ndarray = field(init=False)
    adapt: np.ndarray = field(init=False)
    kc_mbon_gain: np.ndarray = field(init=False)   # the plastic synapses
    tick: int = 0
    time_s: float = 0.0

    # Behavioural state exposed to the rest of the integration
    heading: float = 0.0
    goal: float = 0.0
    turn: float = 0.0
    speed: float = 0.0
    escape_drive: float = 0.0
    valence: float = 0.0
    arousal: float = 0.5
    hunger: float = 0.2

    def __post_init__(self) -> None:
        d = self.data
        self.rate = np.zeros(d.n, dtype=np.float32)
        self.adapt = np.zeros(d.n, dtype=np.float32)
        self._last_seconds = DT

        # --- cache the index sets we read and write every tick -------------
        self.i_epg = _typed(d, "EPG")
        self.i_pen = _typed(d, "PEN_a", "PEN_b")
        self.i_d7 = _typed(d, "Delta7")
        self.i_er = d.group_index.get("ring", np.empty(0, np.int32))
        self.i_pfl3 = _typed(d, "PFL3")
        self.i_pfl2 = _typed(d, "PFL2")
        self.i_fb = _typed(d, "hDelta", "FC", "FS", "PFN")
        self.i_kc = d.group_index.get("mb_kc", np.empty(0, np.int32))
        self.i_mbon = d.group_index.get("mb_out", np.empty(0, np.int32))
        self.i_dan = d.group_index.get("mb_dan", np.empty(0, np.int32))
        self.i_apl = d.group_index.get("mb_inh", np.empty(0, np.int32))
        self.i_pn = d.group_index.get("olfactory", np.empty(0, np.int32))
        # The tail of the projection-neuron population is reserved for clock
        # context. The coordinator is told to keep its odours off them.
        self.i_clock_ctx = (self.i_pn[-CLOCK_CHANNELS:] if len(self.i_pn) > CLOCK_CHANNELS
                            else np.empty(0, np.int32))
        self.n_odour_channels = max(0, len(self.i_pn) - len(self.i_clock_ctx))
        self.i_loom = _typed(d, "LPLC2", "LC4", "LC6")
        self.i_dnp = _typed(d, "DNp")
        self.i_dna = _typed(d, "DNa")
        self.i_clock_m = _typed(d, "s-LNv", "5th s-LNv", "l-LNv")   # morning
        self.i_llnv = _typed(d, "l-LNv")                            # light-driven arousal
        self.i_clock_e = _typed(d, "LNd", "DN1", "LPN")             # evening

        # Escape command neurons: DNp09 and DNp10 are the giant-fibre-adjacent
        # pathway driving takeoff; keep them separate from steering DNs.
        self.i_escape = np.asarray(
            [i for i, t in enumerate(d.types) if t in ("DNp09", "DNp10", "DNp11")],
            dtype=np.int32,
        )

        # --- per-circuit gain control ---------------------------------------
        # Divisive normalisation is applied within each circuit rather than
        # across the whole network. A single global term cannot serve both a
        # 152-neuron compass held in balance by Delta7 and a 1,531-neuron
        # fan-shaped body that is almost entirely excitatory: set it for the
        # compass and the columnar network floods until every PFL3 cell sits at
        # the same rate and the fly can only fly straight; set it for the
        # columnar network and the bump is crushed.
        #
        # Doing it per circuit is also the more honest model. Each of these
        # regions has its own local inhibitory population doing exactly this
        # job -- APL across the mushroom body, Delta7 across the bridge, the
        # ring neurons across the ellipsoid body -- so gain control really is
        # local rather than brain-wide.
        group_names = sorted(d.group_index)
        self.group_id = np.zeros(d.n, dtype=np.int32)
        for k, name in enumerate(group_names):
            self.group_id[d.group_index[name]] = k
        self.n_groups = len(group_names)
        self.group_size = np.bincount(
            self.group_id, minlength=self.n_groups
        ).astype(np.float32)
        self.group_size[self.group_size == 0] = 1.0
        self.circuit_gain = np.ones(d.n, dtype=np.float32)
        self.adapting = np.zeros(d.n, dtype=np.float32)
        for name in group_names:
            idx = d.group_index[name]
            if name in CIRCUIT_GAIN:
                self.circuit_gain[idx] = CIRCUIT_GAIN[name]
            if name in ADAPTING_CIRCUITS:
                self.adapting[idx] = 1.0

        # --- per-neuron time constants -------------------------------------
        self.tau = np.full(d.n, TAU_DEFAULT, dtype=np.float32)
        self.tau[self.i_dnp] = TAU_FAST
        self.tau[self.i_dna] = TAU_FAST
        self.tau[self.i_loom] = TAU_FAST
        self.tau[self.i_clock_m] = TAU_CLOCK
        self.tau[self.i_clock_e] = TAU_CLOCK

        # --- compass geometry ----------------------------------------------
        # EPG phase comes straight from the protocerebral bridge glomerulus
        # labels in the connectome, not from anything we invented.
        self.epg_phase = d.phase[self.i_epg].astype(np.float32)
        ok = ~np.isnan(self.epg_phase)
        self.i_epg = self.i_epg[ok]
        self.epg_phase = self.epg_phase[ok]
        self.epg_cos = np.cos(self.epg_phase)
        self.epg_sin = np.sin(self.epg_phase)

        # Ring neurons carry visual azimuth into the ellipsoid body, but they
        # have no bridge glomerulus, so the connectome gives them no label to
        # read a phase off. Derive it instead: an ER neuron's preferred heading
        # is the circular mean of the headings of the EPG cells it talks to,
        # weighted by real synapse counts. That is its receptive field, and it
        # comes out of the wiring rather than out of an assumption.
        self.neuron_phase = self._derive_phases()
        self.er_phase = self.neuron_phase[self.i_er]

        # How much net drive each ring neuron delivers to the compass. Used to
        # make landmark input shape the bump without switching it off: see the
        # note in _sensory_drive.
        epg_set = np.zeros(d.n, dtype=bool)
        epg_set[self.i_epg] = True
        onto_epg = epg_set[d.post]
        net = np.bincount(d.pre[onto_epg], weights=d.weight[onto_epg], minlength=d.n)
        self.er_to_epg = net[self.i_er].astype(np.float32)
        norm = float(self.er_to_epg @ self.er_to_epg)
        self.er_to_epg_norm = norm if norm > 1e-12 else 1.0

        # PEN side determines which way the bump rotates: left-hemisphere PENs
        # shift the bump one way, right-hemisphere the other. That asymmetry is
        # the fly's angular velocity integrator.
        self.pen_side = d.side[self.i_pen].astype(np.float32)

        # PFL3 neurons tile the fan-shaped body; their left/right imbalance is
        # the steering command that actually drives walking in the animal.
        self.pfl3_side = d.side[self.i_pfl3].astype(np.float32)
        pfl3_phase = d.phase[self.i_pfl3]
        self.pfl3_phase = np.where(np.isnan(pfl3_phase), 0.0, pfl3_phase).astype(np.float32)

        fb_phase = self.neuron_phase[self.i_fb]
        fb_col = d.column[self.i_fb].astype(np.float32)
        # Prefer the fan-shaped-body column label where present, else the bridge.
        col_phase = np.where(fb_col >= 1, 2 * np.pi * ((fb_col - 1) % 9) / 9.0, np.nan)
        self.fb_phase = np.where(~np.isnan(col_phase), col_phase, fb_phase).astype(np.float32)

        # --- mushroom body plasticity --------------------------------------
        self._setup_mushroom_body()

        # Seed the compass with a bump so it starts somewhere rather than at
        # a degenerate all-zero fixed point.
        self.rate[self.i_epg] = 0.4 * (1.0 + np.cos(self.epg_phase))

        # Settling is deliberately *not* done here. It takes a couple of
        # seconds of CPU, and FlyBrain is constructed on Home Assistant's event
        # loop; the coordinator calls settle() from an executor thread instead.

    def settle(self, time_of_day: float = 0.5, seconds: float = 120.0) -> None:
        """Run the network forward with no sensory input, to a resting state.

        The time of day matters here and is not a detail. Clock neurons
        integrate over minutes, so a fly settled at noon and then handed the
        real time at six in the morning spends its first quarter of an hour of
        life asleep, looking for all the world like a broken integration.

        Their time constant is shortened for the duration so they reach the
        state they would have reached after fifteen simulated minutes, without
        anyone having to wait for it.
        """
        slow = np.concatenate([self.i_clock_m, self.i_clock_e]).astype(np.int32)
        original = self.tau[slow].copy()
        self.tau[slow] = TAU_DEFAULT
        try:
            self.step(Senses(time_of_day=time_of_day), sub_steps=int(seconds / DT))
        finally:
            self.tau[slow] = original
        self.tick = 0

    # -------------------------------------------------------------- phases
    def _derive_phases(self) -> np.ndarray:
        """Give every neuron a preferred heading, propagated through the wiring.

        Start from the EPG cells, whose heading is fixed by their protocerebral
        bridge glomerulus. Then repeatedly assign each remaining neuron the
        circular mean of its already-known synaptic partners, weighted by real
        synapse counts. Two rounds reach essentially the whole central complex.
        Neurons that never connect to the compass keep a phase of zero and are
        simply never used for anything directional.
        """
        d = self.data
        phase = d.phase.copy().astype(np.float32)
        known = ~np.isnan(phase)

        for _ in range(3):
            cx = np.zeros(d.n, dtype=np.float64)
            cy = np.zeros(d.n, dtype=np.float64)
            for src, dst in ((d.pre, d.post), (d.post, d.pre)):
                m = known[src]
                if not np.any(m):
                    continue
                # Signed, because an inhibitory cell encodes the *opposite*
                # heading to the one it suppresses. Multiplying by the synaptic
                # sign rotates its contribution by 180 degrees, which is what
                # turns "the wedges this ring neuron silences" into "the
                # bearing this ring neuron is looking at".
                w = d.raw_weight[m] * d.sign[src[m]]
                a = phase[src[m]]
                cx += np.bincount(dst[m], weights=w * np.cos(a), minlength=d.n)
                cy += np.bincount(dst[m], weights=w * np.sin(a), minlength=d.n)
            strength = np.hypot(cx, cy)
            fresh = (~known) & (strength > 0)
            if not np.any(fresh):
                break
            phase[fresh] = np.arctan2(cy[fresh], cx[fresh]).astype(np.float32) % (2 * np.pi)
            known = known | fresh

        return np.where(np.isnan(phase), 0.0, phase).astype(np.float32)

    # ------------------------------------------------------------------ MB
    def _setup_mushroom_body(self) -> None:
        """Wire up the plastic KC->MBON synapses and their teaching signals.

        In Drosophila, learning happens at KC->MBON synapses: a Kenyon cell
        active at the same time as a dopaminergic neuron in that MBON's
        compartment gets *depressed*. That is the whole rule, and it is
        anti-Hebbian, which is why the fly learns to stop approaching things
        that turned out to be bad.
        """
        d = self.data
        # Locate the KC->MBON edges inside the edge list so we can modulate
        # them in place without rebuilding the sparse matrix each tick.
        is_kc = np.zeros(d.n, dtype=bool)
        is_kc[self.i_kc] = True
        is_mbon = np.zeros(d.n, dtype=bool)
        is_mbon[self.i_mbon] = True
        self.kc_mbon_edges = np.where(is_kc[d.pre] & is_mbon[d.post])[0].astype(np.int32)
        self.kc_mbon_gain = np.ones(len(self.kc_mbon_edges), dtype=np.float32)
        self.kc_mbon_base = d.weight[self.kc_mbon_edges].copy()

        # The alpha'3 compartment, and the subset of KC->MBON synapses landing
        # in it. Habituation acts on these and on nothing else.
        types = np.asarray(d.types)
        self.i_novelty = np.asarray(
            [i for i in self.i_mbon if types[i] in NOVELTY_COMPARTMENT], dtype=np.int32)
        in_novelty = np.zeros(d.n, dtype=bool)
        in_novelty[self.i_novelty] = True
        self.kc_novelty_mask = in_novelty[d.post[self.kc_mbon_edges]]
        # Naive: every synapse at full strength, so the first thing it ever
        # sees is maximally surprising. That is the correct starting state and
        # it is why a fresh install reports everything as novel for a while.
        # Habituation is held per Kenyon cell rather than per synapse, and the
        # reason is a limit of the data rather than a modelling preference: the
        # pack reconstructs 623 of the KC->alpha'3 synapses out of 20,391
        # KC->MBON synapses in total, from 330 of 1,927 Kenyon cells. With ~25
        # cells active at a time that is about four synapses carrying the
        # readout, which is too thin to read a rate from -- measured, it sat at
        # exactly zero for a hundred ticks and then jumped to 0.999.
        #
        # A presynaptic trace is well sampled, it is the same claim (a cell's
        # output weakens where it has been active before), and it still drives
        # the network through the alpha'3 edges.
        self.kc_habituation = np.ones(len(self.i_kc), dtype=np.float32)
        self.kc_slot = np.full(d.n, -1, dtype=np.int32)
        self.kc_slot[self.i_kc] = np.arange(len(self.i_kc), dtype=np.int32)
        self.novelty = 1.0

        # Compartment assignment, derived rather than hard-coded: an MBON
        # belongs to the compartment of whichever DAN class synapses onto it
        # most strongly. PAM compartments report reward, PPL1 punishment.
        slot = np.full(d.n, -1, dtype=np.int32)
        slot[self.i_mbon] = np.arange(len(self.i_mbon), dtype=np.int32)
        types_arr = np.asarray(d.types)
        is_pam = np.char.startswith(types_arr, "PAM")
        is_ppl = np.char.startswith(types_arr, "PPL1")
        onto_mbon = slot[d.post] >= 0
        pam_w = np.bincount(
            slot[d.post[onto_mbon & is_pam[d.pre]]],
            weights=d.raw_weight[onto_mbon & is_pam[d.pre]],
            minlength=len(self.i_mbon),
        ).astype(np.float32)
        ppl_w = np.bincount(
            slot[d.post[onto_mbon & is_ppl[d.pre]]],
            weights=d.raw_weight[onto_mbon & is_ppl[d.pre]],
            minlength=len(self.i_mbon),
        ).astype(np.float32)
        total = pam_w + ppl_w
        # +1 reward compartment, -1 punishment compartment, 0 if neither.
        self.mbon_valence = np.where(
            total > 0, (pam_w - ppl_w) / np.maximum(total, 1e-6), 0.0
        ).astype(np.float32)

        # Which DAN drives which MBON's compartment -- used as the teaching
        # signal gate for the plasticity rule.
        self.dan_to_mbon = np.zeros((len(self.i_mbon),), dtype=np.float32)
        self.i_pam = _typed(d, "PAM")
        self.i_ppl = _typed(d, "PPL1")

        # Map each plastic edge to its postsynaptic MBON slot.
        self.kc_mbon_mbon_slot = slot[d.post[self.kc_mbon_edges]].astype(np.int32)
        self.kc_mbon_pre = d.pre[self.kc_mbon_edges]

        # Which projection-neuron channels feed which Kenyon cells. Used only
        # to answer "which inputs is the surprise coming through", which is not
        # something the fly knows -- it is something we can work out afterwards
        # by following its own wiring backwards.
        is_pn = np.zeros(d.n, dtype=bool)
        is_pn[self.i_pn] = True
        is_kc_post = np.zeros(d.n, dtype=bool)
        is_kc_post[self.i_kc] = True
        self.pn_kc_edges = np.where(is_pn[d.pre] & is_kc_post[d.post])[0].astype(np.int32)
        pn_slot = np.full(d.n, -1, dtype=np.int32)
        pn_slot[self.i_pn] = np.arange(len(self.i_pn), dtype=np.int32)
        self.pn_kc_pn = pn_slot[d.pre[self.pn_kc_edges]]
        self.pn_kc_kc = self.kc_slot[d.post[self.pn_kc_edges]]
        self.pn_kc_w = np.abs(d.weight[self.pn_kc_edges]).astype(np.float32)
        self.kc_novelty_slot = self.kc_slot[self.kc_mbon_pre]

    # --------------------------------------------------------------- input
    def _sensory_drive(self, senses: "Senses") -> np.ndarray:
        """Turn the state of the house into current injected into real neurons."""
        d = self.data
        inj = np.zeros(d.n, dtype=np.float32)

        # --- Ring neurons: visual landmark bearing --------------------------
        # ER neurons carry the azimuth of visual features into the ellipsoid
        # body and are what pins the heading bump to the outside world.
        #
        # The drive is made zero-mean before it is injected, and that is not a
        # detail -- without it the compass does not work at all. Ring neurons
        # are GABAergic, so *any* net activity across the population arrives at
        # EPG as uniform inhibition. Measured on this connectome that inhibition
        # is about -1.1 per EPG cell with only 7% spatial modulation on top, and
        # the EPG population sits just above threshold, so a single visible
        # landmark silenced the bump completely. It was found on a real house
        # with six lamps on, where the compass read one cell at 0.002 and every
        # other wedge at zero.
        #
        # Removing the component that carries net drive leaves the total
        # inhibitory tone into the ellipsoid body unchanged and passes only the
        # *pattern*, which is what a landmark should contribute: information
        # about direction, not a reason to stop having a heading.
        #
        # Subtracting the plain mean is not enough, and the difference is the
        # whole fix. Ring neurons do not contribute equally -- some have far
        # more outgoing weight onto EPG than others -- so a pattern that is
        # zero-mean across the ring population still delivers net inhibition to
        # the compass. Projecting out the direction that actually drives EPG
        # makes the net effect exactly zero by construction. With only the mean
        # removed, two or three visible landmarks still silenced the bump.
        if senses.landmarks:
            pattern = np.zeros(len(self.i_er), dtype=np.float32)
            for bearing, strength in senses.landmarks:
                tuning = np.maximum(np.cos(self.er_phase - bearing), 0.0) ** 2
                pattern += (strength * tuning).astype(np.float32)
            if pattern.size:
                overlap = float(pattern @ self.er_to_epg) / self.er_to_epg_norm
                pattern = pattern - overlap * self.er_to_epg
                inj[self.i_er] += RING_GAIN * pattern

        # --- PEN neurons: angular velocity ----------------------------------
        # Turning drives one hemisphere's PENs harder than the other, which is
        # how the bump moves. This is the integrator, and it is real.
        # A turn excites one hemisphere's PENs and not the other's; neither is
        # ever driven negative, because injecting a negative current merely
        # rectifies away to zero and the bump would then rotate the same way
        # for both turn directions, which is not a compass.
        #
        # The sign is fixed empirically, by simulation, not by inspection. The
        # static loop analysis (EPG -> left PEN -> EPG shifts +12.5 degrees,
        # the right loop -11.5) establishes that the two hemispheres push the
        # bump *opposite ways*, which is the part that matters; but a weighted
        # mean over EPG pairs does not reliably tell you which way round the
        # running network ends up, and taking it at face value produced a
        # compass that integrated beautifully and pointed exactly backwards.
        # tools/validate.py measures the actual correlation between commanded
        # angular velocity and observed bump rotation, and it is that number,
        # not this comment, that says the sign is right.
        av = float(np.clip(senses.angular_velocity, -2.0, 2.0))
        inj[self.i_pen] += (PEN_GAIN * np.maximum(av * self.pen_side, 0.0)).astype(np.float32)
        # The tonic stand-in goes to the tonically-driven circuits only. Giving
        # it to the phasic ones too parks them exactly at ACTIVATION_THRESHOLD,
        # since TONIC_DRIVE and that threshold are the same number, and a
        # pathway sitting precisely at its own firing threshold will fire for
        # any input at all. Measured before this line was qualified: a looming
        # input of 1e-5 produced escape 0.286 and an input of 1.25 produced
        # 0.284 -- the same burst, so theta-dot = v/r^2 was computed upstream
        # and then thrown away, and the fly startled at everything equally.
        #
        # DNp09 and its LPLC2 inputs are silent at rest in the animal, which is
        # what makes them a trigger rather than a readout, so withholding the
        # resting drive from exactly the circuits already marked phasic is the
        # assumption that matches them. Escape now needs looming >= ~0.1, about
        # 1.4 m for something closing at walking pace, and stays all-or-nothing
        # above that -- which is also how the giant-fibre pathway behaves.
        inj += np.float32(TONIC_DRIVE) * (1.0 - self.adapting)

        # --- Fan-shaped body and PFL3: the goal direction -------------------
        # A goal bump in the fan-shaped body columns is what the steering cells
        # compare the current heading against.
        goal_tuning = np.cos(self.fb_phase - senses.goal_bearing)
        inj[self.i_fb] += (FB_GOAL_GAIN * senses.goal_strength
                           * np.maximum(goal_tuning, 0.0)).astype(np.float32)

        # A note on what is deliberately *not* here.
        #
        # In the animal, PFL3 performs a vector comparison: its fan-shaped-body
        # arbor sits about a quarter turn from its protocerebral bridge arbor,
        # in opposite directions per hemisphere, so the left-right difference
        # across the population comes out as the sine of the goal-minus-heading
        # error -- a steering command (Hulse et al. 2021; Westeinde et al.
        # 2024). We tried to reproduce that here, both by feeding the goal into
        # the fan-shaped body and letting the connectome do the rest, and by
        # imposing the quarter-turn offset on PFL3 explicitly. Neither produced
        # reliable goal-following: the correlation between the turn command and
        # the sine of the heading error came out somewhere between +0.03 and
        # -0.54 depending on the trajectory, and the closed loop did not
        # converge on the goal.
        #
        # That offset is anatomy -- where the arbors physically sit in the
        # neuropil -- and synapse counts between cell types do not carry it.
        # Rather than tune a fudge factor until the demo looked right and call
        # it a connectome result, the goal-seeking controller lives in
        # coordinator.py where it is plainly labelled as a controller, and the
        # PFL3 left-right asymmetry is still read out as a real motor signal
        # and still contributes to steering.

        # --- Olfactory projection neurons: the smell of the house -----------
        if senses.odour is not None and len(self.i_pn):
            k = min(len(self.i_pn), len(senses.odour))
            inj[self.i_pn[:k]] += senses.odour[:k].astype(np.float32) * 0.9

        # --- what time it is, as part of the smell --------------------------
        # The last few channels carry the clock rather than the house. They are
        # driven by the morning and evening oscillators' own firing rates, so a
        # code learned in the evening does not match the same house at 3am.
        if len(self.i_clock_ctx):
            # A phase code: a bump that travels round the reserved channels once
            # a day, so 03:00 and 19:12 light different ones.
            #
            # Driving these from the modelled clock cells was tried first and
            # did not work. Their population-mean rates barely differ across the
            # day -- 0.407 in the evening against 0.330 at three in the morning
            # -- which is far too little to re-rank a competition that keeps the
            # top 5% of Kenyon cells. Measured, the code overlap between those
            # two times stayed at 100%: the same 39 cells, every hour.
            n = len(self.i_clock_ctx)
            phase = (senses.time_of_day % 1.0) * 2.0 * math.pi
            centres = np.arange(n, dtype=np.float32) * (2.0 * math.pi / n)
            bump = np.maximum(np.cos(phase - centres), 0.0) ** 2
            inj[self.i_clock_ctx] += (CLOCK_CONTEXT_GAIN * bump).astype(np.float32)

        # --- Looming: LPLC2 ------------------------------------------------
        # LPLC2 is the population that detects expanding dark edges and drives
        # escape. Feed it optic expansion, not a generic "motion" number.
        if senses.looming > 0.0 and len(self.i_loom):
            inj[self.i_loom] += np.float32(senses.looming * 1.4)

        # --- Dopaminergic teaching signals ---------------------------------
        if senses.reward > 0.0 and len(self.i_pam):
            inj[self.i_pam] += np.float32(senses.reward)
        if senses.punishment > 0.0 and len(self.i_ppl):
            inj[self.i_ppl] += np.float32(senses.punishment)

        # --- Circadian drive ------------------------------------------------
        # The morning and evening oscillators are genuinely separate cells.
        # Driving them with real local time makes the fly crepuscular in your
        # house without a single line of "if hour > 18" anywhere.
        t = senses.time_of_day  # 0..1

        # The morning and evening peaks sit where this house's dawn and dusk
        # actually are, rather than at a fixed 06:00 and 18:43.
        #
        # This is photoperiod tracking and not entrainment, and the difference
        # is worth being exact about: entrainment is a free-running oscillator
        # being pulled into phase by a zeitgeber, and there is no free-running
        # oscillator here. The clock in this model is a function of local time.
        # So the honest thing is to move where the peaks sit, which is a real
        # behaviour -- the morning and evening oscillators separate in long
        # days and close up in short ones (Rieger et al. 2003; Stoleru et al.
        # 2007) -- rather than to claim a mechanism that is not implemented.
        #
        # The phases are learned in the coordinator, from the light the house
        # actually reports, because estimating them is a house-level job and
        # not a neural computation. It is a stand-in, and labelled one.
        morning = _circadian_bump(t, senses.dawn_phase, 0.004)
        evening = _circadian_bump(t, senses.dusk_phase, 0.006)
        if len(self.i_clock_m):
            inj[self.i_clock_m] += np.float32(0.6 * morning + 0.15)
        if len(self.i_clock_e):
            inj[self.i_clock_e] += np.float32(0.6 * evening + 0.15)

        # Acute light onto l-LNv. These are the arousal-promoting clock cells
        # and they respond to light directly rather than through the clock
        # (Shang et al. 2008), which is why a light switched on at three in the
        # morning wakes a fly that the clock says should be asleep. Separate
        # from the photoperiod above: that shifts *when* it is active, this
        # makes it active *now*.
        if senses.light > 0.0 and len(self.i_llnv):
            inj[self.i_llnv] += np.float32(LIGHT_AROUSAL * senses.light)

        return inj

    # ---------------------------------------------------------------- step
    def step(self, senses: "Senses", sub_steps: int = 20) -> dict[str, Any]:
        """Integrate the network forward by sub_steps * DT seconds."""
        d = self.data
        inj = self._sensory_drive(senses)
        decay = (DT / self.tau).astype(np.float32)
        adapt_decay = np.float32(DT / TAU_ADAPT)

        w = d.weight.copy()
        # Both plasticities ride on the same measured synapses, in different
        # compartments: the valence memory everywhere, habituation only in
        # alpha'3. The mask is what keeps them from becoming the same thing.
        # Both plasticities ride on the same measured synapses, in different
        # compartments: the valence memory everywhere, habituation only in
        # alpha'3. The mask is what keeps them from becoming the same thing.
        hab = np.where(self.kc_novelty_mask,
                       self.kc_habituation[self.kc_novelty_slot], 1.0).astype(np.float32)
        w[self.kc_mbon_edges] = self.kc_mbon_base * self.kc_mbon_gain * hab

        for _ in range(sub_steps):
            # Recurrent drive: every measured synapse, every step.
            drive = np.bincount(
                d.post, weights=w * self.rate[d.pre], minlength=d.n
            ).astype(np.float32)
            total = RECURRENT_GAIN * drive + inj - ADAPT_GAIN * self.adapt

            # Global inhibition onto Kenyon cells via APL keeps the odour code
            # sparse. APL is in the connectome, but an explicit gain control
            # term is needed because we run a rate model, not spikes.
            if len(self.i_kc):
                kc = total[self.i_kc]
                if kc.size:
                    cut = np.quantile(kc, 1.0 - KC_SPARSENESS_TARGET)
                    total[self.i_kc] = kc - max(cut, 0.0)

            pos = _threshold(total)
            pos /= 1.0 + NORMALISATION_GAIN * float(pos.mean())
            pos /= self.circuit_gain
            self.rate += decay * (_saturate(pos) - self.rate)
            # Adaptation accumulates only in the phasic circuits.
            self.adapt += adapt_decay * (self.adapting * self.rate - self.adapt)

        self._last_seconds = sub_steps * DT
        self.time_s += self._last_seconds
        self.tick += 1
        self._learn(senses)
        self._habituate()
        return self._readout(senses)

    # ------------------------------------------------------------- learning
    def novel_channels(self, top: int = 4) -> list[tuple[int, float]]:
        """Which projection-neuron channels the current surprise arrives on.

        The Kenyon code is a hash and a hash does not invert, so this is not
        "the fly knows what changed" -- it does not, and never will. It is the
        measured PN->KC wiring read backwards: of the cells that are active and
        have *not* habituated, which input channels feed them hardest.

        Channels collide, because a random projection with more entities than
        glomeruli must. So this narrows the field rather than naming a culprit,
        which is exactly the right job for something whose next step is to hand
        the question to a system that can actually go and look.
        """
        if not len(self.pn_kc_edges) or not len(self.i_kc):
            return []
        act = self._kc_code()
        if act.sum() <= 1e-6:
            return []
        surprise = act * self.kc_habituation          # active AND still novel
        weight = surprise[self.pn_kc_kc] * self.pn_kc_w
        scores = np.bincount(self.pn_kc_pn, weights=weight, minlength=len(self.i_pn))
        total = float(scores.sum())
        if total <= 1e-9:
            return []
        order = np.argsort(scores)[::-1][:top]
        return [(int(i), round(float(scores[i] / total), 4))
                for i in order if scores[i] > 0]

    def _kc_code(self) -> np.ndarray:
        """The active Kenyon ensemble, as a weight per cell.

        Above the floor it is graded rather than binary, because a cell that is
        barely in the code should not habituate as fast as one driven hard.
        """
        return np.tanh(np.maximum(self.rate[self.i_kc] - KC_ACTIVE_FLOOR, 0.0) * 12.0)

    def _habituate(self) -> None:
        """Depress KC->alpha'3 synapses for whatever is active, regardless of
        whether anything good or bad happened.

        No dopamine gate, which is the whole difference between this and
        _learn: the valence memory needs a teacher and this does not. It is
        unsupervised, and it is why the fly can tell you something is unusual
        about a house nobody has ever labelled for it.
        """
        if not len(self.kc_mbon_edges):
            return
        act = self._kc_code()
        self.kc_habituation -= NOVELTY_DEPRESSION * act
        self.kc_habituation += NOVELTY_RECOVERY * (1.0 - self.kc_habituation)
        np.clip(self.kc_habituation, 0.02, 1.0, out=self.kc_habituation)

    def _learn(self, senses: "Senses") -> None:
        """Dopamine-gated depression of KC->MBON synapses.

        Only synapses whose Kenyon cell was active *and* whose MBON sits in a
        compartment whose dopaminergic neurons were firing get depressed. That
        conjunction is the entire memory: the fly does not store what happened,
        it stores which of its own synapses were on at the time.
        """
        if not len(self.kc_mbon_edges):
            return
        teaching = np.zeros(len(self.i_mbon), dtype=np.float32)
        if len(self.i_pam):
            teaching += np.float32(senses.reward) * np.clip(self.mbon_valence, 0, 1)
        if len(self.i_ppl):
            teaching += np.float32(senses.punishment) * np.clip(-self.mbon_valence, 0, 1)
        if not np.any(teaching > 1e-4):
            # Slow recovery towards baseline when nothing is being taught.
            self.kc_mbon_gain += 0.0005 * (1.0 - self.kc_mbon_gain)
            return

        kc_act = self.rate[self.kc_mbon_pre]
        gate = teaching[self.kc_mbon_mbon_slot]
        depression = 0.05 * gate * np.tanh(kc_act)
        self.kc_mbon_gain *= (1.0 - depression)
        np.clip(self.kc_mbon_gain, 0.05, 1.5, out=self.kc_mbon_gain)

    # -------------------------------------------------------------- readout
    def _readout(self, senses: "Senses") -> dict[str, Any]:
        r = self.rate

        # Heading: population vector across EPG neurons, weighted by the phase
        # their bridge glomerulus corresponds to. This is how the experimenters
        # read the bump out of imaging data, and it is how we read it here.
        epg = r[self.i_epg]
        total = float(epg.sum())
        if total > 1e-6:
            x = float((epg * self.epg_cos).sum() / total)
            y = float((epg * self.epg_sin).sum() / total)
            self.heading = math.atan2(y, x) % (2 * math.pi)
            bump_strength = math.hypot(x, y)
        else:
            bump_strength = 0.0

        # Steering: the left/right imbalance across PFL3, exactly the signal
        # that makes a real fly turn towards its goal.
        pfl3 = r[self.i_pfl3]
        if pfl3.size:
            left = float(pfl3[self.pfl3_side < 0].sum())
            right = float(pfl3[self.pfl3_side > 0].sum())
            denom = left + right
            self.turn = (right - left) / denom if denom > 1e-6 else 0.0
        else:
            self.turn = 0.0

        escape = float(r[self.i_escape].mean()) if len(self.i_escape) else 0.0
        self.escape_drive = escape

        mbon = r[self.i_mbon]
        self.valence = float((mbon * self.mbon_valence).sum() / max(mbon.sum(), 1e-6)) \
            if mbon.size else 0.0

        # Arousal is read off the two oscillator populations directly. There is
        # no rule anywhere that says "be active at dawn"; the morning cells are
        # driven by morning and the evening cells by evening, and this is just
        # their sum, scaled against the range the clock is actually observed to
        # cover.
        m_clock = float(r[self.i_clock_m].mean()) if len(self.i_clock_m) else 0.0
        e_clock = float(r[self.i_clock_e].mean()) if len(self.i_clock_e) else 0.0
        clock = m_clock + e_clock
        self.arousal = float(np.clip(
            (clock - AROUSAL_LO) / (AROUSAL_HI - AROUSAL_LO), 0.0, 1.0
        ))

        # Familiarity, read off the alpha'3 cells the way an experimenter
        # would: their firing rate *is* the novelty signal, high for something
        # new and low for something met many times. Reported against the
        # un-habituated drive the same Kenyon ensemble would have produced when
        # naive, so it is a proportion rather than a raw rate and does not
        # depend on how many cells happen to be active.
        if len(self.i_kc):
            act = self._kc_code()
            total = float(act.sum())
            # No active Kenyon cells is not the same as "completely familiar",
            # and reporting 0.0 for it said exactly the wrong thing. Nothing is
            # being smelled, so the last real answer stands.
            if total > 1e-6:
                self.novelty = float(np.clip(
                    float((act * self.kc_habituation).sum()) / total, 0.0, 1.0))
        kc = r[self.i_kc]
        kc_active = int((kc > 0.05).sum()) if kc.size else 0

        # Forward speed: arousal sets how much the fly wants to move, the
        # escape pathway overrides everything, and a strong turn slows it down
        # the way it does in a walking fly.
        base = self.arousal * (0.55 + 0.45 * senses.goal_strength)
        self.speed = float(np.clip(
            base * (1.0 - 0.6 * abs(self.turn)) + 2.5 * escape, 0.0, 3.0
        ))

        mode = (
            "escape" if escape > 0.15
            else "sleep" if self.arousal < SLEEP_BELOW
            else "forage" if self.hunger > 0.5
            else "walk" if self.speed > 0.25
            else "groom"
        )

        return {
            "heading": self.heading,
            "heading_deg": math.degrees(self.heading),
            "bump_strength": round(bump_strength, 4),
            "turn": round(self.turn, 4),
            "speed": round(self.speed, 4),
            "escape": round(escape, 4),
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "mode": mode,
            "tick": self.tick,
            "kc_active": kc_active,
            "kc_total": int(kc.size),
            "kc_sparseness": round(kc_active / max(kc.size, 1), 4),
            "mbon_activity": round(float(mbon.mean()) if mbon.size else 0.0, 4),
            "memory_depression": round(float(1.0 - self.kc_mbon_gain.mean()), 4),
            "novelty": round(float(self.novelty), 4),
            "familiarity": round(float(1.0 - self.novelty), 4),
            # How much of the Kenyon population has been habituated at all.
            # A fresh install has seen nothing, so everything is novel and
            # "unusual" would mean nothing -- this is what lets the coordinator
            # hold its tongue until the fly has some basis for an opinion.
            "settled": round(float(1.0 - self.kc_habituation.mean()), 4),
            "network_activity": round(float(r.mean()), 5),
            "active_neurons": int((r > 0.05).sum()),
        }

    # ------------------------------------------------------------- snapshot
    def activity_snapshot(self, indices: np.ndarray | None = None) -> list[int]:
        """Quantised activity for the frontend, 0-255 per neuron."""
        r = self.rate if indices is None else self.rate[indices]
        return np.clip(r * 90.0, 0, 255).astype(np.uint8).tolist()

    def compass_profile(self) -> list[float]:
        """EPG activity ordered by heading angle -- the bump, as drawn."""
        order = np.argsort(self.epg_phase)
        return [round(float(v), 4) for v in self.rate[self.i_epg][order]]


@dataclass
class Senses:
    """Everything the house tells the fly on a given tick."""

    landmarks: list[tuple[float, float]] = field(default_factory=list)
    angular_velocity: float = 0.0
    goal_bearing: float = 0.0
    goal_strength: float = 0.0
    odour: np.ndarray | None = None
    looming: float = 0.0
    reward: float = 0.0
    punishment: float = 0.0
    time_of_day: float = 0.5
    # Ambient light, 0..1. Drives l-LNv acutely -- those are the arousal cells
    # and they are genuinely light-responsive, which is why a fly wakes up when
    # you turn the kitchen light on at two in the morning.
    light: float = 0.0
    # Where the house's dawn and dusk actually are, as fractions of the day.
    # Defaults are 06:00 and 18:43, which is nobody's actual daylight.
    dawn_phase: float = 0.25
    dusk_phase: float = 0.78
