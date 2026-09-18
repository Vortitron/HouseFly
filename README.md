# HouseFly 🪰

> **Let a fruit fly control your house.**

A Home Assistant / [HACS](https://hacs.xyz) custom integration exploring what happens when you map sensors into a tiny **leaky reservoir** (~256 dims, pure Python) and write the "motor" channels out to lights, covers, switches, and numbers.

**Current release (v1.0):** 👁️ Real camera → ommatidia (optional `camera.*` snapshot via Pillow), hunger phototaxis bias on light outputs, persistent fly state across restarts, richer lifecycle tracking. Soft remote peek via [vome.io](https://vome.io). Pure Python — zero GPU, zero torch.

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

This is a **toy dynamical system**, not a scientific instrument or AI agent.

- **Inspired by** fruit-fly sensorimotor motifs: compound eyes, hunger-driven foraging, escape responses
- **Architecture:** Leaky reservoir (256 neurons, seeded sparse matrix) + fruit-fly-inspired drives (phototaxis, hunger, motion detection)
- **NOT** an LLM chatbot, NOT MaleCNS running in Home Assistant, NOT downloading multi-GB neural network weights
- **Pure Python** — no torch, no numpy; optional **Pillow** for camera→ommatidia (falls back to lights+sun if missing)
- **Inspired by** the spirit of [QuixiAI/MaleCNS](https://huggingface.co/QuixiAI/MaleCNS) (CC-BY 4.0), [ngxson/fly-llm-hf](https://huggingface.co/ngxson/fly-llm-hf), and "chessfly" / flyputer demos
- Any resemblance to actual *Drosophila melanogaster* neuroscience is **comedic and superficial**

### What It Actually Is

A **toy dynamical system** with fruit-fly-inspired components:

1. **Compound eye** (ommatidia grid): Synthesises a 16×16 visual field from your lights + sun position, or can process camera snapshots
2. **Hunger drive**: Internal state that rises over time, affects foraging behaviour (more exploration when hungry)
3. **Reservoir brain**: 256-neuron leaky-tanh network processes sensory inputs → motor outputs
4. **Phototaxis**: Biases motor outputs towards brighter lights when hungry
5. **Motion detection**: Responds to changes in visual field (loom response)
6. **State persistence**: Fly remembers its hunger and lifecycle across Home Assistant restarts

This is **not neuroscience** — it's an exploratory project mapping dynamical systems concepts onto home automation as a playful experiment.

**Inspiration citation:** QuixiAI/MaleCNS packaging of the MaleCNS connectome is licenced **CC-BY 4.0**. We cite it for inspiration only; this integration does not redistribute those weights.

If you wire this to real actuators, use common sense: start with a spare lamp, not the garage door whilst you're out.

---

## Features (v1.0)

| Piece | What it does |
|-------|----------------|
| Config flow | Pick 1–32 input entities (what the fly can SEE), 1–32 outputs (what it can CONTROL), tick interval (default 10s), intensity 0–1, seed |
| **Compound eye** | 16×16 ommatidia from optional camera snapshot (Pillow luma downsample) or lights+sun synthesis; phototaxis + motion detection |
| **Hunger system** | Internal drive (0–100%) rises over time, reduces on `fly_house.feed`; hungry fly explores more + seeks brighter lights |
| **Persistence** | Hunger, mode, and lifecycle metadata (birth time, last poke/feed) survive Home Assistant restarts — fly feels continuous |
| Brain | Pure Python leaky reservoir (~256), sensory hash → visual pathway → hunger modulation → motor channels |
| Entities | `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`), `sensor.fly_house_brain`, `sensor.fly_house_hunger`, `sensor.fly_house_retina` (ommatidia hex grid) |
| Services | `fly_house.poke` (strength 0.1–5.0), `fly_house.feed` (amount 0.1–1.0, reduces hunger) |
| **Custom card** | `housefly-card` — animated fly + faceted compound eye + hunger bar + brain stats + Poke/Feed buttons |
| Visual assets | Animated SVG fly + brain connectome sparks for Lovelace dashboards |
| Whole house mode | ⚠️ **DANGER ZONE** — auto-selects up to 32 devices, requires confirmation (NOT recommended for first-time users!) |

Supported **outputs**: `light` (brightness %), `cover` (position), `switch` (threshold), `number` / `input_number`, `fan` (percentage).

### Fly Biology (Non-Superficial)

- **Compound eye**: 16×16 grid = 256 "ommatidia" (facets). Downsamples camera images or synthesises visual field from lights.
- **Phototaxis**: When hungry, biases motor outputs towards brighter regions of visual field.
- **Motion detection**: Compares current vs previous frame, triggers loom response (escape mode).
- **Hunger drive**: Rises at ~0.2% per tick (reaches 100% in ~8 hours). Feed via service or automation when `sensor.fly_house_hunger > 50`.
- **Foraging**: High hunger → more output variance (wander mode), seeks light sources.
- **Grooming/idle**: Low hunger → calmer reservoir state, less motor activity.
- **Lifecycle tracking**: Birth time, time alive, last poke/feed timestamps exposed as sensor attributes.

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
- `/local/community/fly_house/housefly-card.js` — custom Lovelace card (see below)

(Restart Home Assistant after first install if images don't load.)

---

## Custom Lovelace Card

HouseFly ships with a **custom card** that displays the full fly experience:

### Installation (Automatic) ✨

**As of v1.0.1, the card auto-registers!** No resource setup required.

1. Install HouseFly via HACS (or manually)
2. Restart Home Assistant
3. Add the card to your dashboard

The integration automatically serves the card from `/fly_house/housefly-card.js` and loads it as a frontend module.

### Manual Resource (Legacy / Optional)

For older HA versions or troubleshooting, you can manually add as a resource:

```yaml
resources:
  - url: /fly_house/housefly-card.js
    type: module
```

Or via UI: **Settings → Dashboards → Resources → Add Resource** → URL: `/fly_house/housefly-card.js`, Type: JavaScript Module

**Legacy paths:** If you copied the card to `/local/`, use `/local/community/fly_house/housefly-card.js` (HACS) or `/local/housefly/housefly-card.js` (manual) instead.

**Full guide:** See [`CUSTOM_CARD_GUIDE.md`](CUSTOM_CARD_GUIDE.md) for detailed installation, troubleshooting, and customisation

### Card Configuration

```yaml
type: custom:housefly-card
entity: binary_sensor.fly_house_active
```

### What the Card Shows

- **Animated fly** (buzzing, flapping wings, mode-reactive) — tap to poke
- **Compound eye** — 16×16 faceted ommatidia grid (updates in real-time from `sensor.fly_house_retina`)
- **Reservoir sparks** — animated brain canvas with glowing nodes and pulsing connections
- **Hunger bar** — gradient from green (satiated) → yellow → red (starving)
- **Brain stats** — spikes, energy, mode badge (idle/wander/escape)
- **Action buttons:**
  - 💥 **Poke** — calls `fly_house.poke` (strength 1.0)
  - 🍎 **Feed** — calls `fly_house.feed` (amount 0.3, reduces hunger by 30%)

The card is **pure vanilla JS** (no build step) and uses Home Assistant design tokens for theming.

**Pro tip:** Place the card next to your lights panel — watch the ommatidia light up as you turn lights on, then see the fly's hunger drive bias its motor outputs towards those bright regions!

**Away from home?** The card includes a soft call-to-action to [Vome](https://vome.io) for remote dashboard access (completely optional)

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

### What It Does

When you enable whole house mode, HouseFly will:

1. **Auto-scan** your Home Assistant for ALL available `light`, `switch`, `cover`, and `fan` entities
2. **Auto-select up to 32** of them (prioritising lights → switches → covers → fans)
3. **Require confirmation** with a scary warning dialogue showing exact device count
4. **Apply safety limits:**
   - Minimum tick interval: **15 seconds** (slower updates)
   - Maximum intensity: **0.4** (capped at 40% chaos)
5. **Give the fly control** over all selected devices simultaneously

This is a **static snapshot** at configuration time — newly added devices won't auto-appear (reconfigure to refresh).

### What This Means

The fruit fly will:
- Flicker all your lights like a rave 💡✨
- Toggle switches on/off randomly 🔌
- Open/close covers based on neural activity 🪟
- Cycle fans based on spike patterns 🌀
- Operate **all of this simultaneously** every 15+ seconds

### Recommended Approach

1. **Start with ONE spare lamp** (seriously!)
2. Watch it for a day ⏰
3. Add 1-2 more devices if brave 🎯
4. **ONLY enable whole house mode if:**
   - You've tested extensively with 3-5 devices
   - You're filming content for the chaos 🎥
   - You understand the pandemonium 💀
   - You're prepared to quickly disable it

### Confirmation Required

You **cannot** enable whole house mode without:
- Reading the scary warning dialogue
- Seeing the exact count of devices (e.g. "47 devices")
- Checking the box: _"I understand this can thrash lights/covers/switches and I'm ready for the chaos"_

If you're not 100% sure, **go back and leave it disabled**. 🚫

---

## How the brain works (technical)

### Architecture: Integration → Optional Card → Optional Add-on

HouseFly follows a **layered architecture**:

1. **HACS Integration** (this repo, `fly_house`): The brain (pure Python reservoir + drives)
2. **HACS Frontend Card** (bundled, `housefly-card`): Visual UI for compound eye + hunger + controls
3. **Optional Add-on** (future, not shipped): Heavy lifting (MaleCNS weights, camera processing, GPU acceleration)

**Current v1.0 = Integration + Card.** No add-on required. No torch. No GPU. Runs entirely in HA core.

### Brain Pipeline

1. **Sensory inputs** (entity states) → hashed into 32-channel vector
2. **Visual pathway** (ommatidia grid):
   - Synthesise 16×16 grid from lights + sun elevation
   - Or downsample camera snapshot (Pillow luma conversion + bilinear resize)
   - Compute motion (difference from previous frame)
   - Feed phototaxis + loom channels into first 16 reservoir neurons
3. **Hunger modulation**:
   - Internal hunger state rises at ~0.2% per tick
   - Hungry → inject variance into middle reservoir neurons (foraging drive)
   - Hungry + phototaxis → bias motor outputs towards bright lights
4. **Reservoir update**:
   - Seeded sparse recurrent matrix (256 neurons, leaky-tanh)
   - Win @ sensory + visual + hunger → drive
   - W @ x (recurrent) → drive
   - Leaky integrate: `x ← (1-α)x + α·tanh(drive)`
5. **Readout channels** (0–1) → map to output entity service calls
6. **Mode classification** (energy + spikes + sensory magnitude) → `idle` / `wander` / `escape`
7. **State persistence**: Hunger, mode, lifecycle metadata saved to HA storage every ~50 ticks

No numpy, no torch, no model download. Requirements list in `manifest.json` has only Pillow for optional camera vision.

### Why Not an LLM?

This is **not** a chatbot and should never become one:

- Fruit flies don't have language
- The point is **sensorimotor dynamics**, not "talk to your house"
- LLM APIs would add latency, cost, and defeat the pure-Python toy appeal
- If you want LLM home control, use existing voice assistants — HouseFly is a different vibe

### Add-on Path (Future, Optional)

For users who want heavier processing:

- **MaleCNS weights**: Swap toy reservoir for subset of actual fly connectome (requires torch, ~GB of weights)
- **Camera vision**: Proper image decoding, downsampling, optical flow (requires OpenCV / PIL)
- **GPU acceleration**: Run reservoir update on GPU for larger networks

**None of this ships in the integration.** Keep it lightweight. Add-on is for advanced users who want to go deeper.

---

## v2 Exploration (optional add-on path — not shipped here)

Local `assets/` may contain MaleCNS-related metadata or larger weights for **experiments**. Those are **not** bundled into this HACS integration (multi‑GB, torch, etc.). A future add-on could swap the toy matrix for a connectome-derived reservoir; see notes in repo. Until then, enjoy the fruit fly cosplay.

---

## Contributing

Contributions are welcome! 🎉

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for:

- Development setup
- Code style guidelines
- Testing checklist
- How to submit bug reports / feature requests / pull requests

**Quick links:**

- [Report a bug](https://github.com/Vortitron/HouseFly/issues/new?template=bug_report.md)
- [Request a feature](https://github.com/Vortitron/HouseFly/issues/new?template=feature_request.md)
- [View open issues](https://github.com/Vortitron/HouseFly/issues)

HouseFly is a **weekend meme** — we value lightweight, fun contributions that keep the fruit-fly spirit alive! 🪰

---

## Licence

- **Code:** MIT (see `LICENSE`)
- **Inspiration / MaleCNS data (not included):** QuixiAI/MaleCNS — CC-BY 4.0

---

## Contributing

HouseFly started as an experiment in mapping dynamical systems onto home automation. Contributions that preserve the founding spirit are welcome:

- Keep it **playful but intentional** — this is toy science done with care
- Maintain **pure Python core** (no numpy/torch in the integration)
- Preserve the **honest science disclaimer** (comedic resemblance to real neuroscience)
- Test thoroughly with actual Home Assistant installations
- Document changes clearly

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for detailed guidelines.

---

## Links

- 🪰 **Visual setup guide:** [`VISUAL_SETUP_GUIDE.md`](VISUAL_SETUP_GUIDE.md)
- 📋 **Lovelace examples:** [`LOVELACE_EXAMPLE.yaml`](LOVELACE_EXAMPLE.yaml)
- 🤝 **Contributing guide:** [`CONTRIBUTING.md`](CONTRIBUTING.md)
- 📢 **Forum post draft:** [`FORUM_POST.md`](FORUM_POST.md)
- 🏠 Watch remotely when away: [vome.io](https://vome.io)
- 🔍 Optional: [fynd.vome.io](https://fynd.vome.io)
- 🧬 MaleCNS packaging: [huggingface.co/QuixiAI/MaleCNS](https://huggingface.co/QuixiAI/MaleCNS)
