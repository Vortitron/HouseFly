/**
 * housefly-vision -- a visual front end for the looming pathway.
 *
 * HouseFly's escape response is real: LPLC2 drives DNp09/10/11 through measured
 * synapses, and theta-dot = v/r^2 decides whether it fires. What it never had
 * was an eye. Looming arrived as a number computed from a ranging sensor, which
 * is honest but is not how the animal does it -- a fly computes expansion from
 * photons, in the optic lobe, before anything central hears about it.
 *
 * This is that stage, and it is deliberately not a generic "motion detector".
 * It is the published circuit, in order:
 *
 *   photoreceptors -> lamina (temporal high-pass) -> T4/T5 (Hassenstein-Reichardt
 *   elementary motion detectors, four directions) -> LPLC2 (radial outward
 *   pooling over four lobula-plate layers) -> a single expansion signal.
 *
 * The part that matters is the LPLC2 stage. Klapoetke et al. (2017, Nature 551)
 * showed that each LPLC2 cell has four dendritic branches, one in each of the
 * four direction-selective layers of the lobula plate, and that each branch is
 * offset so it samples motion pointing *away* from that cell's receptive-field
 * centre. A cell is therefore built to respond to an object expanding on its own
 * patch of sky, and to nothing else. That single piece of anatomy is what makes
 * the difference between a fly and a burglar alarm.
 *
 * Two consequences fall straight out of it, and both are tested in
 * tools/test_vision.mjs rather than asserted here:
 *
 *   * Receding produces nothing. The flow is inward, the branches want outward.
 *   * Translation produces nothing. This takes two mechanisms, not one. Within
 *     a receptive field, half of uniform flow points outward and half points
 *     inward, so the outward and inward pools cancel -- but only for flow that
 *     is spatially uniform. Measured against a drifting square-wave grating,
 *     whose motion energy sits on the edges and nowhere else, that symmetry
 *     argument alone left a response larger than an actual approach.
 *
 *     So the field-average motion vector is subtracted from every sample before
 *     it is pooled, which is what the lobula plate intrinsic (LPi) neurons do:
 *     they are wide-field, they pool a whole direction-selective layer, and they
 *     inhibit the layer of opposite preference. Radial flow averages to nearly
 *     zero, so an approach passes through it untouched; uniform flow averages to
 *     itself and cancels. This is why a fly can turn its own head without
 *     fleeing from the optic flow it just created.
 *
 * Everything runs in the viewer's browser on a downsampled grid. The only thing
 * that leaves the page is one number for expansion and one for where it was --
 * no frames, no images, nothing that could reconstruct the picture.
 */

/* A Drosophila eye has roughly 750 ommatidia with an interommatidial angle of
   about 5 degrees. 32 x 24 = 768 samples is not an approximation of that
   number, it is that number, and it is also small enough that the whole
   pipeline costs well under a millisecond per frame. */
export const EYE_W = 32;
export const EYE_H = 24;

/* LPLC2 cells, per hemisphere, in the hemibrain reconstruction: 85 in our data
   pack, around 65 in the published counts. A 9 x 7 grid of receptive fields is
   63, which tiles the eye at the right coarseness -- each cell's field is tens
   of degrees across, not a pixel. */
export const CELLS_X = 9;
export const CELLS_Y = 7;
export const CELL_COUNT = CELLS_X * CELLS_Y;

/* Field of view, radians. A fly sees very nearly everything; a webcam sees
   about 60 degrees. The azimuth reported for a threat is in the *camera's*
   frame, so this is the camera's figure and not the animal's. */
export const FOV_X = (60 * Math.PI) / 180;
export const FOV_Y = (45 * Math.PI) / 180;

/* Time constants, seconds.
   TAU_ADAPT  photoreceptor/lamina adaptation. Long enough that a static scene
              fades to nothing, short enough to track a changing one.
   TAU_DELAY  the delay arm of the correlator. This sets which image speeds the
              detector is tuned to; ~80 ms is in the range measured for T4/T5. */
