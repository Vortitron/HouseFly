# 🪰 HouseFly Visual Setup Guide

Get the full **chessfly/flyputer demo vibe** with animated flies and brain visualisations!

---

## 🎨 What You Get

After installing HouseFly, you automatically have access to:

1. **Animated buzzing fly** SVG (wings flapping, body buzzing)
2. **Brain connectome** SVG (glowing nodes, sparking synapses)
3. **ASCII art brain sensor** (changes with neural activity)
4. **Multi-entity dashboard** ready to use

---

## 📦 Quick Start (5 minutes)

### Step 1: Install HouseFly via HACS

```
HACS → Integrations → ⋮ Menu → Custom repositories
Repository: https://github.com/Vortitron/HouseFly
Category: Integration
```

Install, restart Home Assistant.

### Step 2: Add the Integration

```
Settings → Devices & Services → Add Integration → Search "HouseFly"
```

Configure:
- Pick 1-3 sensors the fly can "see" (temperature, motion, etc.)
- Pick 1-2 lights/switches it can "control" (start small!)
- Leave other settings at defaults
- **Do NOT enable whole house mode yet!**

### Step 3: Add Dashboard Cards

Open your dashboard in edit mode, add a new card, paste this YAML:

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
```

Save. You should see:
- ✅ Animated fly buzzing
- ✅ Four status entities
- ✅ Tap the fly to "poke" it

### Step 4: Add Brain Visualisation

Add another card with this YAML:

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

Now you'll see live ASCII art that changes as the brain activity changes:
- `💤🧠` — Idle (low activity)
- `·🧠` — Light activity
- `✨🧠` — Moderate (wandering)
- `⚡💥🧠` — High spikes (escaping!)

---

## 🎭 Advanced: Side-by-Side Demo

For the full **chessfly aesthetic** (fly + brain side-by-side):

```yaml
type: horizontal-stack
cards:
  - type: picture
    image: /local/community/fly_house/fly-animated.svg
    tap_action:
      action: call-service
      service: fly_house.poke
      data:
        strength: 2.0
  - type: picture
    image: /local/community/fly_house/brain-sparks.svg
    tap_action:
      action: more-info
      entity: sensor.fly_house_brain
```

This gives you:
- Left: Buzzing fly (wings animated)
- Right: Sparking brain (nodes pulsing)
- Tap fly = poke with strength 2.0
- Tap brain = open sensor details

---

## 🎯 Picture Elements (Moving Fly!)

Want the fly to **move around** based on brain activity? Try this:

```yaml
type: picture-elements
image: https://via.placeholder.com/600x400/1a1a1a/ffffff?text=Your+House
elements:
  - type: image
    entity: binary_sensor.fly_house_active
    image: /local/community/fly_house/fly-animated.svg
    style:
      left: >
        {% set channels = state_attr('sensor.fly_house_brain', 'channels') %}
        {{ (channels[0] * 90 + 5) if channels else 50 }}%
      top: >
        {% set channels = state_attr('sensor.fly_house_brain', 'channels') %}
        {{ (channels[1] * 80 + 10) if channels and channels|length > 1 else 50 }}%
      width: 60px
      transform: translate(-50%, -50%)
      transition: all 0.3s ease-in-out
```

The fly now moves based on brain channel outputs! Replace the placeholder with an actual floorplan image.

---

## 🐛 Troubleshooting

### Images Not Loading?

1. **Restart Home Assistant** after first install (files need to be registered)
2. Check browser console for 404 errors
3. Verify path: Should be `/local/community/fly_house/fly-animated.svg`
4. Try hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)

### Brain Sensor Not Showing ASCII Art?

The `sensor.fly_house_brain` may take 1-2 update cycles to populate. Wait 10-20 seconds (default tick interval is 10s).

### Fly Not Moving in Picture Elements?

- Check that `sensor.fly_house_brain` has `channels` attribute (click sensor → Developer Tools → States)
- Ensure the integration is running (`binary_sensor.fly_house_active` should be ON)
- Poke the fly to trigger updates

---

## 🎨 Customisation

### Change Fly Size

In any picture card, add `style` under the image:

```yaml
- type: picture
  image: /local/community/fly_house/fly-animated.svg
  style:
    width: 120px  # Default is SVG size, adjust as needed
```

### Adjust Brain Card Background

Add a colored background to the markdown brain card:

```yaml
type: markdown
style: |
  ha-card {
    background: #1a1a2e;
    border: 2px solid #4a4a6e;
  }
content: |
  ## 🧠 Fly Brain Activity
  ...
```

### Multiple Flies (Why Not?)

Install the integration once, but use the same SVG assets in multiple cards. Each card can call `fly_house.poke` with different strengths.

---

## 📸 Screenshots / Recording

The visual assets make great content for:
- Home Assistant community posts
- YouTube demos
- Blog posts about weird HA integrations
- Showing guests "a fruit fly controls my lights"

Just capture your dashboard with the fly buzzing + mode flipping between `wander` and `escape`.

---

## 🔗 More Examples

Full collection of 6+ dashboard layouts: See `LOVELACE_EXAMPLE.yaml` in the repository.

---

**Have fun, start with one lamp, and may your fly never get stuck in `escape` mode!** 🪰⚡
