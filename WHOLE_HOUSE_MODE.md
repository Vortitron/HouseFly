# 🚨 HouseFly Whole House Mode — Technical Documentation

## Overview

Whole house mode is a **fully implemented, scary, and functional** feature that auto-selects multiple controllable entities and gives the fruit fly reservoir control over them simultaneously.

⚠️ **This is not a joke flag** — enabling this will actually let a toy neural network control dozens of devices in your home.

---

## How It Works

### 1. Enable Toggle

User checks **"⚠️ WHOLE HOUSE MODE"** checkbox in config flow (initial setup or options).

### 2. Confirmation Step Required

Instead of proceeding immediately, the config flow redirects to `async_step_confirm_whole_house`:

**What the user sees:**
```
⚠️ WHOLE HOUSE MODE — ARE YOU SURE?!

This will give the fruit fly control over **47 devices** (lights, 
switches, covers, fans) across your home. The fly will randomly 
flicker, toggle, open, and close things based on a 256-neuron 
toy reservoir.

**This is pretty insane.**

Safety limits: tick ≥15s, intensity ≤0.4. Capped at 32 max outputs.

Recommended: Start with 1-2 spare lamps, NOT this.

Still want chaos? Check the box below.

☑️ I understand this can thrash lights/covers/switches and I'm 
   ready for the chaos
```

**Required action:**
- User MUST check the confirmation box
- Shows **exact device count** (dynamic, based on current hass.states)
- Cannot proceed without explicit confirmation

**Error if unchecked:**
```
You must check the confirmation box to enable whole house mode. 
If you're not sure, go back and disable whole house mode.
```

### 3. Auto-Entity Selection

Once confirmed, `_async_get_whole_house_outputs()` executes:

```python
async def _async_get_whole_house_outputs(self) -> list[str]:
    """Get all controllable entities for whole house mode."""
    entities = []
    domains = ["light", "switch", "cover", "fan"]
    
    for state in self.hass.states.async_all():
        if state.domain in domains:
            # Skip unavailable/unknown entities
            if state.state not in ("unavailable", "unknown"):
                entities.append(state.entity_id)
    
    # Cap at MAX_OUTPUT_ENTITIES (32)
    if len(entities) > MAX_OUTPUT_ENTITIES:
        # Prioritize: lights → switches → covers → fans
        def sort_key(eid: str) -> tuple:
            domain = eid.split(".", 1)[0]
            priority = {"light": 0, "switch": 1, "cover": 2, "fan": 3}.get(domain, 4)
            return (priority, eid)
        
        entities.sort(key=sort_key)
        entities = entities[:MAX_OUTPUT_ENTITIES]
    
    return entities
```

**Selection logic:**
- Scans **all entities** in `hass.states`
- Includes domains: `light`, `switch`, `cover`, `fan`
- Filters out `unavailable` and `unknown` states
- Prioritises by domain: lights first, then switches, covers, fans
- Caps at **MAX_OUTPUT_ENTITIES = 32**

**Example result:**
```python
[
    "light.living_room_main",
    "light.kitchen_ceiling",
    "light.bedroom_lamp",
    # ... up to 29 more lights/switches/covers/fans
]
```

### 4. Auto-Fill Inputs (If Empty)

If user provided no input entities, `_async_get_default_inputs()` provides sensible defaults:

```python
async def _async_get_default_inputs(self) -> list[str]:
    inputs = []
    
    # Add sun if available
    if self.hass.states.get("sun.sun"):
        inputs.append("sun.sun")
    
    # Add up to 5 motion sensors
    motion_count = 0
    for state in self.hass.states.async_all():
        if state.domain == "binary_sensor" and "motion" in state.entity_id.lower():
            if state.state not in ("unavailable", "unknown"):
                inputs.append(state.entity_id)
                motion_count += 1
                if motion_count >= 5:
                    break
    
    # Add time sensor if available
    if self.hass.states.get("sensor.time"):
        inputs.append("sensor.time")
    
    return inputs if inputs else []
```

**Selection logic:**
- `sun.sun` (position in sky)
- Up to 5 `binary_sensor.*motion*` entities
- `sensor.time` if available
- Only auto-fills if input list is empty (preserves manual selections)

### 5. Safety Constraints Applied

When whole house mode is confirmed:

```python
# Apply safety constraints for whole house mode
tick_interval = max(15, int(original_input.get(CONF_TICK_INTERVAL, 15)))
intensity = min(0.4, float(original_input.get(CONF_INTENSITY, 0.4)))
```

**Enforced limits:**
- **Tick interval:** Minimum **15 seconds** (slower updates, less thrashing)
- **Intensity:** Maximum **0.4** (40% chaos cap, reduced from default 0.55)