const TAU_ADAPT = 0.40;
const TAU_DELAY = 0.08;

/* How long a cell's response is integrated before it counts, seconds.
   A looming object drives the same cell for as long as it is approaching; a
   textured scene panning past drives whichever cell the texture currently
   favours, for a frame or two, at random. Taking the peak over 63 cells and 60
   frames without this made the max of that noise -- a camera panning across a
   room scored fourteen times an actual approach. 120 ms is also roughly the
   integration DNp09 does before it commits, which is why a fly can be startled
   by a hand but not by wallpaper. */
const TAU_CELL = 0.12;

/* Receptive-field radius of one LPLC2 cell, in grid samples. About 8 samples on
   a 32-wide eye is ~15 degrees of half-width, so the fields overlap heavily --
   as they do in the animal, where a looming object is seen by many cells. */
const RF_RADIUS = 5.0;

/* Converts the normalised population response into the units circuits.py uses
   for `looming`. Calibrated in tools/test_vision.mjs against a synthetic disc
   expanding at a known rate, so that an object closing the way a hand closes on
   a fly lands near 1.0 -- comfortably over the escape threshold, which sits
   around 0.1 and is enforced by the brain rather than here. */
export const VISION_GAIN = 2.6;

const EPS = 1e-6;

/* Contrast floor for the normalisation. The correlator's output is a product of
   two contrast terms, so it scales as contrast squared and dividing by the
   field's mean square restores contrast invariance -- which is what LPLC2 shows
   in vivo. Doing that with no floor means a nearly blank field divides a small
   number by a smaller one: an unlit room produced responses forty times an
   actual approach. The floor is the sensor noise the division must not amplify,
   and 2% contrast is about what a webcam gives you in the dark. */
const CONTRAST_FLOOR = 0.02;

/* Coherence above which the field's motion is taken to be the camera moving
   rather than something moving in front of it.

   A fly suppresses its own looming responses during a saccade, and it can,
   because a turn produces flow that is wide-field and all one direction while
   an approach produces flow that is radial. Those two are not similar
   quantities and do not need a careful threshold to separate: measured over the
   stimuli in tools/test_vision.mjs, an approach scores 0.000 and a camera
   panning across a textured room scores 0.76 to 0.84. The limit below sits in
   the empty gap between them with a factor of two of margin on each side.

   Without this the eye is unusable on anything hand-held. A panning camera
   scored 0.92 against a nominal approach's 0.21 -- four times the response, for
   nothing happening at all -- and no choice of population read-out fixed it:
   peak cell, mean of the top three, top five, peak-plus-neighbours and the
   whole-population mean were all measured, and every one of them preferred the
   pan. It is not a read-out problem, it is a self-motion problem. */
const COHERENCE_LIMIT = 0.40;

function gridIndex(x, y) {
  return y * EYE_W + x;
}

/**
 * One eye. Feed it frames; it gives you expansion and where the expansion was.
 */
