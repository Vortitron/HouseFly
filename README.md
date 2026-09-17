# HouseFly 🪰

> **Let a fruit fly control your house.**

A weekend Home Assistant / [HACS](https://hacs.xyz) custom integration that maps a handful of sensors into a tiny **leaky reservoir** (~256 dims, pure Python) and writes the "motor" channels out to lights, covers, switches, and numbers.

**New in v0.1:** 🎨 Complete visual overhaul with animated fly + brain assets, ASCII art sensors, and picture-perfect Lovelace cards — all the meme-y DNA from chessfly/flyputer demos, zero GPU required!

Soft CTA: when you're away and want to *watch* the chaos (or just check the house), peek at **[vome.io](https://vome.io)**. Optionally try **[fynd.vome.io](https://fynd.vome.io)** for finding stuff around the home.

---

## 🎨 Visual Demo

- 🪰 **Animated buzzing fly** SVG (flapping wings, CSS animations)
- 🧠 **Sparking brain connectome** SVG (glowing nodes, pulse effects)
- 📊 **Live ASCII art** brain sensor (💤 idle → ✨ wander → ⚡💥 escape)
- 📋 **6+ Lovelace examples** ready to copy (see `LOVELACE_EXAMPLE.yaml` + `VISUAL_SETUP_GUIDE.md`)

All assets ship with the integration — no downloads, no external dependencies!

---

## Honest science disclaimer

This is a **meme / toy**, not a scientific instrument.

- Inspired by the spirit of **MaleCNS**, [ngxson/fly-llm-hf](https://huggingface.co/ngxson/fly-llm-hf) ("chessfly" / flyputer-style demos), and the idea of a fruit-fly connectome as an echo-state reservoir.
- **Not** a real fly brain running your house.
- **Does not** download or load [QuixiAI/MaleCNS](https://huggingface.co/QuixiAI/MaleCNS) weights, torch, or multi‑GB connectome tensors.
- v1 uses a **seeded sparse-ish random matrix** with leaky-tanh dynamics. Any resemblance to Drosophila is comedic.

**Inspiration citation:** QuixiAI/MaleCNS packaging of the MaleCNS connectome is licensed **CC-BY 4.0**. We cite it for inspiration only; this integration does not redistribute those weights.

If you wire this to real actuators, use common sense: start with a spare lamp, not the garage door whilst you're out.

---

## Features (v1)

| Piece | What it does |
|-------|----------------|
| Config flow | Pick 1–32 input entities (what the fly can SEE), 1–32 outputs (what it can CONTROL), tick interval (default 10s), intensity 0–1, seed |
| Brain | Pure Python leaky reservoir (~256), sensory hash → update → motor channels |
| Entities | `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`), `sensor.fly_house_brain` (ASCII art + spark visualisation) |
| Service | `fly_house.poke` — inject a jolt (strength 0.1–5.0) |
| Visual assets | Animated SVG fly + brain connectome sparks for Lovelace dashboards |
| Whole house mode | ⚠️ **DANGER ZONE** — let the fly control many devices at once (NOT recommended for first-time users!) |

Supported **outputs**: `light` (brightness %), `cover` (position), `switch` (threshold), `number` / `input_number`, `fan` (percentage).

---

## Install (HACS)

**Quick start:** See [`QUICK_START.md`](QUICK_START.md) for step-by-step instructions with safety tips.

**Summary:**
1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/Vortitron/HouseFly` as category **Integration**
3. Install **HouseFly**, restart Home Assistant
4. Settings → Devices & services → **Add integration** → **HouseFly**
5. Pick inputs (1-32 sensors) / outputs (1-32 entities) / tick / intensity / seed
6. ⚠️ **Start with ONE spare lamp** — do NOT enable whole house mode on first run!

### Manual install

Copy `custom_components/fly_house/` into your HA `config/custom_components/` folder, restart, then add the integration.

```text
config/
  custom_components/
    fly_house/
      manifest.json
      __init__.py
      ...
```

---

## Lovelace visual examples

HouseFly ships with **animated SVG assets** — see the fly buzz and the brain spark! 🪰⚡🧠

### Quick start card

```yaml
type: vertical-stack
title: 🪰 HouseFly Control
cards:
  - type: picture
    image: /local/community/fly_house/fly-animated.svg
    tap_action:
      action: call-service
      service: fly_house.poke
  - type: entities
    entities:
      - entity: binary_sensor.fly_house_active
      - entity: sensor.fly_house_mode
      - entity: sensor.fly_house_spikes
      - entity: sensor.fly_house_brain
  - type: button
    name: 💥 POKE THE FLY
    icon: mdi:hand-pointing-right
    tap_action:
      action: call-service
      service: fly_house.poke
```

### Brain ASCII art card

```yaml
type: markdown
content: |
  ## 🧠 Fly Brain Activity
  **Mode:** {{ states('sensor.fly_house_mode') | upper }}
  **Spikes:** {{ states('sensor.fly_house_spikes') }}
  
  ```
  {{ state_attr('sensor.fly_house_brain', 'ascii_brain') }}
  ```
  {{ states('sensor.fly_house_brain') }}
```

**Full examples** (including animated fly position, brain sparks, picture-elements) → see [`LOVELACE_EXAMPLE.yaml`](LOVELACE_EXAMPLE.yaml)

**Assets automatically available:**
- `/local/community/fly_house/fly-animated.svg` — buzzing fly with flapping wings
- `/local/community/fly_house/brain-sparks.svg` — animated connectome with glowing nodes

(Restart Home Assistant after first install if images don't load.)

---

## Service

```yaml
service: fly_house.poke
data:
  strength: 1.0   # 0.1 – 5.0 (gentle tap to hard jolt)
```

**Pro tip:** Poke during `escape` mode for maximum chaos. 🔥

---

## ⚠️ Whole House Mode

**DO NOT enable this unless you know what you're doing.**

Whole house mode is an optional config toggle that lets you give the fly control over 20+ devices simultaneously. This can result in:
- All your lights flickering like a rave
- Covers opening/closing randomly
- Fans cycling on and off
- General household pandemonium

**Recommended approach:**
1. Start with **ONE spare lamp** in a corner
2. Watch it for a day
3. Add 1-2 more devices if you're brave
4. Only enable whole house mode if you're absolutely certain (or filming content)

When whole house mode is enabled, the integration will show extra warnings in the config flow. You've been warned. 💀

---

## How the brain works (short)

1. Each tick, input entity states are hashed into an 8-D sensory vector.
2. A seeded sparse recurrent matrix updates a 256-D leaky-tanh state.
3. Readout channels in `[0,1]` map to brightness / cover position / switch on-off / number.
4. Mode heuristically classifies energy + spikes as `idle`, `wander`, or `escape`.

No numpy, no torch, no model download. Requirements list in `manifest.json` is empty on purpose.

---

## v2 (optional add-on path — not shipped here)

Local `assets/` may contain MaleCNS-related metadata or larger weights for **experiments**. Those are **not** bundled into this HACS integration (multi‑GB, torch, etc.). A future add-on could swap the toy matrix for a connectome-derived reservoir; see `MVP.md`. Until then, enjoy the fruit fly cosplay.

---

## Licence

- **Code:** MIT (see `LICENSE`)
- **Inspiration / MaleCNS data (not included):** QuixiAI/MaleCNS — CC-BY 4.0

---

## Links

- 🪰 **Visual setup guide:** [`VISUAL_SETUP_GUIDE.md`](VISUAL_SETUP_GUIDE.md)
- 📋 **Lovelace examples:** [`LOVELACE_EXAMPLE.yaml`](LOVELACE_EXAMPLE.yaml)
- 📢 **Forum post draft:** [`FORUM_POST.md`](FORUM_POST.md)
- 🏠 Watch remotely when away: [vome.io](https://vome.io)
- 🔍 Optional: [fynd.vome.io](https://fynd.vome.io)
- 🧬 MaleCNS packaging: [huggingface.co/QuixiAI/MaleCNS](https://huggingface.co/QuixiAI/MaleCNS)