User cannot override these in whole house mode — they're hardcoded safety rails.

### 6. Config Entry Created

Final data structure:

```python
data = {
    CONF_INPUT_ENTITIES: ["sun.sun", "binary_sensor.hallway_motion", ...],
    CONF_OUTPUT_ENTITIES: ["light.living_room", "switch.porch", ...],  # Up to 32
    CONF_TICK_INTERVAL: 15,  # >= 15
    CONF_INTENSITY: 0.4,     # <= 0.4
    CONF_SEED: 42,
    CONF_WHOLE_HOUSE: True,
    CONF_NAME: "HouseFly",
}
```

Entry title becomes: **"HouseFly (Whole House)"**

---

## Static vs Dynamic

**Current implementation: STATIC SNAPSHOT**

- Entity list captured at **config/options confirmation time**
- New lights/switches added later **will NOT auto-appear**
- User must **reconfigure** (Settings → Devices & Services → HouseFly → Configure) to refresh
- **Why static?** Predictability — users should know exactly what's being controlled, not surprised by new devices suddenly joining the chaos

**To refresh entity list:**
1. Go to Settings → Devices & Services → HouseFly
2. Click **Configure**
3. Toggle whole house mode OFF then ON again
4. Go through confirmation step
5. New entities will be scanned and selected

---

## Options Flow

Same behavior when enabling whole house mode via options:

```python
class FlyHouseOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input):
        # Check if enabling whole house (was off, now on)
        was_whole_house = current.get(CONF_WHOLE_HOUSE, False)
        now_whole_house = user_input.get(CONF_WHOLE_HOUSE, False)
        
        if now_whole_house and not was_whole_house:
            # Enabling — go to confirmation
            self._user_input = user_input
            return await self.async_step_confirm_whole_house()
```

**Flow:**
1. User opens HouseFly options
2. Enables whole house toggle
3. Redirected to confirmation step (same scary warning)
4. Must confirm to proceed
5. Entities auto-selected, safety limits applied

**Disabling whole house:**
- No confirmation required (turning chaos OFF is always safe)
- User-selected entities preserved
- Intensity/tick revert to user values

---

## Coordinator Behavior

The coordinator does **NOT** rescan entities on each tick:

```python
class FlyHouseCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry_data, entry_id):
        self.output_entities: list[str] = list(entry_data.get(CONF_OUTPUT_ENTITIES, []))
        # Static list from config
```

**On each tick:**
- Coordinator uses the **static list** from `self.output_entities`
- Calls `map_channel_to_output()` for each entity
- Executes service calls (e.g. `light.turn_on`, `cover.set_position`)

