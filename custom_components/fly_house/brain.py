"""Pure-Python leaky reservoir 'brain' for Fly House.

Inspired by echo-state / fly-llm-style reservoirs and the MaleCNS connectome
packaging (QuixiAI/MaleCNS, CC-BY 4.0) — this is a tiny seeded toy matrix,
NOT a real fly brain and does not load MaleCNS or torch weights.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .const import (
    DEFAULT_RESERVOIR_SIZE,
    MODE_ESCAPE,
    MODE_IDLE,
    MODE_WANDER,
)


def _tanh(x: float) -> float:
    # Bound for numerical calm without math.tanh overflow worries
    if x > 20.0:
        return 1.0
    if x < -20.0:
        return -1.0
    return math.tanh(x)


def _hash_state(value: Any) -> float:
    """Map an HA state string/number into roughly [-1, 1]."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        # Soft squash so bright lights / percentages don't explode
        return _tanh(float(value) / 50.0)
    text = str(value).strip().lower()
    if text in ("", "unknown", "unavailable", "none"):
        return 0.0
    if text in ("on", "true", "home", "open", "unlocked"):
        return 1.0
    if text in ("off", "false", "away", "not_home", "closed", "locked"):
        return -1.0
    # Stable hash for categorical strings
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    # Map uint32-ish into [-1, 1]
    return ((h / 0xFFFFFFFF) * 2.0) - 1.0


@dataclass
class FlyBrain:
    """Leaky tanh reservoir with sparse-ish recurrent weights."""

    size: int = DEFAULT_RESERVOIR_SIZE
    seed: int = 42
    leak: float = 0.15
    spectral_scale: float = 0.9
    sparsity: float = 0.08  # fraction of non-zero recurrent edges
    intensity: float = 0.55
    state: list[float] = field(default_factory=list)
    # CSR-ish sparse matrix: list of (row, col, weight)
    edges: list[tuple[int, int, float]] = field(default_factory=list)
    input_proj: list[list[float]] = field(default_factory=list)
    output_channels: int = 32
    readouts: list[list[float]] = field(default_factory=list)
    input_channels: int = 32
    pending_poke: float = 0.0
    tick_count: int = 0

    def __post_init__(self) -> None:
        self.reset(seed=self.seed)

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        rng = random.Random(self.seed)
        n = self.size
        self.state = [0.0] * n

        # Sparse recurrent matrix
        edges: list[tuple[int, int, float]] = []
        n_edges = max(n, int(n * n * self.sparsity))
        for _ in range(n_edges):
            i = rng.randrange(n)
            j = rng.randrange(n)
            w = rng.gauss(0.0, 1.0)
            edges.append((i, j, w))
        # Crude spectral radius proxy: scale by sqrt(mean degree)
        mean_degree = max(1.0, n_edges / n)
        scale = self.spectral_scale / math.sqrt(mean_degree)
        self.edges = [(i, j, w * scale) for i, j, w in edges]

        # Input projection: up to 32 senses → n
        self.input_proj = [
            [rng.gauss(0.0, 0.35) for _ in range(self.input_channels)] for _ in range(n)
        ]
        # Readouts: n → output_channels
        self.readouts = [
            [rng.gauss(0.0, 0.25) for _ in range(n)]
            for _ in range(self.output_channels)
        ]
        self.pending_poke = 0.0
        self.tick_count = 0

    def set_intensity(self, intensity: float) -> None:
        self.intensity = max(0.0, min(1.0, float(intensity)))

    def poke(self, strength: float = 1.0) -> None:
        self.pending_poke += max(0.0, float(strength))

    def sensory_vector(self, input_states: Sequence[Any]) -> list[float]:
        vec = [0.0] * self.input_channels
        for i, st in enumerate(list(input_states)[: self.input_channels]):
            vec[i] = _hash_state(st)
        if self.pending_poke > 0.0:
            # Spread poke across channels as a jolt
            jolt = min(5.0, self.pending_poke)
            for i in range(min(8, self.input_channels)):  # Poke first 8 channels
                vec[i] += jolt * (1.0 if i % 2 == 0 else -0.7)
            self.pending_poke = 0.0
        return vec

    def step(self, input_states: Sequence[Any]) -> dict[str, Any]:
        """One leaky reservoir tick. Returns diagnostics + motor channels."""
        u = self.sensory_vector(input_states)
        n = self.size
        drive = [0.0] * n

        # Win @ u
        for i in range(n):
            s = 0.0
            row = self.input_proj[i]
            for k in range(min(len(u), self.input_channels)):
                s += row[k] * u[k]
            drive[i] = s * (0.4 + 0.6 * self.intensity)

        # W @ x (sparse)
        for i, j, w in self.edges:
            drive[i] += w * self.state[j]

        a = self.leak
        new_state = [0.0] * n
        energy = 0.0
        spikes = 0
        for i in range(n):
            x = (1.0 - a) * self.state[i] + a * _tanh(drive[i])
            new_state[i] = x
            energy += x * x
            if abs(x) > 0.55:
                spikes += 1
        self.state = new_state
        self.tick_count += 1
        rms = math.sqrt(energy / n)

        # Readout channels in [0, 1]
        channels: list[float] = []
        for ch in range(self.output_channels):
            s = 0.0
            wrow = self.readouts[ch]
            for i in range(n):
                s += wrow[i] * self.state[i]
            # Map through sigmoid-ish into 0..1, intensity gated
            y = 1.0 / (1.0 + math.exp(-s * (0.8 + self.intensity)))
            channels.append(y)

        mode = self._classify_mode(rms, spikes, u)
        return {
            "spikes": spikes,
            "energy": round(rms, 4),
            "mode": mode,
            "channels": channels,
            "tick": self.tick_count,
            "sensory": u,
        }

    def _classify_mode(
        self, rms: float, spikes: int, sensory: Iterable[float]
    ) -> str:
        sense_list = list(sensory)
        n_sense = len(sense_list) if sense_list else 1
        sense_mag = math.sqrt(sum(v * v for v in sense_list) / max(1, n_sense))
        if spikes > self.size * 0.35 or rms > 0.55 or sense_mag > 0.85:
            return MODE_ESCAPE
        if spikes > self.size * 0.08 or rms > 0.18 or sense_mag > 0.25:
            return MODE_WANDER
        return MODE_IDLE


def map_channel_to_output(
    channel: float,
    domain: str,
    *,
    switch_threshold: float = 0.55,
) -> dict[str, Any] | None:
    """Translate a [0,1] channel into a service call payload hint.

    Returns dict with keys: service (domain.service), data (kwargs).
    """
    c = max(0.0, min(1.0, float(channel)))
    if domain == "light":
        return {
            "service": "light.turn_on",
            "data": {"brightness_pct": max(1, int(round(c * 100)))},
        }
    if domain == "cover":
        return {
            "service": "cover.set_cover_position",
            "data": {"position": int(round(c * 100))},
        }
    if domain == "switch":
        on = c >= switch_threshold
        return {
            "service": "switch.turn_on" if on else "switch.turn_off",
            "data": {},
        }
    if domain == "number":
        # Assume 0–100 range; HA number entities vary — caller may clamp
        return {
            "service": "number.set_value",
            "data": {"value": round(c * 100.0, 2)},
        }
    if domain == "input_number":
        return {
            "service": "input_number.set_value",
            "data": {"value": round(c * 100.0, 2)},
        }
    if domain == "fan":
        return {
            "service": "fan.set_percentage",
            "data": {"percentage": int(round(c * 100))},
        }
    return None