export class FlyEye {
  constructor() {
    const n = EYE_W * EYE_H;
    this.lum = new Float32Array(n);      // current, after optics
    this.slow = new Float32Array(n);     // adaptation state (lamina)
    this.hp = new Float32Array(n);       // high-passed contrast
    this.delayed = new Float32Array(n);  // the correlator's delay arm
    this.mx = new Float32Array(n);       // opponent horizontal motion, + is right
    this.my = new Float32Array(n);       // opponent vertical motion, + is down
    // The four direction-selective layers of the lobula plate, which is what
    // LPLC2's four dendritic branches actually read.
    this.right = new Float32Array(n);
    this.left = new Float32Array(n);
    this.down = new Float32Array(n);
    this.up = new Float32Array(n);
    this.cells = new Float32Array(CELL_COUNT);       // integrated, what is reported
    this.instant = new Float32Array(CELL_COUNT);    // this frame only
    this.primed = false;

    // Precompute each cell's pooling weights once. Every frame after this is
    // multiply-accumulate over a fixed list, which is what keeps it cheap.
    this.pool = [];
    for (let cy = 0; cy < CELLS_Y; cy++) {
      for (let cx = 0; cx < CELLS_X; cx++) {
        const centreX = ((cx + 0.5) / CELLS_X) * EYE_W;
        const centreY = ((cy + 0.5) / CELLS_Y) * EYE_H;
        const taps = [];
        let total = 0;
        const r0 = Math.ceil(RF_RADIUS * 1.6);
        for (let y = Math.max(0, Math.floor(centreY - r0)); y < Math.min(EYE_H, centreY + r0); y++) {
          for (let x = Math.max(0, Math.floor(centreX - r0)); x < Math.min(EYE_W, centreX + r0); x++) {
            const dx = x + 0.5 - centreX;
            const dy = y + 0.5 - centreY;
            const r = Math.hypot(dx, dy);
            if (r < 0.75 || r > r0) continue;
            const g = Math.exp(-(r * r) / (2 * RF_RADIUS * RF_RADIUS));
            // The outward unit vector at this point of the receptive field.
            // These four numbers *are* the four dendritic branches: how much
            // this sample contributes to the cell through the rightward,
            // leftward, downward and upward layer respectively.
            taps.push({ i: gridIndex(x, y), g, ux: dx / r, uy: dy / r });
            total += g;
          }
        }
        this.pool.push({
          taps,
          total: total || 1,
          azimuth: (centreX / EYE_W - 0.5) * FOV_X,
          elevation: (centreY / EYE_H - 0.5) * FOV_Y,
          x: centreX / EYE_W,
          y: centreY / EYE_H,
        });
      }
    }
  }

  /**
   * Sample a frame into the eye. `pixels` is RGBA from getImageData at any
   * resolution; it is box-averaged down to the ommatidial grid.
   */
  sample(pixels, width, height) {
    const acc = new Float32Array(EYE_W * EYE_H);
    const count = new Float32Array(EYE_W * EYE_H);
    for (let y = 0; y < height; y++) {
      const gy = Math.min(EYE_H - 1, (y * EYE_H / height) | 0);
      for (let x = 0; x < width; x++) {
        const gx = Math.min(EYE_W - 1, (x * EYE_W / width) | 0);
        const p = (y * width + x) * 4;
        // Rec. 601 luma. Flies are not trichromats in this sense at all, but
        // the point here is a single achromatic contrast channel, which is what
        // the motion pathway actually uses -- L1/L2 are fed by R1-R6, which are
        // all the same broad-spectrum receptor.
        const lum = 0.299 * pixels[p] + 0.587 * pixels[p + 1] + 0.114 * pixels[p + 2];
        const gi = gy * EYE_W + gx;
        acc[gi] += lum;
        count[gi] += 1;
      }
    }
    for (let i = 0; i < acc.length; i++) acc[i] = count[i] ? acc[i] / (count[i] * 255) : 0;
    this._optics(acc);
  }

  /** Feed an already-downsampled grid of luminances in 0..1. For tests. */
  sampleGrid(grid) {
    this._optics(grid);
  }

  /* The ommatidial acceptance function: each ommatidium sees a blurred cone,
     not a point. A separable 1-2-1 kernel is the cheapest honest stand-in, and
     without it the correlator picks up aliasing and calls it motion. */
  _optics(grid) {
    const tmp = new Float32Array(EYE_W * EYE_H);
    for (let y = 0; y < EYE_H; y++) {
      for (let x = 0; x < EYE_W; x++) {
        const l = grid[gridIndex(Math.max(0, x - 1), y)];
        const c = grid[gridIndex(x, y)];
        const r = grid[gridIndex(Math.min(EYE_W - 1, x + 1), y)];
        tmp[gridIndex(x, y)] = (l + 2 * c + r) / 4;
      }
    }
    for (let x = 0; x < EYE_W; x++) {
      for (let y = 0; y < EYE_H; y++) {
        const u = tmp[gridIndex(x, Math.max(0, y - 1))];
        const c = tmp[gridIndex(x, y)];
        const d = tmp[gridIndex(x, Math.min(EYE_H - 1, y + 1))];
        this.lum[gridIndex(x, y)] = (u + 2 * c + d) / 4;
      }
    }
  }

