# HouseFly v1.2 (manifest 0.2.0)

Weekend-meme bump: real compound eye from a Home Assistant camera, hungrier phototaxis, soft Vome peeks. Still not a real fly brain.

## Camera → ommatidia

- Optional `camera_entity` in config/options flow (EntitySelector, domain `camera`).
- Optional `vision_tick_interval` (default 30s): coordinator calls `camera.async_get_image(hass, entity_id, timeout=10, width=64, height=64)` and passes `image.content` bytes to the brain.
- Brain `_process_camera_image` now does real luminance downsample to 16×16 via **Pillow** (`RGB/any → L → resize`). Listed in `manifest.json` requirements.
- On `ImportError` / decode failure / missing camera / snapshot error → keep **lights + sun** synthesis (unchanged fallback).
- Between vision ticks, last good snapshot is reused (`vision_source`: `camera` / `camera_cached` / `lights_sun` / `none`), exposed on the retina sensor.

## Hunger phototaxis

- When hunger > 0.35, `_async_drive_outputs` biases channels for `light.*` outputs upward, stronger for currently brighter lights (seek-the-lamp behavior).

## Soft Vome CTAs (not a banner)

- README / FORUM_POST / QUICK_START: one-liner peeks at https://vome.io (+ optional https://fynd.vome.io).
- `housefly-card.js`: muted footer “Away? Peek via Vome →”.
- `strings.json` / translations: tiny optional nod in config help + camera field labels.

## Package / meta

- `manifest.json` version **0.2.0**, requirements `Pillow>=10.0.0`.
- Device model string bumped to “Leaky reservoir v0.2”.

## Not in this release

- No MaleCNS / torch weights, no multi-GB assets in the tarball.
- No cloud deploy; local tree only.

## Camera API note

Uses Home Assistant core helper:

```python
from homeassistant.components.camera import async_get_image
image = await async_get_image(hass, entity_id, timeout=10, width=64, height=64)
# image.content -> bytes (typically JPEG)
```

Signature verified against `homeassistant/components/camera/__init__.py` (dev). Failures are caught and logged at debug; fly keeps buzzing on synthesized vision.
