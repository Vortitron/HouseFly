# [Share your Projects!] HouseFly — let a fruit fly control your house (HACS toy)

**Category:** Share your Projects! / Custom Integrations  
**Tone:** weekend meme, honest science

---

Hey Community 👋

I built a tiny HACS integration for the sole purpose of answering an important research question:

> What if a fruit fly ran the living room lights?

### What it actually is

**HouseFly** is a Home Assistant custom component that:

1. Reads 1–32 sensors you pick (what the fly can "see")
2. Shoves them into a **~256-dim leaky reservoir** (pure Python, seeded sparse matrix)  
3. Maps readout channels to lights / covers / switches / numbers (what the fly can "control")
4. Exposes `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`), and `sensor.fly_house_brain` with **ASCII art brain visualisation**
5. Ships with **animated SVG fly + brain assets** for Lovelace (buzzing wings, sparking connectome nodes — proper meme-y visual DNA)
6. Offers `fly_house.poke` for when you need to… scientifically perturb the organism
7. Optional **whole house mode** for maximum chaos (⚠️ not recommended for beginners!)

Tick interval defaults to 10 seconds. Intensity and seed are configurable. No cloud required for the fly itself.

### What it is NOT

- **Not** a real Drosophila brain on your Pi  
- **Not** downloading MaleCNS / torch / multi-GB weights  
- **Not** peer-reviewed home automation  

It's inspired by the fun orbit around MaleCNS / fly-llm / "chessfly" / flyputer demos — especially the idea of a connectome as an echo-state reservoir. We cite **QuixiAI/MaleCNS (CC-BY 4.0)** for inspiration only. v1 is a random matrix wearing antennae.

### Why

Weekend project. Soft chaos. Guests ask what the flickering lamp is doing and you get to say "the fly is escaping." Also a gentle excuse to glance at the house when you're out via [vome.io](https://vome.io) (optional: [fynd.vome.io](https://fynd.vome.io)).

### Safety ⚠️

**Start with ONE spare bulb.** Seriously.

Do not:
- Give the fly your garage door on day one
- Enable whole house mode without reading the warnings
- Wire it to critical infrastructure (thermostats, security, etc.)
- Blame me when your living room looks like a nightclub

The "whole house mode" toggle exists for brave souls and content creators. Intensity exists for a reason. The config flow now supports multi-select so you can pick exactly what the fly sees and controls (up to 32 each).

### Install

HACS custom repository → Integration → `https://github.com/Vortitron/HouseFly` → restart → Add Integration → HouseFly.  
Or drop `custom_components/fly_house` into your config folder.

### Visual setup

After installing, add the Lovelace cards from the repo's `LOVELACE_EXAMPLE.yaml`. The animated fly SVG and brain sparks are automatically available at:
- `/local/community/fly_house/fly-animated.svg`
- `/local/community/fly_house/brain-sparks.svg`

The `sensor.fly_house_brain` entity shows live ASCII art of neural activity. All the visual DNA from chessfly/flyputer demos, zero GPU required.

Happy buzzing. If your `mode` stuck on `escape`, try poking less. Or more. Science is messy. 🪰⚡

— a responsible adult who definitely reviewed the brightness mapping twice
