# [Share your Projects!] HouseFly — let a fruit fly control your house (HACS toy)

**Category:** Share your Projects! / Custom Integrations  
**Tone:** weekend meme, honest science

---

Hey Community 👋

I built a tiny HACS integration for the sole purpose of answering an important research question:

> What if a fruit fly ran the living room lights?

### What it actually is

**HouseFly v1.1** is a Home Assistant custom component with fruit-fly-inspired sensorimotor dynamics:

1. **Compound eye** (16×16 ommatidia): Synthesizes visual field from your lights + sun position, feeds phototaxis + motion detection pathways
2. **Hunger drive**: Internal state rises over time, triggers foraging behavior (more exploration + light-seeking when hungry)
3. **Reservoir brain**: ~256-neuron pure Python leaky-tanh network processes sensory inputs + vision + hunger → motor outputs
4. **Entities**: `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`), `sensor.fly_house_brain`, `sensor.fly_house_hunger`, `sensor.fly_house_retina` (ommatidia hex grid)
5. **Services**: `fly_house.poke` (sensory jolt) and `fly_house.feed` (reduces hunger, calms foraging)
6. **Custom Lovelace card**: `housefly-card` — animated fly + faceted compound eye + hunger bar + brain stats + Poke/Feed buttons (pure vanilla JS, no build step)
7. **Visual assets**: Animated SVG fly + brain connectome sparks (buzzing wings, sparking nodes)
8. **Whole house mode**: Auto-selects up to 32 devices, requires scary confirmation (⚠️ not recommended for beginners!)

**This is a toy dynamical system**, not an LLM chatbot. It has hunger, sees through a fake compound eye, and exhibits phototaxis. No torch, no numpy, no cloud API calls.

Tick interval defaults to 10 seconds. Intensity and seed are configurable.

### What it is NOT

- **Not** a real Drosophila brain on your Pi  
- **Not** an LLM chatbot (no "talk to your fly" nonsense)
- **Not** downloading MaleCNS / torch / multi-GB weights  
- **Not** peer-reviewed home automation  

It's a **toy dynamical system** inspired by fruit-fly sensorimotor motifs (compound eyes, hunger-driven foraging, escape responses) and the fun orbit around MaleCNS / fly-llm / "chessfly" / flyputer demos. We cite **QuixiAI/MaleCNS (CC-BY 4.0)** for inspiration only. Pure Python leaky reservoir + toy vision + hunger drives.

### Why (the deeper hook)

It's not just "random flickering" — **it gets hungry and sees through a fake compound eye.**

- Watch `sensor.fly_house_hunger` climb from 0% → 100% over ~8 hours
- Feed it (`fly_house.feed`) and see the foraging drive calm down
- Turn on a bright light across the room → hungry fly biases motor outputs toward that light (phototaxis)
- Sudden brightness change → ommatidia detect motion → escape mode triggered
- Use the custom card to see the 16×16 faceted eye light up in real-time

Guests ask what the flickering lamp is doing and you get to say "the fly is hungry and tracking the kitchen light."

Also a gentle excuse to glance at the house when you're out via [vome.io](https://vome.io) (optional: [fynd.vome.io](https://fynd.vome.io)).

### Safety ⚠️

**Start with ONE spare bulb.** Seriously.

Do not:
- Give the fly your garage door on day one
- Enable whole house mode without reading the warnings
- Wire it to critical infrastructure (thermostats, security, etc.)
- Blame me when your living room looks like a nightclub

The "whole house mode" toggle exists for brave souls and content creators. Intensity exists for a reason. The config flow now supports multi-select so you can pick exactly what the fly sees and controls (up to 32 each).

**Whole house mode** is real and scary:
- Enable the toggle → confirmation step appears
- Shows exact device count (e.g. "43 lights/switches/covers/fans")
- Must check "I understand this can thrash my house" to proceed
- Auto-selects up to 32 controllable entities
- Forces safety: tick ≥15s, intensity ≤0.4
- Static snapshot (reconfigure to refresh entity list)

### Install

HACS custom repository → Integration → `https://github.com/Vortitron/HouseFly` → restart → Add Integration → HouseFly.  
Or drop `custom_components/fly_house` into your config folder.

### Visual setup

After installing, add the **custom Lovelace card** for the full experience:

1. Add resource: `/local/community/fly_house/housefly-card.js` (Settings → Dashboards → Resources)
2. Add card: `type: custom:housefly-card` with `entity: binary_sensor.fly_house_active`

**Card shows:**
- Animated fly (tap to poke)
- 16×16 faceted compound eye (ommatidia grid, updates in real-time)
- Hunger bar (green → yellow → red as hunger rises)
- Brain stats (spikes, energy, mode)
- Poke + Feed buttons

Or use the basic Lovelace cards from `LOVELACE_EXAMPLE.yaml`. Assets:
- `/local/community/fly_house/fly-animated.svg`
- `/local/community/fly_house/brain-sparks.svg`

The `sensor.fly_house_brain` entity shows live ASCII art. The `sensor.fly_house_retina` has ommatidia hex data. All the visual DNA from chessfly/flyputer demos, zero GPU, pure Python.

Happy buzzing. If your `mode` stuck on `escape`, try feeding the fly. Or poke less. Or more. Science is messy. 🪰⚡🍎

— a responsible adult who definitely reviewed the brightness mapping twice
