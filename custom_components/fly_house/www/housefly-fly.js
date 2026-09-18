/**
 * housefly-fly -- how the fly is drawn and how its legs move.
 *
 * Kept separate from the overlay because it is the only part anyone is likely
 * to want to fiddle with, and because it is the part that decides whether this
 * reads as an animal or as a sprite being dragged across the screen.
 *
 * The thing that makes it read as an animal is that **feet stay where they are
 * put**. A real fly walks with a tripod gait: front-left, middle-right and
 * hind-left push against the ground as one group while the opposite three swing
 * forward, then they swap. During stance a foot is motionless in the world and
 * the body travels over it. Sliding the whole thing along as one rigid picture
 * is what makes most 2D insects look like stickers, and it is avoided here by
 * storing foot positions in viewport coordinates rather than body coordinates.
 *
 * Nothing here is physics. The reference for how this ought to look is the
 * MuJoCo whole-body fly (Vaxenburg et al. 2025, Nature 642), 67 body parts and
 * 102 degrees of freedom solved with real fluid and adhesion forces. This is a
 * cartoon of that, chosen so it costs a few hundred microseconds a frame and
 * runs inside a Lovelace card.
 */

const TAU = Math.PI * 2;

/* Hip sockets and where each foot sits at rest, in body-frame units.
   +x is the fly's right, +y is behind it. One unit is roughly a millimetre of
   fly at the scale everything else is drawn. */
const LEGS = [
  { side: -1, hip: [-3.0, -4.0], rest: [-13, -11], tripod: 0 },  // front left
  { side: -1, hip: [-4.0,  0.5], rest: [-17,   1], tripod: 1 },  // middle left
  { side: -1, hip: [-3.5,  4.5], rest: [-14,  14], tripod: 0 },  // hind left
  { side:  1, hip: [ 3.0, -4.0], rest: [ 13, -11], tripod: 1 },  // front right
  { side:  1, hip: [ 4.0,  0.5], rest: [ 17,   1], tripod: 0 },  // middle right
  { side:  1, hip: [ 3.5,  4.5], rest: [ 14,  14], tripod: 1 },  // hind right
];

const STRIDE = 13;        // body-frame units a foot travels per step
const STEP_DISTANCE = 16; // viewport px of travel per half gait cycle

export function createLegs() {
  return LEGS.map((spec) => ({ ...spec, foot: null, lift: 0, from: null }));
}

/** Body frame -> viewport. */
function toWorld(bx, by, cx, cy, heading, scale) {
  // The body is drawn nose-up, so its +y axis points along `heading`.
  const c = Math.cos(heading), s = Math.sin(heading);
  const fx = by * scale, fy = -bx * scale;   // forward, left
  return [cx + fx * c - fy * s, cy + fx * s + fy * c];
}

/**
 * Advance the gait. `moved` is how far the body travelled this frame, in px --
 * driving the cycle by distance rather than by time is what keeps the feet from
 * skating when the fly speeds up or slows down.
 */
export function stepGait(fly, moved, scale, airborne) {
  fly.gait = (fly.gait + moved / STEP_DISTANCE) % 2;
  const swingPhase = fly.gait % 1;
  const activeTripod = fly.gait < 1 ? 0 : 1;

  for (const leg of fly.legs) {
    const stance = leg.tripod !== activeTripod;
    // Where this foot would like to be: rest position, shifted forward by half
    // a stride at the start of stance so the body has somewhere to travel to.
    const reach = stance ? -STRIDE * (swingPhase - 0.5) : STRIDE * 0.5;
    const target = toWorld(leg.rest[0], leg.rest[1] + reach,
                           fly.x, fly.y, fly.heading, scale);

    if (airborne) {
      // In the air the legs are simply tucked; nothing is planted.
      leg.foot = target;
      leg.lift = 1;
      continue;
    }
    if (!leg.foot) { leg.foot = target; leg.from = target; }

    if (stance) {
      leg.lift = 0;                       // planted: do not move it at all
    } else {
      if (leg.lift === 0) leg.from = leg.foot;   // just lifted off
      const t = swingPhase;
      const ease = t * t * (3 - 2 * t);
      leg.foot = [leg.from[0] + (target[0] - leg.from[0]) * ease,
                  leg.from[1] + (target[1] - leg.from[1]) * ease];
      leg.lift = Math.sin(t * Math.PI);   // arc height through the swing
    }
  }
}

/** Two-link inverse kinematics, elbow pointing outward. */
function knee(hx, hy, fx, fy, femur, tibia, side) {
  const dx = fx - hx, dy = fy - hy;
  const d = Math.max(1e-3, Math.hypot(dx, dy));
  const reach = Math.min(d, femur + tibia - 0.01);
  const a = (femur * femur - tibia * tibia + reach * reach) / (2 * reach);
  const h = Math.sqrt(Math.max(0, femur * femur - a * a));
  const mx = hx + (dx / d) * a, my = hy + (dy / d) * a;
  return [mx + (dy / d) * h * side, my - (dx / d) * h * side];
}

