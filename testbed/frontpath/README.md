# FrontPath

Two LD2410 mmWave radars over BLE on an ESP32-C3, watching the walkway to the
front door: one pointing at the street, one at the door, nine energy gates
each. It publishes `sensor.path_person_position` in metres, which is what
HouseFly's looming pathway eats.

## What is here

- **`veml6040-twilight.yaml`** — the reference write-up of the colour work, as
  paste-in fragments.
- **`frontpath-rgb.yaml`** is what is actually deployed (it lives on the
  ESPHome dashboard, not here). It is an *overlay*: it includes `frontpath.yaml`
  unchanged as a package and uses `!remove` to drop the two TEMT6000 sensors,
  then adds the VEML6040 ones. All the radar logic stays in one place.
- **`frontpath-deployed-backup.yaml`** — a copy of `frontpath.yaml` as it was
  on the dashboard when the colour work went in, kept as a rollback.

## Two things worth knowing before touching the I2C

**`write_register()` and `read_register()` do not exist on a bus.** They are
methods on `i2c::I2CDevice`, the base class a *component* inherits when it owns
an address. A bare bus referenced by `id()` is an `i2c::I2CBus`, which has only
`write()` and `read()`. Calling the register helpers on it fails at compile
time with *"class esphome::i2c::IDFI2CBus has no member named write_register"*.

So a register read goes the long way: write the register pointer with the stop
condition suppressed, then read. The `false` in `bus->write(addr, &reg, 1,
false)` is the whole trick — with a stop in between, the VEML6040 forgets which
register was asked for.

**Changing the integration time makes the next reading stale.** The part needs
a full integration period before a new setting means anything, so a read taken
straight after a write returns the previous conversion. The auto-ranging code
therefore re-ranges at the *end* of a poll, so the next one is ten seconds away
and honest.

## Why colour at all

A path light wants to know whether the sun is going down. A lux threshold
cannot answer that — a dark cloud at two in the afternoon and civil twilight
look identical to it, which is why the TEMT6000 never gave a usable number.

At dusk the sun is below the horizon and the sky is lit along a long slant path
where ozone's Chappuis band absorbs the orange and red, so twilight goes
strongly blue. A cloud does nothing of the sort: cloud droplets are large
compared with the wavelength and scatter near-neutrally. So **B/R separates
sunset from weather**, in one number.

```
 clear midday        ~1.2 - 1.6
 overcast            ~1.0 - 1.3    dim, but NOT blue
 civil twilight      ~1.8 - 3.0    the blue hour
 sodium street lamp  ~0.3 - 0.6    this path's own lamp, once it is on
```

That last row is a warning as much as a calibration point: read the index
before switching the lights, or gate it on the lights being off.
