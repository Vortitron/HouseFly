# 🎴 HouseFly Custom Card Guide

The **housefly-card** is a custom Lovelace card that displays the full fly experience in one compact panel.

---

## What You Get

- 🪰 **Animated fly** (buzzing wings, tap to poke)
- 👁️ **Compound eye** (16×16 ommatidia grid, updates in real-time)
- 📊 **Brain stats** (spikes, energy, mode badge)
- 🍽️ **Hunger bar** (gradient: green → yellow → red)
- 🔘 **Action buttons** (Poke / Feed)

All in one card, using Home Assistant design tokens for automatic theming.

---

## Installation

### Step 1: Add Resource

**Via UI (Recommended):**

1. Go to **Settings** → **Dashboards**
2. Click **⋮** (top right) → **Resources**
3. Click **Add Resource**
4. Enter:
   - **URL:** `/local/community/fly_house/housefly-card.js`
   - **Resource type:** JavaScript Module
5. Click **Create**
6. Hard refresh browser: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)

**Via `configuration.yaml`:**

```yaml
lovelace:
  mode: yaml  # Or storage with manual resource add
  resources:
    - url: /local/community/fly_house/housefly-card.js
      type: module
```

Restart Home Assistant if using YAML mode.

### Step 2: Add Card

1. Edit your dashboard
2. Click **Add Card**
3. Search "HouseFly" or scroll to **Manual**
4. Paste this YAML:

```yaml
type: custom:housefly-card
entity: binary_sensor.fly_house_active
```

5. Click **Save**

---

## Card Features

### Animated Fly

- **Buzzing animation** (body vibrates slightly)
- **Flapping wings** (CSS keyframe animation, 0.15s cycle)
- **Tap action** → calls `fly_house.poke` with strength 1.0
- **Hover** → slight opacity change for feedback

### Compound Eye (Ommatidia Grid)

- **16×16 grid** = 256 facets
- Each facet represents one "ommatidium" (insect eye unit)
- **Color mapping:** Brightness 0–15 → RGB gradient (darker → brighter)
- **Real-time updates** from `sensor.fly_house_retina` ommatidia_hex attribute
- **Visual effect:** Facets light up as your lights turn on, darken when off

**Example:** Turn on kitchen light → top-right quadrant of grid brightens → fly's phototaxis pathway activates

### Mode Badge

- **IDLE** (grey) → Low activity, grooming
- **WANDER** (teal) → Exploring, foraging
- **ESCAPE** (red) → High spikes, loom response

Updates from `sensor.fly_house_mode` in real-time.

### Stats Panel

**Spikes:** Raw spike count from reservoir  
**Hunger:** 0–100% with color-coded bar (green → yellow → red)  
**Energy:** RMS energy of reservoir state (0.00–1.00)

### Action Buttons

**💥 Poke:**
- Calls `fly_house.poke` service
- Strength: 1.0 (moderate)
- Effect: Injects sensory jolt → likely triggers escape mode

**🍎 Feed:**
- Calls `fly_house.feed` service
- Amount: 0.3 (reduces hunger by 30%)
- Food type: "sugar" (cosmetic)
- Effect: Hunger bar drops, foraging drive calms

---

## Configuration Options

### Basic

```yaml
type: custom:housefly-card
entity: binary_sensor.fly_house_active
```

**Required:**
- `entity` — Must be `binary_sensor.fly_house_active` (card auto-discovers related sensors)

**That's it!** The card automatically finds:
- `sensor.fly_house_brain`
- `sensor.fly_house_hunger`
- `sensor.fly_house_retina`
- `sensor.fly_house_spikes`
- `sensor.fly_house_mode`

### Future Options (Not Yet Implemented)

```yaml
type: custom:housefly-card
entity: binary_sensor.fly_house_active
poke_strength: 2.0        # Custom poke strength
feed_amount: 0.5          # Custom feed amount
hide_eye: false           # Hide ommatidia grid
hide_buttons: false       # Hide action buttons
theme: dark               # Force theme (overrides HA theme)
```

Currently v1.0 is intentionally simple — one entity, auto-discovery, no config needed.

---

## Theming

The card uses Home Assistant design tokens:

- `--ha-card-background` → Card background
- `--primary-text-color` → Text color
- `--primary-color` → Poke button color

**To customize:**

Add to your theme (`configuration.yaml` or theme file):

```yaml
my-housefly-theme:
  ha-card-background: "#1a1a2e"
  primary-color: "#00ffff"
  primary-text-color: "#ffffff"
```

Apply theme → card updates automatically.

---

## Technical Details

### Pure Vanilla JS

- **No build step** required
- **No external dependencies** (React, Vue, etc.)
- **Web Components API** (`HTMLElement` + Shadow DOM)
- **File size:** ~8KB unminified

