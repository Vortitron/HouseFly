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

# How hard the goal bearing is written into the fan-shaped body columns. The
# columnar network is large and mostly excitatory, so this has to stay small or
# it floods and every PFL3 cell ends up at the same rate.
FB_GOAL_GAIN = 0.12


# Converts summed clock-neuron firing into an arousal level in 0..1. The
# oscillators only swing over about 0.458..0.508 in these units, so the readout
# is stretched onto the useful range rather than reporting a flat value all day.
# The swing is small because these are 27 cells inside a 4,724-neuron network;
# the shape of it is what matters.
# Measured across a simulated 24 hours: the morning cells peak at 06:00 and the
# evening cells at 18:00, with nothing telling them to.
AROUSAL_GAIN = 17.33
AROUSAL_BASE = -7.86

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
            side=core["side"].astype(np.int8),
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
        self.i_loom = _typed(d, "LPLC2", "LC4", "LC6")
        self.i_dnp = _typed(d, "DNp")
        self.i_dna = _typed(d, "DNa")
        self.i_clock_m = _typed(d, "s-LNv", "5th s-LNv", "l-LNv")   # morning
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
        real time at six in the morning spends its first five minutes of life
        asleep, looking for all the world like a broken integration.
        """
        self.step(Senses(time_of_day=time_of_day), sub_steps=int(seconds / DT))
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

    # --------------------------------------------------------------- input
    def _sensory_drive(self, senses: "Senses") -> np.ndarray:
        """Turn the state of the house into current injected into real neurons."""
        d = self.data
        inj = np.zeros(d.n, dtype=np.float32)

        # --- Ring neurons: visual landmark bearing --------------------------
        # ER neurons carry the azimuth of visual features into the ellipsoid
        # body and are what pins the heading bump to the outside world.
        if senses.landmarks:
            for bearing, strength in senses.landmarks:
                tuning = np.cos(self.er_phase - bearing)
                inj[self.i_er] += (strength * np.maximum(tuning, 0.0) ** 2).astype(np.float32)

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
        inj += np.float32(TONIC_DRIVE)  # stands in for the un-modelled brain

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
        morning = math.exp(-((t - 0.25) ** 2) / 0.004)
        evening = math.exp(-((t - 0.78) ** 2) / 0.006)
        if len(self.i_clock_m):
            inj[self.i_clock_m] += np.float32(0.6 * morning + 0.15)
        if len(self.i_clock_e):
            inj[self.i_clock_e] += np.float32(0.6 * evening + 0.15)

        return inj

    # ---------------------------------------------------------------- step
    def step(self, senses: "Senses", sub_steps: int = 20) -> dict[str, Any]:
        """Integrate the network forward by sub_steps * DT seconds."""
        d = self.data
        inj = self._sensory_drive(senses)
        decay = (DT / self.tau).astype(np.float32)
        adapt_decay = np.float32(DT / TAU_ADAPT)

        w = d.weight.copy()
        w[self.kc_mbon_edges] = self.kc_mbon_base * self.kc_mbon_gain

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

        self.time_s += sub_steps * DT
        self.tick += 1
        self._learn(senses)
        return self._readout(senses)

    # ------------------------------------------------------------- learning
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
        # their sum.
        m_clock = float(r[self.i_clock_m].mean()) if len(self.i_clock_m) else 0.0
        e_clock = float(r[self.i_clock_e].mean()) if len(self.i_clock_e) else 0.0
        self.arousal = float(np.clip(
            AROUSAL_BASE + AROUSAL_GAIN * (m_clock + e_clock), 0.0, 1.0
        ))

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
            else "sleep" if self.arousal < 0.30
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
