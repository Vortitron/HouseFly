# Contributing to HouseFly

Thank you for your interest in HouseFly! This project started as an experiment in mapping dynamical systems onto home automation, and contributions that preserve that founding spirit are welcome. 🪰

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md). We are committed to providing a welcoming and inclusive environment for all contributors.

## Philosophy

HouseFly is **playful but intentional** — it's a toy dynamical system done with care:

- **Not a gag:** The fruit fly framing is fun, but the implementation is deliberate
- **Exploratory science:** We're exploring alternative patterns in home automation
- **Honest toy:** Clear disclaimers about what it is and isn't (not real neuroscience)
- **Pure Python core:** No numpy/torch dependencies in the integration (keep it lightweight)
- **Whole-house danger humour:** Embrace the chaos, but with real safety guardrails

We value:
- 🎯 **Clarity** over cleverness
- 🪶 **Lightweight** over feature-bloat
- 🧪 **Experimentation** over perfection
- 🤝 **Kindness** in code reviews

## What we're looking for

Good contributions to HouseFly:

✅ **Richer fly biology** — hunger variants, circadian rhythms, other fruit fly behaviours  
✅ **Better vision processing** — improved ommatidia synthesis, optical flow, loom detection  
✅ **State persistence improvements** — smarter storage, migration paths  
✅ **Visual/UX polish** — better cards, animations, dashboards that show the organism  
✅ **Documentation clarity** — help users understand what they're building  
✅ **Safety improvements** — better guardrails for whole house mode, intensity limits  
✅ **Testing** — actual Home Assistant integration tests, real hardware validation

## What we're NOT looking for

❌ **Adding torch/numpy to the core** — keep the integration lightweight (add-on path for heavy stuff)  
❌ **LLM chatbot features** — fruit flies don't have language; this is sensorimotor, not conversational  
❌ **Removing the science disclaimer** — stay honest about the toy nature  
❌ **Excessive enterprise-ification** — this is an experiment, not a SaaS product  
❌ **Removing safety warnings** — whole house mode IS dangerous; keep the scary dialogues

---

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

---

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
- ✅ Pure Python, lightweight, exploratory dynamical systems
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
   - Test hunger persistence (restart HA, verify state survives)
   - Test camera ommatidia (if camera entity selected)
6. **Update documentation** if needed (README, guides)
7. **Commit with clear messages:**
   ```
   feat: add phototaxis intensity parameter
   fix: hunger overflow when feeding during escape mode
   docs: clarify whole house mode safety warnings
   ```
8. **Push and open a PR** against `main`
9. **Respond to review feedback**

---

## Code Style

### Python

- **Tabs, not spaces** (per repo conventions)
- **British English** in comments/docs where possible (`colour`, `behaviour`)
- **Clear variable names** — `hunger` not `h`, `ommatidia_grid` not `og`
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

---

## Testing

### Manual Testing Checklist

Before submitting a PR, test:

- [ ] Integration loads without errors (check HA logs)
- [ ] Config flow works (add/reconfigure integration)
- [ ] Sensors update correctly (`binary_sensor.fly_house_active`, `sensor.fly_house_*`)
- [ ] Services work (`fly_house.poke`, `fly_house.feed`)
- [ ] Mode transitions happen (`idle` → `wander` → `escape`)
- [ ] Hunger rises over time, decreases on feed
- [ ] **State persistence** — restart HA, verify hunger/mode/lifecycle survives
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

---

## Documentation

When adding features, update:

- **README.md** — user-facing feature description
- **CUSTOM_CARD_GUIDE.md** — if card changes
- **LOVELACE_EXAMPLE.yaml** — if new sensors/services
- **Docstrings** — inline code documentation

Keep documentation clear, concise, and fun (but informative).

---

## Science Honesty

Maintain the honest disclaimer:

- **DO** say "toy dynamical system"
- **DO** say "inspired by fruit fly biology"
- **DO** cite MaleCNS / fly-llm for inspiration
- **DON'T** claim "real neuroscience"
- **DON'T** claim "actual Drosophila connectome" (we're using a seeded toy matrix)
- **DON'T** remove the "comedic and superficial" language

---

## Safety First

If your change increases chaos potential:

- Add warnings to the config flow
- Update whole house mode documentation
- Test with intensity limits
- Consider adding new safety caps

---

## Project Structure

```
HouseFly/
├── custom_components/fly_house/
│   ├── __init__.py          # Integration setup, services
│   ├── config_flow.py       # UI configuration flow
│   ├── coordinator.py       # Data update coordinator (+ state persistence)
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
    ├── PULL_REQUEST_TEMPLATE.md
    └── workflows/           # CI (optional)
```

---

## Release Process

(For maintainers)

1. **Update version** in `manifest.json`
2. **Update CHANGELOG** (if we add one)
3. **Tag release:** `git tag v1.0.0 && git push --tags`
4. **HACS auto-detects** new releases via tags
5. **Forum post** (optional, for major versions)

---

## PR Process

1. Open a PR with clear description of what changed and why
2. Reference any related issues
3. Include testing notes ("tested with 3 Philips Hue bulbs + ESP32 camera")
4. Be patient — maintainers test PRs with real hardware before merging

---

## Questions?

- **Issues:** [GitHub Issues](https://github.com/Vortitron/HouseFly/issues)
- **Discussions:** [GitHub Discussions](https://github.com/Vortitron/HouseFly/discussions) (if enabled)
- **Forum:** [Home Assistant Community](https://community.home-assistant.io) (search "HouseFly")

---

**Welcome to the experiment. Let's see where this fly takes us.** 🪰⚡