export function drawFly(ctx, fly, scale, opts = {}) {
  const { airborne = false, escaping = false, asleep = false } = opts;
  const s = scale;

  // ---- legs, drawn in viewport space so planted feet really are planted ----
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (const leg of fly.legs) {
    if (!leg.foot) continue;
    const [hx, hy] = toWorld(leg.hip[0], leg.hip[1], fly.x, fly.y, fly.heading, s);
    const lift = leg.lift * 3.2 * s;
    const fx = leg.foot[0], fy = leg.foot[1] - lift;
    const [kx, ky] = knee(hx, hy, fx, fy, 9 * s, 11 * s, leg.side);
    ctx.strokeStyle = 'rgba(28,23,20,0.92)';
    ctx.lineWidth = Math.max(1, 1.5 * s);
    ctx.beginPath();
    ctx.moveTo(hx, hy); ctx.lineTo(kx, ky); ctx.lineTo(fx, fy);
    ctx.stroke();
    // tarsus: the little foot that actually touches
    ctx.lineWidth = Math.max(0.8, 1.0 * s);
    ctx.beginPath();
    ctx.moveTo(fx, fy);
    ctx.lineTo(fx + (fx - kx) * 0.16, fy + (fy - ky) * 0.16 + (leg.lift < 0.1 ? 0 : 0));
    ctx.stroke();
  }
  ctx.restore();

  // ---- body ---------------------------------------------------------------
  ctx.save();
  ctx.translate(fly.x, fly.y - fly.z);
  ctx.rotate(fly.heading + Math.PI / 2);
  // Bank into turns, and bob with the gait. Both are small; both are why it
  // looks alive rather than like a decal.
  const bob = airborne ? 0 : Math.sin(fly.gait * Math.PI * 2) * 0.55 * s;
  ctx.translate(0, bob);
  ctx.rotate(Math.max(-0.5, Math.min(0.5, -fly.bank)));

  if (airborne) {
    ctx.save();
    ctx.globalAlpha = escaping ? 0.5 : 0.36;
    ctx.fillStyle = '#cfe0f5';
    for (const side of [-1, 1]) {
      ctx.save();
      ctx.translate(side * 2.4 * s, 0.6 * s);
      ctx.rotate(side * (0.42 + Math.sin(fly.wing) * 0.5));
      ctx.beginPath();
      ctx.ellipse(side * 7 * s, 1.5 * s, 11.5 * s, 4.4 * s, 0, 0, TAU);
      ctx.fill();
      ctx.restore();
    }
    ctx.restore();
  }

  // abdomen, banded
  const grad = ctx.createLinearGradient(0, -6 * s, 0, 13 * s);
  grad.addColorStop(0, '#5a5044'); grad.addColorStop(1, '#241f1a');
  ctx.fillStyle = grad;
  ctx.beginPath(); ctx.ellipse(0, 6.2 * s, 4.5 * s, 8.1 * s, 0, 0, TAU); ctx.fill();
  ctx.strokeStyle = 'rgba(20,17,14,0.5)';
  ctx.lineWidth = Math.max(0.6, 0.8 * s);
  for (const y of [3.5, 6.2, 8.9]) {
    ctx.beginPath();
    ctx.ellipse(0, y * s, 4.5 * s * Math.sqrt(1 - ((y - 6.2) / 8.1) ** 2), 0.5 * s, 0, 0, Math.PI);
    ctx.stroke();
  }

  if (!airborne) {
    // Wings folded flat along the back when walking -- a fly at rest is not a
    // fly with its wings out, and getting this wrong is instantly readable.
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.fillStyle = '#c3d6ee';
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(side * 1.5 * s, 6.5 * s, 2.6 * s, 8.6 * s, side * 0.1, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  ctx.fillStyle = '#4a4238';
  ctx.beginPath(); ctx.ellipse(0, -1.4 * s, 4.3 * s, 5.4 * s, 0, 0, TAU); ctx.fill();
  ctx.fillStyle = 'rgba(122,110,92,0.55)';
  ctx.beginPath(); ctx.ellipse(-1.3 * s, -2.6 * s, 1.9 * s, 2.7 * s, 0, 0, TAU); ctx.fill();

  ctx.fillStyle = '#2b2520';
  ctx.beginPath(); ctx.ellipse(0, -7.8 * s, 3.8 * s, 3.5 * s, 0, 0, TAU); ctx.fill();

  // Compound eyes. Red, because Drosophila melanogaster, and because it is the
  // one detail everybody recognises.
  for (const side of [-1, 1]) {
    const ex = side * 2.3 * s;
    const eye = ctx.createRadialGradient(ex, -8.8 * s, 0.3 * s, ex, -8 * s, 3.2 * s);
    eye.addColorStop(0, asleep ? '#8d2a22' : '#ff6b5a');
    eye.addColorStop(0.55, '#cf261c');
    eye.addColorStop(1, '#79100c');
    ctx.fillStyle = eye;
    ctx.beginPath();
    ctx.ellipse(ex, -8 * s, 2.5 * s, 2.9 * s, side * 0.2, 0, TAU);
    ctx.fill();
  }
  ctx.strokeStyle = 'rgba(40,34,30,0.9)';
  ctx.lineWidth = Math.max(0.8, 1.0 * s);
  for (const side of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(side * 1.3 * s, -10 * s);
    ctx.quadraticCurveTo(side * 2.9 * s, -13.2 * s, side * 2.0 * s, -15.2 * s);
    ctx.stroke();
  }
  ctx.restore();
}
