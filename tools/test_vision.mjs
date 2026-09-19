/**
 * Checks the visual front end against stimuli whose answer is known.
 *
 *   node tools/test_vision.mjs
 *
 * The claim being tested is not "it detects motion". It is the specific claim
 * the LPLC2 anatomy makes: that a cell built from four outward-facing branches
 * responds to something coming at it and to nothing else. So the interesting
 * cases here are the negatives -- receding, translating, flickering -- because
 * a detector that fires on those is a motion sensor wearing a fly costume.
 *
 * Stimuli are generated directly on the ommatidial grid, so nothing depends on
 * a browser, a canvas, or a camera.
 */

import { FlyEye, EYE_W, EYE_H } from '../custom_components/fly_house/www/housefly-vision.js';

const DT = 1 / 30;               // 30 fps, which is what a webcam gives
const results = [];

function check(name, passed, detail) {
  results.push(passed);
  console.log(`  ${passed ? 'PASS' : 'FAIL'}  ${name}  --  ${detail}`);
}

/* ------------------------------------------------------------------ stimuli */

/** A dark disc of angular radius `rad` (in grid samples) centred at (cx, cy). */
function disc(cx, cy, rad) {
  const g = new Float32Array(EYE_W * EYE_H);
  for (let y = 0; y < EYE_H; y++) {
    for (let x = 0; x < EYE_W; x++) {
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy);
      // A soft edge, because a hard one is an aliasing generator and a real
      // lens does not produce one.
      g[y * EYE_W + x] = 1 - 0.9 / (1 + Math.exp((d - rad) * 2.0));
    }
  }
  return g;
}

/** A drifting square-wave grating -- pure wide-field translation. */
function grating(phase, period = 6) {
  const g = new Float32Array(EYE_W * EYE_H);
  for (let y = 0; y < EYE_H; y++) {
    for (let x = 0; x < EYE_W; x++) {
      g[y * EYE_W + x] = 0.5 + 0.4 * Math.sign(Math.sin(((x - phase) / period) * Math.PI * 2));
    }
  }
  return g;
}

/**
 * A broadband "natural" texture: a dozen random sinusoids, so it has the spread
 * of spatial frequencies a real room has rather than the single frequency a
 * grating has. Deterministic, so the numbers in the comments stay true.
 */
let seed = 7;
const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const COMPONENTS = Array.from({ length: 12 }, () => ({
  fx: (rnd() - 0.5) * 1.2, fy: (rnd() - 0.5) * 1.2,
  ph: rnd() * 6.28, a: 0.10 + rnd() * 0.10,
}));

function texture(ox, oy) {
  const g = new Float32Array(EYE_W * EYE_H);
  for (let y = 0; y < EYE_H; y++) {
    for (let x = 0; x < EYE_W; x++) {
      let v = 0.5;
      for (const c of COMPONENTS) v += c.a * Math.sin((x - ox) * c.fx + (y - oy) * c.fy + c.ph);
      g[y * EYE_W + x] = Math.max(0, Math.min(1, v));
    }
  }
  return g;
}

/** Uniform field at a given level -- for flicker. */
function flat(level) {
  return new Float32Array(EYE_W * EYE_H).fill(level);
}

/* ---------------------------------------------------------------- protocols */

/**
 * Run a sequence of frames and return the peak response, ignoring the first
 * few frames while the adaptation state settles.
 */
function run(frames, { settle = 10 } = {}) {
  const eye = new FlyEye();
  let peak = 0;
  let peakAz = 0;
  let peakCell = 0;
  frames.forEach((grid, i) => {
    eye.sampleGrid(grid);
    const out = eye.step(DT);
    if (i >= settle && out.expansion > peak) {
      peak = out.expansion;
      peakAz = out.azimuth;
      peakCell = out.peak;
    }
  });
  return { peak, azimuth: peakAz, cell: peakCell };
}

/**
 * An object of real size L approaching at speed v, rendered as the angular
 * size a real approach produces: theta = 2*atan(L / 2r), so the disc's radius
 * on the eye goes as the physics does and not as a linear ramp.
 */
