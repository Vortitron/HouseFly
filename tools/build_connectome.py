#!/usr/bin/env python3
"""Build HouseFly's connectome data pack from public sources.

Sources (both CC-BY 4.0, both fetched at build time -- nothing here is
redistributed without attribution, see connectome/meta.json):

  1. Janelia hemibrain v1.2 "exported traced adjacencies"
     https://storage.googleapis.com/hemibrain/v1.2/exported-traced-adjacencies-v1.2.tar.gz
     Scheffer et al. 2020, eLife 9:e57443.
     -> cell types, instances (columnar labels), and real synapse counts.

  2. FlyWire (FAFB) whole-brain annotations, Schlegel et al. 2024, Nature.
     https://github.com/flyconnectome/flywire_annotations
     -> neurotransmitter predictions and real soma coordinates.

The hemibrain gives us connectivity; FlyWire gives us chemistry and geometry.
Run:  python3 tools/build_connectome.py --out custom_components/fly_house/connectome
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
from collections import defaultdict

import numpy as np

HEMIBRAIN_URL = (
    "https://storage.googleapis.com/hemibrain/v1.2/"
    "exported-traced-adjacencies-v1.2.tar.gz"
)
FLYWIRE_URL = (
    "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/"
    "main/supplemental_files/Supplemental_file1_neuron_annotations.tsv"
)

# Hemibrain's own criterion for a reliable connection (Scheffer et al. 2020).
WEIGHT_THRESHOLD = 5

# Circuit groups. Each regex is matched with fullmatch against hemibrain type.
# Grouping is what the simulator uses to know where to inject sensory drive
# and where to read motor commands from.
CIRCUITS: dict[str, list[str]] = {
    # --- Central complex: heading, steering, goal ---------------------------
    "compass": [r"EPG", r"EPGt", r"PEG", r"PEN_a\(PEN1\)", r"PEN_b\(PEN2\)", r"Delta7"],
    "ring": [r"ER\d.*", r"ExR\d"],
    "steer": [
        r"PFL1", r"PFL2", r"PFL3",
        r"PFN[a-z_]*",
        r"hDelta[A-M]", r"vDelta[A-M]",
        r"FC\d[A-F]?", r"FS\d[A-C]?",
    ],
    # --- Mushroom body: associative learning -------------------------------
    "mb_kc": [r"KC.*"],
    "mb_out": [r"MBON\d+"],
    "mb_dan": [r"PAM\d+.*", r"PPL1\d*"],
    "mb_inh": [r"APL"],
    # --- Olfactory input ----------------------------------------------------
    "olfactory": [r".*_(ad|l|v|il)PN"],
    # --- Looming / escape ---------------------------------------------------
    "loom": [r"LPLC2", r"LPLC1", r"LC4", r"LC6"],
    "descending": [r"DNp0[1-9]", r"DNp1[0-1]", r"DNa0[12]"],
    # --- Circadian clock ----------------------------------------------------
    "clock": [r"s-LNv", r"5th s-LNv", r"l-LNv", r"LNd", r"DN1a", r"DN1pA", r"DN1pB", r"LPN"],
}

# Neurotransmitter -> synaptic sign. Glutamate is predominantly inhibitory in
# Drosophila (GluCl-alpha), unlike vertebrate cortex -- this matters.
NT_SIGN = {
    "acetylcholine": 1.0,
    "glutamate": -1.0,    # GluCl-alpha makes glutamate inhibitory in the fly
    "gaba": -1.0,
    "histamine": -1.0,    # photoreceptor transmitter, inhibitory via HisCl1
    "dopamine": 0.0,      # modulatory, handled separately by the learning rule
    "serotonin": 0.0,
    "octopamine": 0.0,
}
FAST_NT = ("acetylcholine", "glutamate", "gaba", "histamine")


def parse_nt(raw: str) -> str:
    """Pull one fast transmitter out of FlyWire's free-text known_nt field.

    That column is not a controlled vocabulary -- it holds co-transmitters,
    duplications and explicit negatives, e.g.
        "acetylcholine; snpf; acetylcholine, snpf"
        "acetylcholine-negative, glutamate-negative, gaba-negative"
    Taking it literally silently assigns a synaptic sign of zero to cells whose
    label happens to be messy, which mutes them entirely. Parse it properly:
    split, discard negatives and neuropeptides, keep the first fast transmitter.
    """
    for part in re.split(r"[;,]", (raw or "").lower()):
        tok = part.strip()
        if not tok or tok.endswith("-negative"):
            continue
        if tok in FAST_NT:
            return tok
    return ""
# Types whose transmitter is established in the literature, used when the
# FlyWire join is ambiguous or missing.
# FlyWire's transmitter predictions are per-neuron classifier output and are
# unreliable for some central-complex families -- it returns acetylcholine for
# most ring neurons, which is simply wrong. Where the literature is settled,
# the literature wins.
NT_KNOWN = {
    "Delta7": "glutamate",   # Hulse et al. 2021, eLife 10:e66039
    "APL": "gaba",           # the mushroom body's single global inhibitory cell
}
# Ring neurons (ER*) are GABAergic and supply the inhibitory visual input to
# the ellipsoid body (Omoto et al. 2018; Hulse et al. 2021). Getting this wrong
# inverts the sign of every landmark the fly sees.
NT_KNOWN_PREFIX = {
    "ER": "gaba",
}


def _cache(url: str, path: str) -> str:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    print(f"  fetching {url}", file=sys.stderr)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    urllib.request.urlretrieve(url, path)
    return path


def circuit_of(cell_type: str) -> str | None:
    for group, pats in CIRCUITS.items():
        if any(re.fullmatch(p, cell_type) for p in pats):
            return group
    return None


_GLOM_RE = re.compile(r"_([LR])(\d)")
# A bare hemisphere suffix, as on DNp09_R or LC6(PLBDL7)_R. The glomerulus
# pattern above needs a digit after the letter, so on its own it recognised the
# hemisphere of the protocerebral-bridge cells and of nothing else -- 3,373
# neurons carried a side in their name and had it thrown away, including the
# whole looming and descending pathway. The negative lookahead keeps it from
# matching the L of a type name like _Lo or _La.
_SIDE_RE = re.compile(r"_([LR])(?![a-zA-Z])")
_COL_RE = re.compile(r"_C(\d)")


def parse_topography(instance: str) -> tuple[str, int, int]:
    """Pull (side, protocerebral-bridge glomerulus, fan-shaped-body column).

    The hemibrain instance names carry the anatomy, e.g.
        EPG(PB08)_L4            -> left PB glomerulus 4
        PFL3(PB12c)_R2_C7       -> right PB glomerulus 2, FB column 7
    Returns -1 for anything not labelled.
    """
    m = _GLOM_RE.search(instance)
    side, glom = ("?", -1)
    if m:
        side, glom = m.group(1), int(m.group(2))
    else:
        bare = _SIDE_RE.search(instance)
        if bare:
            side = bare.group(1)
    c = _COL_RE.search(instance)
    col = int(c.group(1)) if c else -1
    return side, glom, col


def phase_of(side: str, glom: int) -> float:
    """Map a protocerebral bridge glomerulus onto a heading angle in radians.

    Each hemisphere carries a full copy of the heading map across 8 glomeruli,
    so the glomerulus index steps in 45 degree increments. Crucially the two
    copies are *mirror images* of each other (Wolff & Rubin 2015; Green et al.
    2017): moving outward along the left bridge sweeps heading one way and
    along the right bridge the other way.

    That mirror symmetry is not cosmetic. It is the entire reason the bump can
    be shifted in a chosen direction: PEN cells project from one bridge
    hemisphere to the ellipsoid body with an angular offset, so exciting the
    left hemisphere's PENs rotates the bump clockwise and the right
    hemisphere's rotates it anticlockwise. Give both hemispheres the same
    angular order and the compass will hold a heading perfectly well but will
    only ever turn one way, which is not a compass.
    """
    if glom < 1:
        return float("nan")
    angle = 2.0 * np.pi * ((glom - 1) % 8) / 8.0
    return angle if side == "R" else (-angle) % (2.0 * np.pi)


def load_flywire_nt_and_pos(tsv_path: str):
    """hemibrain type -> (transmitter, [soma coordinates])."""
    nt_votes: dict[str, defaultdict] = defaultdict(lambda: defaultdict(int))
    positions: dict[str, list] = defaultdict(list)
    with open(tsv_path, newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            hb = (row.get("hemibrain_type") or "").strip()
            if not hb:
                continue
            nt = parse_nt(row.get("known_nt", "")) or parse_nt(row.get("top_nt", ""))
            if nt:
                nt_votes[hb][nt] += 1
            try:
                x = float(row["soma_x"] or row["pos_x"])
                y = float(row["soma_y"] or row["pos_y"])
                z = float(row["soma_z"] or row["pos_z"])
            except (ValueError, KeyError, TypeError):
                continue
            positions[hb].append((x, y, z))
    nt = {k: max(v.items(), key=lambda kv: kv[1])[0] for k, v in nt_votes.items()}
    return nt, positions


def build(out_dir: str, cache_dir: str, validate: bool) -> None:
    os.makedirs(out_dir, exist_ok=True)
    hb_tar = _cache(HEMIBRAIN_URL, os.path.join(cache_dir, "hemibrain.tar.gz"))
    fw_tsv = _cache(FLYWIRE_URL, os.path.join(cache_dir, "flywire_annotations.tsv"))

    print("  reading hemibrain neurons + connections", file=sys.stderr)
    neurons: dict[int, tuple[str, str]] = {}
    conn_bytes: bytes
    with tarfile.open(hb_tar) as tf:
        for member in tf.getmembers():
            if member.name.endswith("traced-neurons.csv"):
                data = tf.extractfile(member).read().decode()
                for row in csv.DictReader(io.StringIO(data)):
                    neurons[int(row["bodyId"])] = (row["type"] or "", row["instance"] or "")
            elif member.name.endswith("traced-total-connections.csv"):
                conn_bytes = tf.extractfile(member).read()

    # --- select the modelled subnetwork ------------------------------------
    selected: dict[int, str] = {}
    for body_id, (ctype, _inst) in neurons.items():
        group = circuit_of(ctype) if ctype else None
        if group:
            selected[body_id] = group

    body_ids = sorted(selected)
    index = {b: i for i, b in enumerate(body_ids)}
    n = len(body_ids)
    print(f"  selected {n} neurons across {len(CIRCUITS)} circuits", file=sys.stderr)

    # --- edges within the subnetwork ---------------------------------------
    pre_l: list[int] = []
    post_l: list[int] = []
    w_l: list[int] = []
    reader = csv.reader(io.StringIO(conn_bytes.decode()))
    next(reader, None)
    for a_s, b_s, w_s in reader:
        w = int(w_s)
        if w < WEIGHT_THRESHOLD:
            continue
        a, b = int(a_s), int(b_s)
        ia, ib = index.get(a), index.get(b)
        if ia is not None and ib is not None:
            pre_l.append(ia)
            post_l.append(ib)
            w_l.append(w)
    print(f"  kept {len(w_l)} connections at weight >= {WEIGHT_THRESHOLD}", file=sys.stderr)

    # --- chemistry and geometry from FlyWire -------------------------------
    print("  joining FlyWire transmitters + soma coordinates", file=sys.stderr)
    fw_nt, fw_pos = load_flywire_nt_and_pos(fw_tsv)

    types = [neurons[b][0] for b in body_ids]
    instances = [neurons[b][1] for b in body_ids]
    groups = [selected[b] for b in body_ids]

    nt_list: list[str] = []
    sign = np.zeros(n, dtype=np.float32)
    for i, t in enumerate(types):
        nt = NT_KNOWN.get(t) or ""
        if not nt:
            for pfx, known in NT_KNOWN_PREFIX.items():
                if t.startswith(pfx):
                    nt = known
                    break
        nt = nt or fw_nt.get(t) or ""
        if not nt:
            # No FlyWire match at all. The overwhelming majority of central
            # brain neurons are cholinergic, so that is the right prior -- but
            # never leave a cell at sign 0, which would mute it completely.
            nt = "acetylcholine"
        nt_list.append(nt)
        sign[i] = NT_SIGN.get(nt, 1.0)
    # Dopaminergic and aminergic cells keep a fast sign of 0: they modulate the
    # learning rule rather than driving the rate equation directly.

    # Positions: give each hemibrain neuron a distinct real FlyWire soma of the
    # same type where one exists, else the type centroid, else NaN.
    used: defaultdict = defaultdict(int)
    pos = np.full((n, 3), np.nan, dtype=np.float32)
    for i, t in enumerate(types):
        cands = fw_pos.get(t)
        if not cands:
            continue
        k = used[t] % len(cands)
        used[t] += 1
        pos[i] = cands[k]

    # --- topography ---------------------------------------------------------
    side_arr = np.zeros(n, dtype=np.int8)      # -1 left, +1 right, 0 unknown
    glom_arr = np.full(n, -1, dtype=np.int8)
    col_arr = np.full(n, -1, dtype=np.int8)
    phase_arr = np.full(n, np.nan, dtype=np.float32)
    for i, inst in enumerate(instances):
        side, glom, col = parse_topography(inst)
        side_arr[i] = -1 if side == "L" else (1 if side == "R" else 0)
        glom_arr[i] = glom
        col_arr[i] = col
        phase_arr[i] = phase_of(side, glom)

    np.savez_compressed(
        os.path.join(out_dir, "core.npz"),
        pre=np.asarray(pre_l, dtype=np.int32),
        post=np.asarray(post_l, dtype=np.int32),
        weight=np.asarray(w_l, dtype=np.float32),
        sign=sign,
        phase=phase_arr,
        side=side_arr,
        glomerulus=glom_arr,
        column=col_arr,
        pos=pos,
    )

    meta = {
        "n_neurons": n,
        "n_connections": len(w_l),
        "weight_threshold": WEIGHT_THRESHOLD,
        "types": types,
        "instances": instances,
        "groups": groups,
        "transmitters": nt_list,
        "group_index": {
            g: [i for i, gg in enumerate(groups) if gg == g] for g in CIRCUITS
        },
        "sources": [
            {
                "name": "Janelia hemibrain v1.2 traced adjacencies",
                "url": HEMIBRAIN_URL,
                "citation": "Scheffer et al. 2020, eLife 9:e57443",
                "licence": "CC-BY 4.0",
                "used_for": "cell types, columnar instance labels, synapse counts",
            },
            {
                "name": "FlyWire FAFB whole-brain annotations",
                "url": FLYWIRE_URL,
                "citation": "Schlegel et al. 2024, Nature 634:139-152",
                "licence": "CC-BY 4.0",
                "used_for": "neurotransmitter predictions, soma coordinates",
            },
        ],
    }
    with gzip.open(os.path.join(out_dir, "meta.json.gz"), "wt") as fh:
        json.dump(meta, fh)

    size = os.path.getsize(os.path.join(out_dir, "core.npz")) / 1e6
    msize = os.path.getsize(os.path.join(out_dir, "meta.json.gz")) / 1e6
    print(f"  wrote core.npz ({size:.2f} MB) + meta.json.gz ({msize:.2f} MB)", file=sys.stderr)

    if validate:
        _validate_ring(np.asarray(pre_l), np.asarray(post_l), np.asarray(w_l, dtype=float),
                       types, phase_arr, n)


def _validate_ring(pre, post, w, types, phase, n) -> None:
    """The bump is only a bump if Delta7 inhibition is sinusoidal in phase.

    Prints the effective EPG -> Delta7 -> EPG coupling binned by heading
    offset. A ring attractor requires this to peak near 180 degrees.
    """
    W = np.zeros((n, n))
    W[pre, post] = w
    t = np.asarray(types)
    epg = np.where(t == "EPG")[0]
    d7 = np.where(t == "Delta7")[0]
    eff = W[np.ix_(epg, d7)] @ W[np.ix_(d7, epg)]
    pe = phase[epg]
    bins = defaultdict(list)
    for a in range(len(epg)):
        for b in range(len(epg)):
            if a == b or np.isnan(pe[a]) or np.isnan(pe[b]):
                continue
            d = (pe[b] - pe[a]) % (2 * np.pi)
            bins[int(round(d / (2 * np.pi / 8))) % 8].append(eff[a, b])
    vals = [float(np.mean(bins[k])) if bins[k] else 0.0 for k in range(8)]
    peak = int(np.argmax(vals))
    print("\n  ring-attractor validation "
          "(effective EPG->Delta7->EPG, Delta7 inhibitory):", file=sys.stderr)
    top = max(vals) or 1.0
    for k, v in enumerate(vals):
        print(f"    {k * 45:3d} deg  {v:10.0f}  {'#' * int(38 * v / top)}", file=sys.stderr)
    verdict = "PASS" if peak in (3, 4, 5) else "FAIL"
    print(f"  peak inhibition at {peak * 45} deg -> {verdict} "
          f"(expected 135-225 deg)\n", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="custom_components/fly_house/connectome")
    ap.add_argument("--cache", default=".connectome-cache")
    ap.add_argument("--validate", action="store_true", default=True)
    args = ap.parse_args()
    build(args.out, args.cache, args.validate)