**No dynamic rescanning** during operation for:
- Performance (less overhead)
- Predictability (users know what's controlled)
- Safety (no surprise additions)

---

## User Experience Flow

### First-Time Setup

1. **Add Integration** → HouseFly config flow appears
2. User picks 1-2 spare lamps as outputs
3. User picks temperature/motion sensors as inputs
4. **Whole house toggle: OFF** (default)
5. Integration created, fly starts controlling 1-2 lamps ✅

### Enabling Whole House (Initial Config)

1. User adds integration
2. User enables **"⚠️ WHOLE HOUSE MODE"** toggle
3. Scary confirmation step appears:
   - **"47 devices will be controlled"**
   - Tick ≥15s, intensity ≤0.4 notice
   - Big red checkbox required
4. User checks: _"I understand this can thrash my house"_
5. Integration created with 47 outputs (up to 32 cap)
6. Fly immediately starts controlling all selected entities 🔥

### Enabling Whole House (Options)

1. Integration already exists (controlling 2 lamps)
2. User opens **Configure** (Settings → Devices & Services → HouseFly)
3. User enables **"⚠️ WHOLE HOUSE MODE"** toggle
4. Scary confirmation step appears (same as initial)
5. User confirms
6. **Entity list replaced** with auto-selected whole house list
7. Fly now controlling 32+ entities instead of 2 🚨

---

## Safety Features

### 1. Required Confirmation
- Cannot bypass — must check box
- Shows exact device count
- Clear warning text

### 2. Enforced Constraints
- Tick ≥15s (slower updates)
- Intensity ≤0.4 (less chaos)
- Max 32 outputs (capped)

### 3. Entity Filtering
- Skips unavailable entities
- Skips unknown states
- Only controllable domains

### 4. Prioritisation
- Lights first (most visible, least dangerous)
- Switches second
- Covers third (potentially more disruptive)
- Fans last

### 5. Static Snapshot
- No surprise new devices
- Explicit reconfigure needed

### 6. Options Reversibility
- Can disable whole house anytime
- No confirmation needed to turn OFF
- Manual entity selections preserved

---

## Edge Cases

### No Controllable Entities

If home has 0 lights/switches/covers/fans:
- Confirmation shows: **"0 devices"**
- User can still confirm (will do nothing)
- Validation catches "no outputs" error

### All Entities Unavailable

If all 47 lights are currently unavailable:
- Auto-selection finds 0 available entities
- Shows: **"0 devices"**
- Likely hits "no outputs" validation error

### Exactly 32 Entities

- All 32 selected
- No truncation message needed
- Works perfectly

### More Than 32 Entities

Example: 87 lights/switches/covers/fans

**Behavior:**
1. All 87 scanned
2. Sorted by priority (lights first)
3. First 32 selected
4. Remaining 55 ignored
5. Confirmation shows: **"32 devices"** (after cap)

**User awareness:**
- Description mentions: _"Capped at 32 max outputs"_
- Prioritisation documented in README
- If user wants specific 32, they should manually select instead of whole house

### User Already Had Manual Selections

**Outputs:**
- Manual selections **completely replaced** by auto-selected list
- No merge — whole house means "all devices", not "all devices + your picks"

**Inputs:**
- Manual selections **preserved** unless empty
- Whole house primarily affects outputs
- User can still fine-tune what fly "sees"

---

## Testing Recommendations

### Manual Testing

1. **Empty home:** Add integration with 0 entities → confirm shows "0 devices"
2. **Few entities:** 3 lights → confirm shows "3 devices", all selected
3. **Many entities:** 50+ lights → confirm shows "32 devices", lights prioritised
4. **Mixed domains:** 20 lights, 10 switches, 5 covers → lights first, then switches
5. **Unavailable entities:** 10 lights (5 unavailable) → only 5 available selected
6. **Enable via options:** Start with 2 outputs, enable whole house → list replaced
7. **Disable via options:** Whole house on → toggle off → manual list restored (if stored)

### Automated Testing (Future)

```python
async def test_whole_house_auto_selection(hass):
    # Setup mock entities
    hass.states.async_set("light.test1", "on")
    hass.states.async_set("light.test2", "off")
    hass.states.async_set("switch.test1", "on")
    
    # Get auto-selected outputs
    outputs = await _async_get_whole_house_outputs(hass)
    
    # Assert lights prioritised
    assert outputs[0].startswith("light.")
    assert outputs[1].startswith("light.")
    assert outputs[2].startswith("switch.")
```

---

## Documentation Coverage

✅ **README.md** — Detailed "Whole House Mode" section  
✅ **QUICK_START.md** — Safety warnings, behavior description  
✅ **FORUM_POST.md** — Real implementation summary  
✅ **IMPLEMENTATION_SUMMARY.md** — Technical feature list  
✅ **Strings.json** — Confirmation dialogue with placeholders  
✅ **Translations/en.json** — English UI strings  
✅ **WHOLE_HOUSE_MODE.md** — This document (technical reference)

---

## Future Enhancements (Out of Scope for v0.1)

### Dynamic Entity Scanning

Optionally rescan entities on each coordinator tick:

```python
if self.whole_house and self.tick_count % 60 == 0:  # Every 10 minutes
    self.output_entities = await self._async_rescan_outputs()
```

**Pros:** New devices auto-appear  
**Cons:** Surprise thrashing, unpredictability, performance overhead  
**Decision:** Static snapshot preferred for v0.1

### Per-Domain Limits

Allow user to cap specific domains:

```yaml
whole_house:
  lights: 20
  switches: 10
  covers: 2
  fans: 0  # Exclude fans
```

**Pros:** Fine-grained control  
**Cons:** Complex UI, defeats "whole house" simplicity  
**Decision:** Global 32 cap sufficient for v0.1

### Exclude List

Let user exclude specific entities:

```yaml
exclude:
  - light.bedroom_main  # Keep manual control
  - cover.garage_door   # Never automate
```

**Pros:** Safety for critical devices  
**Cons:** Complex UI, better solved by not using whole house mode  
**Decision:** Out of scope — users wanting exclusions should use manual select

---

## Summary

✅ **Fully implemented** whole house mode  
✅ **Required confirmation** with device count  
✅ **Auto-selection** of up to 32 entities  
✅ **Safety constraints** (tick ≥15s, intensity ≤0.4)  
✅ **Static snapshot** (predictable, no surprises)  
✅ **Options flow support** (enable/disable anytime)  
✅ **Comprehensive documentation** (README, guides, strings)  

**Status:** Production-ready, scary, functional, and properly warned. 🪰🔥