function approach({ from = 5.0, to = 0.4, speed = 1.0, size = 0.35,
                    cx = EYE_W / 2, cy = EYE_H / 2 } = {}) {
  // However many frames the approach actually takes. An earlier version of
  // this capped the loop at 60, so a stimulus labelled "5.0 m to 0.4 m" in
  // fact stopped at 3.0 m and every number derived from it was describing a
  // different experiment from the one named.
  const steps = Math.ceil(((from - to) / speed) / DT) + 2;
  const frames = [];
  // Hold still first so the adaptation state is settled on a static scene,
  // which is the situation a fly is actually in before something happens.
  const held = disc(cx, cy, angularRadius(from, size));
  for (let i = 0; i < 20; i++) frames.push(held);
  let r = from;
  for (let i = 0; i < steps && r > to; i++) {
    r -= speed * DT;
    frames.push(disc(cx, cy, angularRadius(Math.max(r, to), size)));
  }
  return frames;
}

/** Angular radius on the grid, in samples, for an object of size L at range r. */
function angularRadius(r, L) {
  const theta = 2 * Math.atan(L / (2 * r));          // radians, full angle
  const perSample = (60 * Math.PI) / 180 / EYE_W;    // FOV_X per sample
  return (theta / 2) / perSample;
}

/* -------------------------------------------------------------------- tests */

console.log('\nThe eye: LPLC2 from four outward-facing branches\n');

const looming = run(approach(), { settle: 20 });
check('something coming at it produces a response',
      looming.peak > 0.15,
      `peak expansion ${looming.peak.toFixed(3)}`);

// The same disc, played backwards. Identical images, identical contrast,
// identical speeds -- only the sign of the flow differs.
const recedeFrames = approach().slice().reverse();
const receding = run(recedeFrames, { settle: 20 });
check('the same thing going away produces almost nothing',
      receding.peak < looming.peak * 0.1,
      `receding ${receding.peak.toFixed(3)} vs looming ${looming.peak.toFixed(3)}`);

// Wide-field translation: the case the outward-minus-inward subtraction exists
// to reject. A fly that fled from this could not turn its own head.
const gratingFrames = [];
for (let i = 0; i < 80; i++) gratingFrames.push(grating(i * 0.9));
const translating = run(gratingFrames, { settle: 20 });
check('the whole world sliding past produces almost nothing',
      translating.peak < looming.peak * 0.1,
      `drifting grating ${translating.peak.toFixed(3)}`);

// A small object crossing the field. Some response is correct -- it does expand
// a little on the cells it passes over -- but it must not rival an approach.
const crossingFrames = [];
for (let i = 0; i < 20; i++) crossingFrames.push(disc(2, EYE_H / 2, 3));
for (let i = 0; i < 60; i++) crossingFrames.push(disc(2 + i * 0.5, EYE_H / 2, 3));
const crossing = run(crossingFrames, { settle: 20 });
check('something crossing in front of it is not an approach',
      crossing.peak < looming.peak * 0.35,
      `lateral pass ${crossing.peak.toFixed(3)}`);

// Whole-field brightness flicker: a light switching, a cloud, an AC-coupled
// camera. Strong temporal contrast with no motion at all.
const flickerFrames = [];
for (let i = 0; i < 80; i++) flickerFrames.push(flat(0.5 + 0.35 * Math.sin(i * 0.9)));
const flicker = run(flickerFrames, { settle: 20 });
check('a light turning on and off is not an approach',
      flicker.peak < looming.peak * 0.05,
      `full-field flicker ${flicker.peak.toFixed(4)}`);

// Static scene. Nothing should ever come out of this.
const staticFrames = [];
const scene = disc(10, 8, 4);
for (let i = 0; i < 60; i++) staticFrames.push(scene);
const still = run(staticFrames, { settle: 20 });
check('a scene that is not moving produces exactly nothing',
      still.peak < 1e-3,
      `static scene ${still.peak.toExponential(2)}`);

console.log('\nSelf-motion: a camera that moves is not a thing coming at you\n');

// The case that actually matters for a webcam, and the one a grating does not
// represent: a textured scene panning past, which is what someone picking up a
// laptop looks like. Before the self-motion gate this scored 0.92 against a
// nominal approach's 0.21 -- four times the response, for nothing at all.
const pan = run(Array.from({ length: 80 }, (_, i) => texture(i * 0.6, 0)), { settle: 20 });
check('a camera panning across a textured room produces nothing',
      pan.peak < 0.01,
      `textured pan ${pan.peak.toFixed(4)} vs nominal approach ${looming.peak.toFixed(3)}`);

const shaky = run(Array.from({ length: 80 }, (_, i) =>
  texture(i * 0.6 + Math.sin(i * 1.7) * 1.4, Math.sin(i * 2.3) * 1.1)), { settle: 20 });
check('nor does a hand-held camera wandering about',
      shaky.peak < 0.02,
      `pan with shake ${shaky.peak.toFixed(4)}`);

