# Fly House — weekend meme MVP

Inspired by Google MaleCNS / chessfly / flyputer. Soft Vome CTA ([vome.io](https://vome.io), optional [fynd.vome.io](https://fynd.vome.io)).

## One-liner

HACS `fly_house`: HA sensors → tiny reservoir → lights/covers. "Let a fruit fly control your house."

## v1 (honest toy) — scaffolded locally

- [x] `custom_components/fly_house` with config flow: 1–8 input sensors + 1–8 output entities
- [x] Interval tick (default 10s) → sensory hash → seeded sparse leaky reservoir (~256) → map channels to brightness / position / switch / number
- [x] Entities: `binary_sensor.fly_house_active`, `sensor.fly_house_spikes`, `sensor.fly_house_mode` (`idle` / `wander` / `escape`)
- [x] Service `fly_house.poke`
- [x] README disclaimer: connectome-inspired, not scientific; cite QuixiAI/MaleCNS CC-BY 4.0 for inspiration
- [x] `FORUM_POST.md` Community draft; link Vome for remote watching
- [x] MIT `LICENSE`, `hacs.json`
- [x] **No** MaleCNS / torch / multi-GB weights in the integration package

## v2 (optional — add-on path, not in HACS bundle)

- Swap toy matrix for MaleCNS subset / QuixiAI MaleCNS safetensors if size/runtime OK (see local `assets/` for experiments only)
- HF Space remote motor stream
- Do **not** ship multi-GB weights inside the custom component

## Notes

- Local packaging under `/workspace/fly-house/` only — not a git clone of a remote product repo
- `assets/` may hold metadata parquets + fly-llm-hf (~271MB) and larger MaleCNS downloads for research; excluded from integration runtime