### Browser Compatibility

- Chrome/Edge: ✅ Full support
- Firefox: ✅ Full support
- Safari: ✅ Full support (iOS 12+)
- Home Assistant Companion App: ✅ Works

### Performance

- **Ommatidia updates:** Only when `sensor.fly_house_retina` changes (every tick, default 10s)
- **Animations:** CSS-only (GPU-accelerated, no JS loop)
- **DOM updates:** Minimal (only stat values, not structure)

### Accessibility

- **Keyboard navigation:** Buttons are focusable
- **Screen readers:** Stat labels read aloud
- **Color contrast:** Uses HA theme tokens (WCAG AA compliant)

---

## Troubleshooting

### Card Not Showing

1. **Check resource loaded:**
   - Developer Tools → Console
   - Look for errors mentioning `housefly-card.js`
   - If 404: restart Home Assistant (resource not registered)

2. **Hard refresh browser:**
   - `Ctrl+Shift+R` (Windows/Linux)
   - `Cmd+Shift+R` (Mac)
   - Clears cached JS

3. **Check entity exists:**
   - Developer Tools → States
   - Search `binary_sensor.fly_house_active`
   - If missing: integration not configured

### Ommatidia Grid Not Updating

1. **Check retina sensor:**
   - Developer Tools → States → `sensor.fly_house_retina`
   - Look for `ommatidia_hex` attribute (256-character hex string)
   - If empty: brain not generating vision data

2. **Turn on lights:**
   - Ommatidia grid synthesized from lights + sun
   - All lights off = dark grid (working as intended)
   - Turn on lamp → facets should brighten within 10s (one tick)

3. **Check console:**
   - Developer Tools → Console
   - Look for errors in `updateOmmatidia()` function

### Buttons Not Working

1. **Check services exist:**
   - Developer Tools → Services
   - Search `fly_house.poke` and `fly_house.feed`
   - If missing: integration not loaded

2. **Check browser console:**
   - Click button → look for errors
   - Should see Home Assistant service call in network tab

### Hunger Bar Stuck at 0%

1. **Check hunger sensor:**
   - `sensor.fly_house_hunger` → should be 0–100
   - If always 0: hunger system not ticking

2. **Wait one tick cycle:**
   - Hunger rises slowly (~0.2% per tick)
   - At default 10s tick, reaches 100% in ~8 hours

3. **Feed the fly:**
   - Click **🍎 Feed** button
   - Hunger should drop by 30% immediately
   - Proves card ↔ integration communication works

---

## Advanced Usage

### Multiple Cards

You can add multiple instances:

```yaml
# Living room dashboard
type: custom:housefly-card
entity: binary_sensor.fly_house_active

# Mobile dashboard (same card, different layout context)
type: custom:housefly-card
entity: binary_sensor.fly_house_active
```

All instances show the same fly (only one integration instance supported).

### Combine with Other Cards

**Side-by-side with controlled lights:**

```yaml
type: horizontal-stack
cards:
  - type: custom:housefly-card
    entity: binary_sensor.fly_house_active
  - type: entities
    title: Controlled Lights
    entities:
      - light.living_room
      - light.kitchen
```

Watch the fly's ommatidia track the lights you toggle!

### Picture-in-Picture Style

```yaml
type: picture-elements
image: /local/your-floorplan.png
elements:
  - type: custom:housefly-card
    entity: binary_sensor.fly_house_active
    style:
      top: 10px
      right: 10px
      width: 300px
```

Overlay the fly card on your floorplan.

---

## Source Code

Located at: `custom_components/fly_house/www/housefly-card.js`

Feel free to fork and customize:
- Change colors, sizes, layout
- Add more stats or visualizations
- Modify button behavior

**Keep it pure vanilla JS** (no build step) to maintain the lightweight toy aesthetic.

---

## Future Enhancements

Potential v2 features (not yet implemented):

- **Camera preview:** Show actual camera feed in eye panel (if camera configured)
- **Phototaxis arrow:** Visual indicator showing which light the fly is tracking
- **Hunger schedule:** Auto-feed on a timer
- **Sound effects:** Buzzing audio on poke (optional, off by default)
- **Mini-game:** "Feed the fly before it reaches 100%" challenge mode

---

## Links

- **Main README:** [`README.md`](README.md)
- **Lovelace examples:** [`LOVELACE_EXAMPLE.yaml`](LOVELACE_EXAMPLE.yaml)
- **Visual setup:** [`VISUAL_SETUP_GUIDE.md`](VISUAL_SETUP_GUIDE.md)

**Have fun watching the ommatidia flicker!** 👁️🪰