// A textured room that is simply *there*. The commonest thing a webcam sees.
const room = run(Array.from({ length: 80 }, () => texture(0, 0)), { settle: 20 });
check('a room that is not moving produces exactly nothing',
      room.peak < 1e-4,
      `static texture ${room.peak.toExponential(2)}`);

// The gate must not have bought its rejection by suppressing real approaches:
// the looming checks above already ran through it, so this only confirms the
// gate stayed open for them.
check('and the gate stays open for a real approach',
      looming.peak > 0.15,
      `approach still ${looming.peak.toFixed(3)} with the gate in place`);

console.log('\nClutter: a real room is not a plain wall\n');

// Every stimulus above puts the object against a blank background, which is
// the easy case and not the one a webcam sees. Here the same approach happens
// in front of a textured room, and the object occludes it.
function texturedApproach(opts = {}) {
  const { from = 5.0, to = 0.4, speed = 1.0, size = 0.35 } = opts;
  const frame = (radius) => {
    const room = texture(0, 0);
    const g = new Float32Array(EYE_W * EYE_H);
    for (let y = 0; y < EYE_H; y++) {
      for (let x = 0; x < EYE_W; x++) {
        const d = Math.hypot(x + 0.5 - EYE_W / 2, y + 0.5 - EYE_H / 2);
        const occluder = 1 - 0.95 / (1 + Math.exp((d - radius) * 2.0));
        g[y * EYE_W + x] = room[y * EYE_W + x] * occluder;
      }
    }
    return g;
  };
  const frames = [];
  for (let i = 0; i < 20; i++) frames.push(frame(angularRadius(from, size)));
  let r = from;
  const steps = Math.ceil(((from - to) / speed) / DT) + 2;
  for (let i = 0; i < steps && r > to; i++) {
    r -= speed * DT;
    frames.push(frame(angularRadius(Math.max(r, to), size)));
  }
  return frames;
}

const cluttered = run(texturedApproach(), { settle: 20 });
check('an approach in a cluttered room still clears the escape threshold',
      cluttered.peak > 0.1,
      `cluttered ${cluttered.peak.toFixed(3)} against a threshold of about 0.1`);
check('though clutter costs it a great deal of sensitivity',
      cluttered.peak < looming.peak * 0.2,
      `${(looming.peak / cluttered.peak).toFixed(0)}x weaker than the same approach on a plain wall`);

const clutteredFar = run(texturedApproach({ from: 6.0, to: 4.0 }), { settle: 20 });
check('and a distant one in clutter still does not fire',
      clutteredFar.peak < 0.01,
      `distant cluttered approach ${clutteredFar.peak.toExponential(1)}`);

console.log('\nRetinotopy: which cell fires says where the threat is\n');

// LPLC2 is retinotopic, so the population tells you *where*. Approach from the
// left and from the right and check the reported azimuth follows.
const left = run(approach({ cx: EYE_W * 0.2 }), { settle: 20 });
const right = run(approach({ cx: EYE_W * 0.8 }), { settle: 20 });
check('a threat on the left is reported on the left',
      left.azimuth < -0.1,
      `azimuth ${(left.azimuth * 180 / Math.PI).toFixed(1)} degrees`);
check('a threat on the right is reported on the right',
      right.azimuth > 0.1,
      `azimuth ${(right.azimuth * 180 / Math.PI).toFixed(1)} degrees`);

console.log('\nMagnitude: the r-squared survives the optics\n');

// The whole point of the pathway. Same object, same closing speed, sampled at
// different ranges -- the response must grow the way theta-dot does, or the
// eye has thrown away what the ranging sensor was careful to keep.
const near = run(approach({ from: 1.2, to: 0.4, speed: 1.0 }), { settle: 20 });
const far = run(approach({ from: 6.0, to: 4.0, speed: 1.0 }), { settle: 20 });
check('the same approach counts for more close in',
      near.peak > far.peak * 3,
      `at 1.2-0.4 m ${near.peak.toFixed(3)}, at 6.0-4.0 m ${far.peak.toFixed(3)}`);
check('a distant approach stays under the escape threshold',
      far.peak < 0.1,
      `far approach ${far.peak.toFixed(4)}, threshold is about 0.1`);
check('a close approach clears it comfortably',
      near.peak > 0.3,
      `close approach ${near.peak.toFixed(3)}`);

const passed = results.filter(Boolean).length;
console.log(`\n${passed}/${results.length} vision checks passed\n`);
process.exit(passed === results.length ? 0 : 1);