  /**
   * Advance the model by `dt` seconds using whatever was last sampled.
   * Returns { expansion, azimuth, elevation, cells, contrast }.
   */
  step(dt) {
    const n = EYE_W * EYE_H;
    if (!this.primed) {
      this.slow.set(this.lum);
      this.delayed.fill(0);
      this.primed = true;
      return this._quiet();
    }
    const aAdapt = 1 - Math.exp(-dt / TAU_ADAPT);
    const aDelay = 1 - Math.exp(-dt / TAU_DELAY);
    const aCell = 1 - Math.exp(-dt / TAU_CELL);

    // Lamina: subtract the slowly adapting mean. A scene that stops moving
    // stops existing, which is exactly what a fly's motion pathway does.
    let rms = 0;
    for (let i = 0; i < n; i++) {
      this.slow[i] += (this.lum[i] - this.slow[i]) * aAdapt;
      const hp = this.lum[i] - this.slow[i];
      this.hp[i] = hp;
      rms += hp * hp;
    }
    rms = Math.sqrt(rms / n);

    // T4/T5: a Hassenstein-Reichardt correlator between each sample and its
    // neighbour, one arm delayed. The subtraction of the mirrored product is
    // the opponency that happens in the lobula plate, and it is what makes the
    // output a signed direction rather than merely "something changed".
    const invDt = 1 / Math.max(dt, EPS);
    for (let y = 0; y < EYE_H; y++) {
      for (let x = 0; x < EYE_W; x++) {
        const i = gridIndex(x, y);
        const ix = x < EYE_W - 1 ? i + 1 : i;
        const iy = y < EYE_H - 1 ? i + EYE_W : i;
        this.mx[i] = (this.delayed[i] * this.hp[ix] - this.delayed[ix] * this.hp[i]) * invDt;
        this.my[i] = (this.delayed[i] * this.hp[iy] - this.delayed[iy] * this.hp[i]) * invDt;
      }
    }
    for (let i = 0; i < n; i++) {
      this.delayed[i] += (this.hp[i] - this.delayed[i]) * aDelay;
    }

    // Self-motion. How much of the field's motion is one shared vector: high
    // when the camera moved, near zero when something moved in front of it,
    // because radial flow cancels in the vector sum while still being there in
    // the magnitude sum.
    let sumX = 0, sumY = 0, sumMag = 0;
    for (let i = 0; i < n; i++) {
      sumX += this.mx[i];
      sumY += this.my[i];
      sumMag += Math.hypot(this.mx[i], this.my[i]);
    }
    const coherence = sumMag > EPS ? Math.hypot(sumX, sumY) / sumMag : 0;
    const selfMotionGate = Math.max(0, 1 - coherence / COHERENCE_LIMIT);

    // LPi. The lobula plate's intrinsic neurons are wide-field and they
    // inhibit the layer of *opposite* preferred direction, so the right model
    // is one subtraction per layer rather than one vector subtraction over all
    // of them. Split the opponent signals into the four rectified layers first.
    for (let i = 0; i < n; i++) {
      const mxi = this.mx[i];
      const myi = this.my[i];
      this.right[i] = mxi > 0 ? mxi : 0;
      this.left[i] = mxi < 0 ? -mxi : 0;
      this.down[i] = myi > 0 ? myi : 0;
      this.up[i] = myi < 0 ? -myi : 0;
    }
    // Then take each layer's own field average away from it. This is the step
    // that separates an approach from the world going past: under translation
    // one layer is active everywhere, so its average is most of its signal and
    // almost nothing survives. Under expansion each layer is active in its own
    // quadrant and quiet elsewhere, so its average is small and the local
    // response comes through.
    for (const layer of [this.right, this.left, this.down, this.up]) {
      let mean = 0;
      for (let i = 0; i < n; i++) mean += layer[i];
      mean /= n;
      for (let i = 0; i < n; i++) {
        const v = layer[i] - mean;
        layer[i] = v > 0 ? v : 0;
      }
    }

    // LPLC2, and this is the step that does the work.
    //
    // The four branches are not summed. Klapoetke et al. showed the cell needs
    // all four of them driven at once -- it is a coincidence detector across
    // directions, and that is the whole reason it is selective for looming
    // rather than merely for motion. Only a radially expanding edge drives
    // rightward motion on the right of a receptive field, leftward on the left,
    // downward below and upward above, all in the same moment. Anything
    // translating drives exactly one of the four, however fast and however
    // high-contrast it is.
    //
    // Summing them instead was tried first and it does not work: a drifting
    // grating scored nine times an actual approach, and a disc crossing the
    // view scored thirty times, because a big number in one branch carried the
    // sum on its own. A geometric mean cannot be carried by one term -- if any
    // branch is silent the product is zero.
    let best = 0;
    let bestCell = 0;
    for (let c = 0; c < this.pool.length; c++) {
      const { taps, total } = this.pool[c];
      // Outward pool per branch, and the same four read with the geometry
      // flipped, which is what an object shrinking in the field looks like.
      let oR = 0, oL = 0, oD = 0, oU = 0;
      let iR = 0, iL = 0, iD = 0, iU = 0;
      let energy = 0;
      for (let t = 0; t < taps.length; t++) {
        const { i, g, ux, uy } = taps[t];
        const px = ux > 0 ? ux : 0;
        const nx = ux < 0 ? -ux : 0;
        const py = uy > 0 ? uy : 0;
        const ny = uy < 0 ? -uy : 0;
        oR += g * px * this.right[i];
        oL += g * nx * this.left[i];
        oD += g * py * this.down[i];
        oU += g * ny * this.up[i];
        iR += g * nx * this.right[i];
        iL += g * px * this.left[i];
        iD += g * ny * this.down[i];
        iU += g * py * this.up[i];
        // Contrast has to be measured inside this cell's own receptive field.
        // Normalising a local response by a field-wide figure means a small
        // object on a plain wall divides a large local signal by a nearly empty
        // field: a disc crossing the view scored a hundred times an approach.
        energy += g * this.hp[i] * this.hp[i];
      }
      const outward = Math.sqrt(Math.sqrt(oR * oL * oD * oU));
      const inward = Math.sqrt(Math.sqrt(iR * iL * iD * iU));
      const localRms = Math.sqrt(energy / total);
      const norm = 1 / (localRms * localRms + CONTRAST_FLOOR * CONTRAST_FLOOR + EPS);
      const response = Math.max(0, (outward - inward) / total) * norm * selfMotionGate;
      this.instant[c] = response;
      this.cells[c] += (response - this.cells[c]) * aCell;
      if (this.cells[c] > best) { best = this.cells[c]; bestCell = c; }
    }

    const cell = this.pool[bestCell];
    return {
      expansion: best * VISION_GAIN,
      azimuth: cell.azimuth,
      elevation: cell.elevation,
      peak: bestCell,
      cells: this.cells,
      contrast: rms,
      coherence,
      selfMotion: coherence >= COHERENCE_LIMIT,
    };
  }

  _quiet() {
    this.cells.fill(0);
    return {
      expansion: 0, azimuth: 0, elevation: 0, peak: 0,
      cells: this.cells, contrast: 0, coherence: 0, selfMotion: false,
    };
  }

  /** Where cell `c` sits in the visual field, normalised 0..1. For drawing. */
  cellPosition(c) {
    return { x: this.pool[c].x, y: this.pool[c].y };
  }
}
