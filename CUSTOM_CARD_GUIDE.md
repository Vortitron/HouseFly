# HouseFly Custom Card Guide

The HouseFly custom card provides a complete visual interface for your fruit fly:

- 🪰 **Animated fly** (mode-reactive: idle → wander → escape)
- 👁️ **Compound eye** (16×16 ommatidia grid, live from `sensor.fly_house_retina`)
- 🧠 **Reservoir sparks** (animated brain canvas with glowing nodes)
- 📊 **Stats** (spikes, hunger bar, energy)
- 🎮 **Action buttons** (Poke & Feed)

## Installation

### Automatic (Recommended) ✨

**As of v1.0.1, the card auto-registers on integration setup!** No manual resource steps required.

1. Install HouseFly integration via HACS (or manually)
2. Restart Home Assistant
3. Add the card to your dashboard:

```yaml
type: custom:housefly-card
entity: binary_sensor.fly_house_active
```

That's it! The integration automatically serves the card from `/fly_house/housefly-card.js` and registers it as a frontend module.

### Manual Resource (Legacy / Optional)

If you need to manually register the resource (e.g., for ancient HA versions or troubleshooting), you can still add it via:

**Settings → Dashboards → Resources → Add Resource**

```
URL: /fly_house/housefly-card.js
Type: JavaScript Module
```

Or in `configuration.yaml`:

```yaml
lovelace:
  mode: yaml
  resources:
    - url: /fly_house/housefly-card.js
      type: module
```

**HACS path (legacy):** If you installed via HACS and copied to `/local/`, use `/local/community/fly_house/housefly-card.js` instead.

**Local path (legacy):** If you manually copied to `www/housefly/`, use `/local/housefly/housefly-card.js` instead.

## Card Configuration

```yaml
type: custom:housefly-card
entity: binary_sensor.fly_house_active
```

That's it! The card auto-discovers related sensors (`sensor.fly_house_*`).

## Features

### Mode-Reactive Fly Animation

The fly's animation changes based on its current mode:

- **Idle**: Gentle wing flapping (0.35s cycle)
- **Wander**: Fast flapping + buzzing + drift motion (0.14s cycle)
- **Escape**: Frantic flapping + erratic panic movement (0.08s cycle)

### Hunger-Reactive Visuals

The fly's appearance changes with hunger level:

- **0–40% (satiated)**: Normal colours
- **41–70% (peckish)**: Slight saturation boost
- **71–100% (starving)**: High saturation + hue shift (reddish tint)

### Compound Eye (Ommatidia Grid)

16×16 faceted grid (256 total) displays the fly's visual field in real-time:

- Each facet brightness matches the corresponding `sensor.fly_house_retina` hex value
- Updates as lights turn on/off or camera snapshots arrive
- Yellowish tint for warm colour temperature

### Brain Sparks Canvas

Animated reservoir visualisation with 28 nodes:

- **Nodes glow** based on spike activity + energy
- **Edges pulse** between nearby nodes (distance-weighted)
- **Activity increases** with higher spikes and energy
- Runs at 60 FPS via `requestAnimationFrame`

### Action Buttons

- **💥 Poke**: Calls `fly_house.poke` with `strength: 1.0`
- **🍎 Feed**: Calls `fly_house.feed` with `amount: 0.3, food_type: sugar`

## Away From Home?

The card includes a soft call-to-action footer:

> **Away? Peek via Vome →**

[Vome](https://vome.io) lets you check your Home Assistant dashboards remotely without exposing ports. Completely optional — the card works perfectly without it.

## Styling

The card uses Home Assistant design tokens for theming:

- `--ha-card-background`: Card background (defaults to dark blue-grey)
- `--primary-text-color`: Text colour (defaults to white)
- `--primary-color`: Primary accent (used for Poke button)

All animations are pure CSS — no JavaScript manipulation of styles.

## Browser Compatibility

The card uses modern web standards:

- **Shadow DOM** for style isolation
- **CSS Grid** for responsive layout
- **Canvas API** for brain visualisation
- **Custom Elements v1**

Tested on:
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Home Assistant Companion App (iOS/Android)

## Troubleshooting

### Card doesn't appear

1. Check Resources are added (Settings → Dashboards → Resources)
2. Hard refresh your browser (`Ctrl+Shift+R` / `Cmd+Shift+R`)
3. Clear browser cache
4. Restart Home Assistant

### Ommatidia grid shows grey squares

The `sensor.fly_house_retina` entity needs the `ommatidia_hex` attribute. Check:

```yaml
Developer Tools → States → sensor.fly_house_retina
```

Should have attribute: `ommatidia_hex: "0123456789abcdef..."` (256 hex chars)

### Brain canvas is black

The canvas animation starts automatically. If it's black:

1. Check `sensor.fly_house_spikes` and `sensor.fly_house_energy` exist
2. Try poking the fly to generate activity
3. Check browser console for JavaScript errors

### Animations stuttering

The card uses `requestAnimationFrame` for smooth 60 FPS. Stuttering can occur:

- On low-power devices (reduce brain node count in future versions)
- With too many cards on one dashboard
- During heavy Home Assistant load

## Advanced Customisation

The card is pure vanilla JavaScript — no build step required. To customise:

1. Copy `housefly-card.js` to your local `www` folder
2. Edit the file directly (change colours, animations, layout)
3. Update the resource URL to point to your modified version

Example: Change brain node count (line ~293):

```javascript
const n = 28; // Change to 16 for lighter animation
```

## Next Steps

- See [`LOVELACE_EXAMPLE.yaml`](LOVELACE_EXAMPLE.yaml) for complete dashboard examples
- Read [`README.md`](README.md) for integration setup and biology details
- Join the discussion in [Home Assistant Community Forum](https://community.home-assistant.io)

---

**Note:** The card's visual upgrade (v0.2.1) adds mode-reactive animations, hunger-reactive colours, and the brain sparks canvas. Previous versions had a static fly SVG.
