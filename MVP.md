# Fly House — Development Notes

Inspired by Google MaleCNS / chessfly / flyputer. Soft Vome CTA ([vome.io](https://vome.io), optional [fynd.vome.io](https://fynd.vome.io)).

## One-liner

HACS `fly_house`: HA sensors → tiny reservoir → lights/covers. "Let a fruit fly control your house."

## v1.0 (founding release)

- [x] `custom_components/fly_house` with config flow: 1–32 input sensors + 1–32 output entities
- [x] Interval tick (default 10s) → sensory hash → seeded sparse leaky reservoir (~256) → map channels to brightness / position / switch / number
- [x] Entities: `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`), `sensor.fly_house_brain`, `sensor.fly_house_hunger`, `sensor.fly_house_retina`
- [x] Services: `fly_house.poke`, `fly_house.feed`
- [x] Camera → ommatidia (Pillow luma downsample)
- [x] Hunger phototaxis (seek bright lights when hungry)
- [x] State persistence (hunger, mode, lifecycle across HA restarts)
- [x] Custom Lovelace card with animated fly + compound eye
- [x] Animated SVG assets (fly, brain sparks)
- [x] Whole house mode with scary confirmation
- [x] README disclaimer: connectome-inspired, not scientific; cite QuixiAI/MaleCNS CC-BY 4.0 for inspiration
- [x] `FORUM_POST.md` Community draft; link Vome for remote watching
- [x] `CONTRIBUTING.md` for founding project contributions
- [x] MIT `LICENSE`, `hacs.json`
- [x] **No** MaleCNS / torch / multi-GB weights in the integration package

## v2 exploration (optional — add-on path, not in HACS bundle)

Future possibilities (NOT in current integration):

- Swap toy matrix for MaleCNS subset / QuixiAI MaleCNS safetensors if size/runtime OK
- HF Space remote motor stream
- GPU acceleration for larger reservoirs
- Do **not** ship multi-GB weights inside the custom component

## Notes

- Integration path: lightweight, pure Python, HACS-installable
- Add-on path (future): heavy lifting, torch, GPU, MaleCNS weights
- `assets/` in repo (if present) may hold experimental metadata/parquets — excluded from integration runtime
- Keep the toy nature honest; preserve the founding exploratory spirit
