# Contributing to HouseFly

Thank you for your interest in contributing to HouseFly! 🪰

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md). We are committed to providing a welcoming and inclusive environment for all contributors.

## Getting Started

### Development Setup

1. **Fork the repository** on GitHub
2. **Clone your fork:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/HouseFly.git
   cd HouseFly
   ```
3. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Install in Home Assistant:**
   - Copy `custom_components/fly_house/` to your HA `config/custom_components/` folder
   - Restart Home Assistant
   - Add the integration via UI (Settings → Devices & services → Add integration)

### Development Environment

HouseFly is pure Python with minimal dependencies:

- **Python 3.11+** (Home Assistant 2024.1+)
- **Pillow ≥10.0.0** (optional, for camera → ommatidia)
- **No torch, numpy, or heavy ML libraries**

## How to Contribute

### Bug Reports

Found a bug? Please [open an issue](https://github.com/Vortitron/HouseFly/issues/new?template=bug_report.md) with:

- **Clear title** describing the bug
- **Steps to reproduce**
- **Expected vs actual behaviour**
- **Logs** from Home Assistant (Settings → System → Logs, filter by `fly_house`)
- **Environment:** HA version, Python version, installation method (HACS/manual)

### Feature Requests

Have an idea? [Open a feature request](https://github.com/Vortitron/HouseFly/issues/new?template=feature_request.md) describing:

- **What** you want to add
- **Why** it's useful
- **How** it might work (optional)

Keep in mind HouseFly's philosophy:
- ✅ Pure Python, lightweight, weekend-meme vibes
- ✅ Fruit-fly-inspired sensorimotor dynamics
- ❌ NOT an LLM chatbot or voice assistant
- ❌ Avoid heavy dependencies (torch, numpy, multi-GB downloads)

### Pull Requests

Ready to code? Great! Here's the workflow:

1. **Check existing issues/PRs** to avoid duplicate work
2. **Open an issue first** for large changes (discuss before coding)
3. **Create a feature branch** from `main`
4. **Make your changes:**
   - Follow existing code style (tabs, British English in comments)
   - Add docstrings for new functions/classes
   - Keep functions focused and reusable
   - Avoid `export let` or dynamic imports (ES modules only)
   - Add assertions for critical assumptions
5. **Test your changes:**
   - Install in Home Assistant and test manually
   - Check logs for errors
   - Test with different entity types (light, switch, cover, number)
   - Verify the fly behaves correctly (idle → wander → escape transitions)
6. **Update documentation** if needed (README, guides)
7. **Commit with clear messages:**
   ```
   feat: add phototaxis intensity parameter
   fix: hunger overflow when feeding during escape mode
   docs: clarify whole house mode safety warnings
   ```
8. **Push and open a PR** against `main`
9. **Respond to review feedback**

## Code Style

### Python

- **Tabs, not spaces** (per repo conventions)
- **British English** in comments/docs where possible (`colour`, `behaviour`)
- **Docstrings** for public functions:
  ```python
  def calculate_phototaxis(ommatidia: list[float], hunger: float) -> list[float]:
      """Calculate phototaxis bias vector from visual field and hunger state.
      
      Args:
          ommatidia: 256-element list of brightness values (0.0–1.0)
          hunger: Hunger level (0–100%)
      
      Returns:
          16-element bias vector for motor channels
      """
  ```
- **Type hints** for new code (gradual adoption)
- **Error handling:** Log warnings/errors, don't crash the coordinator
- **Assertions** for internal invariants:
  ```python
  assert 0 <= hunger <= 100, f"Hunger out of range: {hunger}"
  ```

### JavaScript (Custom Card)

- **Vanilla JS** — no frameworks, no build step
- **ES6+ syntax** (classes, arrow functions, template literals)
- **Shadow DOM** for style isolation
- **requestAnimationFrame** for animations
- **Home Assistant design tokens** for theming (`--ha-card-background`, `--primary-color`)
- **Descriptive variable names** (`ommatidia`, not `om`)

## Testing

### Manual Testing Checklist

Before submitting a PR, test:

- [ ] Integration loads without errors (check HA logs)
- [ ] Config flow works (add/reconfigure integration)
- [ ] Sensors update correctly (`binary_sensor.fly_house_active`, `sensor.fly_house_*`)
- [ ] Services work (`fly_house.poke`, `fly_house.feed`)
- [ ] Mode transitions happen (`idle` → `wander` → `escape`)
- [ ] Hunger rises over time, decreases on feed
- [ ] Output entities respond (light brightness, switch toggle, etc.)
- [ ] Custom card loads and animates
- [ ] Card buttons work (Poke/Feed)
- [ ] Ommatidia grid updates (turn lights on/off)

### Test with Edge Cases

- [ ] Zero inputs (no sensors selected)
- [ ] Zero outputs (no controllable entities)
- [ ] Mixed output types (light + switch + cover + number)
- [ ] Whole house mode (if brave!)
- [ ] Camera entity selected for vision (optional)
- [ ] Hunger at 0%, 50%, 100%
- [ ] Rapid poking (spam the Poke button)

## Documentation

When adding features, update:

- **README.md** — user-facing feature description
- **CUSTOM_CARD_GUIDE.md** — if card changes
- **LOVELACE_EXAMPLE.yaml** — if new sensors/services
- **Docstrings** — inline code documentation

Keep documentation clear, concise, and fun (but informative).

## Project Structure

```
HouseFly/
├── custom_components/fly_house/
│   ├── __init__.py          # Integration setup, services
│   ├── config_flow.py       # UI configuration flow
│   ├── coordinator.py       # Data update coordinator
│   ├── brain.py             # Reservoir brain logic
│   ├── sensor.py            # Sensor entities
│   ├── binary_sensor.py     # Binary sensor entities
│   ├── const.py             # Constants
│   ├── manifest.json        # Integration metadata
│   └── www/
│       └── housefly-card.js # Custom Lovelace card
├── README.md                # Main documentation
├── CONTRIBUTING.md          # This file
├── CUSTOM_CARD_GUIDE.md     # Card installation guide
├── LOVELACE_EXAMPLE.yaml    # Dashboard examples
├── LICENSE                  # MIT licence
└── .github/
    ├── ISSUE_TEMPLATE/      # Bug/feature templates
    └── workflows/           # CI (optional)
```

## Release Process

(For maintainers)

1. **Update version** in `manifest.json`
2. **Update CHANGELOG** (if we add one)
3. **Tag release:** `git tag v0.2.1 && git push --tags`
4. **HACS auto-detects** new releases via tags
5. **Forum post** (optional, for major versions)

## Philosophy

HouseFly is a **weekend meme** with serious attention to detail:

- **Toy dynamical system**, not production AI
- **Pure Python**, no heavy ML dependencies
- **Fruit-fly-inspired**, not neuroscience-accurate
- **Fun and chaotic**, but safe (with proper safety warnings)
- **Open source**, MIT licensed, community-driven

We value:
- 🎯 **Clarity** over cleverness
- 🪶 **Lightweight** over feature-bloat
- 🧪 **Experimentation** over perfection
- 🤝 **Kindness** in code reviews

## Questions?

- **Issues:** [GitHub Issues](https://github.com/Vortitron/HouseFly/issues)
- **Discussions:** [GitHub Discussions](https://github.com/Vortitron/HouseFly/discussions) (if enabled)
- **Forum:** [Home Assistant Community](https://community.home-assistant.io) (search "HouseFly")

Thank you for making HouseFly better! 🪰✨
