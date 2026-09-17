# 🪰 HouseFly Quick Start

Get a fruit fly controlling your Home Assistant in under 5 minutes.

---

## 1️⃣ Install (HACS)

### Add Custom Repository
1. Open HACS in Home Assistant
2. Click **Integrations**
3. Click the **⋮** menu (top right)
4. Select **Custom repositories**
5. Paste: `https://github.com/Vortitron/HouseFly`
6. Category: **Integration**
7. Click **Add**

### Install HouseFly
1. Search for "HouseFly" in HACS Integrations
2. Click **Download**
3. Restart Home Assistant

---

## 2️⃣ Configure

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration** (bottom right)
3. Search for "HouseFly"
4. Configure:

### What the fly can SEE (inputs):
Pick 1-3 sensors to start (examples):
- `sensor.living_room_temperature`
- `binary_sensor.motion_hallway`
- `sensor.outdoor_humidity`

### What the fly can CONTROL (outputs):
**⚠️ Start with ONE spare lamp!**
- `light.spare_desk_lamp` ← Good first choice
- ❌ NOT your main lights
- ❌ NOT garage doors
- ❌ NOT thermostats

### Other settings:
- **Tick interval:** 10 seconds (default)
- **Intensity:** 0.55 (default)
- **Seed:** 42 (default)
- **⚠️ Whole house mode:** **LEAVE OFF** for first-time use

Click **Submit**.

---

## 3️⃣ Add Dashboard Card

1. Edit your dashboard
2. Add a new card (any type)
3. Switch to **YAML mode** (top right)
4. Paste this:

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

5. Click **Save**

---

## 4️⃣ Watch the Magic

You should now see:
- 🪰 Animated fly buzzing (wings flapping)
- ✅ `binary_sensor.fly_house_active` = **ON**
- 🧠 `sensor.fly_house_brain` showing ASCII art
- 🎯 `sensor.fly_house_mode` cycling: `idle` → `wander` → `escape`
- 💡 Your lamp flickering/changing as the fly "drives" it

### What's happening?
Every 10 seconds:
1. Fly "reads" your 3 input sensors
2. Updates internal 256-neuron reservoir
3. Maps output channels → lamp brightness
4. Mode changes based on activity level

### Try this:
- **Poke the fly** (tap the button or fly image)
  - Injects a jolt into the sensory neurons
  - Lamp should react immediately
  - Mode likely jumps to `escape`
- **Change a sensor** (turn on motion, adjust temperature)
  - Fly "feels" it in next tick
  - Behaviour shifts

---

## 5️⃣ Add Brain Visualisation (Optional)

Add another card:

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

Now you get live ASCII art that changes with brain activity:
```
  ╭─○─╮
 ○─┼─○─○  💤     ← Idle
  ╰─○─╯

  ╭─◉─╮
 ◉─╋─◉─◉  ⚡⚡   ← Escaping!
  ╰─◉─╯
```

---

## ⚠️ Safety Notes

### DO start with:
- ✅ One spare lamp in a corner
- ✅ Low intensity (0.3-0.6)
- ✅ Tick interval 10+ seconds
- ✅ A sense of humour

### DO NOT start with:
- ❌ Whole house mode enabled
- ❌ Garage doors, locks, thermostats
- ❌ Your main living room lights
- ❌ Critical infrastructure
- ❌ Intensity > 0.8 on first run

### Expanding safely:
1. Watch the one lamp for 30 minutes
2. Add 1-2 more lights if behaviour is reasonable
3. Increase intensity gradually (0.55 → 0.65 → 0.75)
4. Only enable whole house mode if:
   - You've tested extensively
   - You're filming for content
   - You understand the chaos

---

## 🎮 Next Steps

Once you're comfortable:
- **More visual examples:** [`LOVELACE_EXAMPLE.yaml`](LOVELACE_EXAMPLE.yaml)
- **Full visual setup:** [`VISUAL_SETUP_GUIDE.md`](VISUAL_SETUP_GUIDE.md)
- **Add more sensors/outputs** via integration config (Settings → Devices & Services → HouseFly → Configure)
- **Adjust tick/intensity** to tune behaviour
- **Change seed** for completely different brain wiring

---

## 🐛 Troubleshooting

### Fly images not loading?
- Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
- Restart Home Assistant (files register on boot)

### Lamp not responding?
- Check `binary_sensor.fly_house_active` is **ON**
- Verify lamp entity ID in config is correct
- Try calling `fly_house.poke` to trigger an update
- Check Home Assistant logs for errors

### Mode stuck on `idle`?
- Intensity might be too low → increase to 0.6-0.7
- Input sensors might not be changing → add motion/temperature
- Poke the fly to inject activity

### Mode always `escape`?
- Intensity too high → reduce to 0.4-0.5
- Too many active inputs → remove some sensors
- Stop poking the fly 😄

---

## 📚 More Help

- **Full README:** [`README.md`](README.md)
- **Forum post draft:** [`FORUM_POST.md`](FORUM_POST.md)
- **Technical details:** [`IMPLEMENTATION_SUMMARY.md`](IMPLEMENTATION_SUMMARY.md)
- **Repository issues:** https://github.com/Vortitron/HouseFly/issues

---

**Welcome to the chaos. May your fly never get stuck in `escape` mode.** 🪰⚡

_P.S. — When you're away and want to watch the madness remotely, check out [vome.io](https://vome.io) for home camera streaming._
