# [Share your Projects!] HouseFly — let a fruit fly control your house (HACS integration)

**Category:** Share your Projects! / Custom Integrations  
**Tone:** Founding experiment, playful but intentional

---

Hey Community 👋

I've been exploring an interesting question in home automation:

> What if you mapped your sensors into a fruit-fly-inspired dynamical system and let it control the lights?

### What HouseFly actually is

**HouseFly v1.0** is a Home Assistant custom component exploring sensorimotor dynamics in home automation, inspired by fruit fly biology:

1. **Compound eye** (16×16 ommatidia): Optional HA camera snapshot → real luminance grid (Pillow), else lights+sun synthesis; phototaxis + motion detection
2. **Hunger drive**: Internal state rises over time, triggers foraging behaviour (more exploration + light-seeking when hungry); persists across HA restarts
3. **Reservoir brain**: ~256-neuron pure Python leaky-tanh network processes sensory inputs + vision + hunger → motor outputs
4. **Lifecycle tracking**: Birth time, time alive, last poke/feed timestamps — the fly feels like an organism, not an amnesiac demo
5. **Entities**: `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`), `sensor.fly_house_brain`, `sensor.fly_house_hunger`, `sensor.fly_house_retina` (ommatidia hex grid)
6. **Services**: `fly_house.poke` (sensory jolt) and `fly_house.feed` (reduces hunger, calms foraging)
7. **Custom Lovelace card**: `housefly-card` — animated fly + faceted compound eye + hunger bar + brain stats + Poke/Feed buttons (pure vanilla JS, no build step)
8. **Visual assets**: Animated SVG fly + brain connectome sparks (buzzing wings, sparking nodes)
9. **Whole house mode**: Auto-selects up to 32 devices, requires scary confirmation (⚠️ not recommended for beginners!)

**This is a toy dynamical system**, not an LLM chatbot. It has hunger, sees through a fake compound eye, and exhibits phototaxis. No torch, no numpy, no cloud API calls.

Tick interval defaults to 10 seconds. Intensity and seed are configurable.

### What it is NOT

- **Not** a real *Drosophila* brain on your Pi  
- **Not** an LLM chatbot (no "talk to your fly" nonsense)
- **Not** downloading MaleCNS / torch / multi-GB weights  
- **Not** peer-reviewed home automation  

It's a **toy dynamical system** inspired by fruit-fly sensorimotor motifs (compound eyes, hunger-driven foraging, escape responses) and the fascinating work around MaleCNS / fly-llm / "chessfly" / flyputer demos. We cite **QuixiAI/MaleCNS (CC-BY 4.0)** for inspiration only. Pure Python leaky reservoir + toy vision + hunger drives.

### The deeper hook

It's not just "random flickering" — **it gets hungry and remembers across restarts.**

- Watch `sensor.fly_house_hunger` climb from 0% → 100% over ~8 hours
- Feed it (`fly_house.feed`) and see the foraging drive calm down
- Restart Home Assistant → fly wakes up with the same hunger level, remembers its age
- Turn on a bright light across the room → hungry fly biases motor outputs towards that light (phototaxis)
- Sudden brightness change → ommatidia detect motion → escape mode triggered
- Use the custom card to see the 16×16 faceted eye light up in real-time

Guests ask what the flickering lamp is doing and you get to say "the fly is hungry and tracking the kitchen light."

Also a gentle excuse to glance at the house when you're out via [vome.io](https://vome.io) (optional: [fynd.vome.io](https://fynd.vome.io)).

### Why I built this

HouseFly started as an experiment in applying dynamical systems thinking to home automation — not as a gag, but as an intentional exploration of what happens when you treat your smart home like a sensorimotor environment. The fruit fly framing is playful, but the implementation is deliberate:

- Pure Python reservoir dynamics (no black-box ML dependencies)
- Hunger as a continuous internal drive (not a one-shot trigger)
- Camera-to-ommatidia visual processing (real Pillow downsample, not fake hex strings)
- State persistence across restarts (the fly feels like an organism with continuity)

It's weird, possibly useless, definitely fun — but it's **weird on purpose** as a way to explore alternative patterns in home automation.

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

Happy buzzing. If your `mode` is stuck on `escape`, try feeding the fly. Or poke less. Or more. Science is exploratory. 🪰⚡🍎

— someone who definitely reviewed the brightness mapping twice

---

**Links:**
- GitHub: https://github.com/Vortitron/HouseFly
- Quick start: [`QUICK_START.md`](https://github.com/Vortitron/HouseFly/blob/main/QUICK_START.md)
- Visual guide: [`VISUAL_SETUP_GUIDE.md`](https://github.com/Vortitron/HouseFly/blob/main/VISUAL_SETUP_GUIDE.md)
- Lovelace examples: [`LOVELACE_EXAMPLE.yaml`](https://github.com/Vortitron/HouseFly/blob/main/LOVELACE_EXAMPLE.yaml)
