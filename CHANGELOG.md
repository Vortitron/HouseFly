# Changelog

All notable changes to HouseFly will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-09-18

### Added
- **Auto-registration of frontend card module**: The `housefly-card.js` is now automatically registered on integration setup. No manual Lovelace resource steps required!
- Card is served from `/fly_house/housefly-card.js` via static path registration
- Frontend module loads automatically via `add_extra_js_url`

### Changed
- Updated `CUSTOM_CARD_GUIDE.md` to reflect automatic installation (manual resource steps now legacy/optional)
- Updated `README.md` to reflect automatic card registration
- Registration is idempotent: safe with multiple config entries or reloads

### Fixed
- Users no longer need to manually add Lovelace resources after installation
- Card works immediately after install/restart with zero UI configuration

## [1.0.0] - 2026-09-17

### Initial Release
- Core fruit fly reservoir brain (256 neurons, pure Python)
- Config flow with input/output entity selection
- Hunger system with persistence across restarts
- Binary sensor (fly active state)
- Sensors (spikes, mode, brain, hunger, retina)
- Services: `fly_house.poke` and `fly_house.feed`
- Custom Lovelace card with animated fly, compound eye, brain sparks
- Visual assets (SVG animations)
- Whole house mode (danger zone)
- HACS integration support
