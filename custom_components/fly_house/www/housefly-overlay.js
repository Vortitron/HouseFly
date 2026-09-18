/**
 * housefly-overlay -- a fly that walks on your dashboard.
 *
 * The card itself renders almost nothing. What it does is mount a fixed,
 * click-through canvas over the whole viewport, find every ha-card on the
 * current view by walking the shadow DOM, and report their screen rectangles
 * to the integration. Those rectangles become landmarks: the brain gets a real
 * bearing to each one and its ring neurons are driven by it exactly as they
 * would be by a stripe on the wall of an arena.
 *
 * Position is integrated here rather than on the server. The brain publishes
 * heading, turn rate and forward speed a few times a second; this dead-reckons
 * between those updates at display rate, which is what a fly's own body does
 * between the updates its compass gives it.
 */

import { createLegs, stepGait, drawFly } from './housefly-fly.js';

const TAU = Math.PI * 2;
const Z_INDEX = 9999;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const angleDelta = (a, b) => ((b - a + Math.PI * 3) % TAU) - Math.PI;

/** Recursively collect elements through shadow roots, which Lovelace is full of. */
function deepQuery(root, selector, found = [], depth = 0) {
  if (!root || depth > 14) return found;
  if (root.querySelectorAll) {
    for (const el of root.querySelectorAll(selector)) found.push(el);
  }
  const children = root.shadowRoot
    ? [root.shadowRoot]
    : (root.children ? Array.from(root.children) : []);
  for (const child of children) {
    deepQuery(child, selector, found, depth + 1);
    if (child.shadowRoot) deepQuery(child.shadowRoot, selector, found, depth + 1);
  }
  return found;
}

/** Best effort at working out which entity a card is showing. */
function entityOfCard(card) {
  let node = card;
  for (let i = 0; i < 6 && node; i++) {
    const cfg = node._config || node.config;
    if (cfg) {
      if (typeof cfg.entity === 'string') return cfg.entity;
      if (Array.isArray(cfg.entities) && cfg.entities.length) {
        const first = cfg.entities[0];
        if (typeof first === 'string') return first;
        if (first && typeof first.entity === 'string') return first.entity;
      }
    }
    node = node.parentElement || (node.getRootNode && node.getRootNode().host);
  }
  return null;
}

class HouseFlyOverlay extends HTMLElement {
  setConfig(config) {
    this._config = { scale: 1.0, show_debug: false, ...config };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._start();
  }

  getCardSize() { return 1; }

  // --------------------------------------------------------------- lifecycle
  connectedCallback() {
    this.innerHTML = `<style>
      .hf-note{padding:12px 16px;font:13px/1.5 var(--paper-font-body1_-_font-family,system-ui);
        color:var(--secondary-text-color,#889);background:var(--ha-card-background,#fff);
        border-radius:var(--ha-card-border-radius,12px);}
      .hf-note b{color:var(--primary-text-color,#222)}
    </style>
    <div class="hf-note"><b>HouseFly is loose on this dashboard.</b>
    Click the fly to swat at it. This card draws nothing itself.</div>`;
    if (this._hass) this._start();
  }

  disconnectedCallback() { this._stop(); }

  _start() {
    if (this._layer) return;
    this._fly = {
      x: window.innerWidth * 0.5, y: window.innerHeight * 0.4,
      heading: 0, speed: 0, turn: 0, mode: 'groom',
      wing: 0, perch: null, z: 0, trail: [],
      gait: 0, bank: 0, legs: createLegs(),
    };
    this._brain = { heading: 0, speed: 0, turn: 0, mode: 'groom', escape: 0, valence: 0, arousal: 0.5 };
    this._cards = [];

    this._layer = document.createElement('div');
    Object.assign(this._layer.style, {
      position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: String(Z_INDEX),
    });
    this._canvas = document.createElement('canvas');
    Object.assign(this._canvas.style, { width: '100%', height: '100%', display: 'block' });
    this._layer.appendChild(this._canvas);
    document.body.appendChild(this._layer);
    this._ctx = this._canvas.getContext('2d');

    this._onResize = () => this._resize();
    this._onScroll = () => this._scanSoon();
    this._onClick = (ev) => this._maybeSwat(ev);
    window.addEventListener('resize', this._onResize, { passive: true });
    window.addEventListener('scroll', this._onScroll, { passive: true, capture: true });
    document.addEventListener('click', this._onClick, { capture: true, passive: true });

    this._resize();
    this._scanSoon();
    this._subscribe();
    this._lastFrame = performance.now();
    this._raf = requestAnimationFrame((t) => this._frame(t));
    this._scanTimer = setInterval(() => this._scanSoon(), 4000);
  }

  _stop() {
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this._scanTimer) clearInterval(this._scanTimer);
    if (this._unsub) { this._unsub.then((f) => f && f()).catch(() => {}); this._unsub = null; }
    window.removeEventListener('resize', this._onResize);
    window.removeEventListener('scroll', this._onScroll, { capture: true });
    document.removeEventListener('click', this._onClick, { capture: true });
    if (this._layer) this._layer.remove();
    this._layer = null;
  }

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    this._canvas.width = Math.floor(window.innerWidth * dpr);
    this._canvas.height = Math.floor(window.innerHeight * dpr);
    this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // ------------------------------------------------------------------- data
  _subscribe() {
    if (!this._hass || !this._hass.connection) return;
    this._unsub = this._hass.connection.subscribeMessage(
      (msg) => { this._brain = { ...this._brain, ...msg }; },
      { type: 'fly_house/subscribe' },
    ).catch((err) => {
      console.warn('[housefly] no live brain stream:', err);
      return null;
    });
  }

  _scanSoon() {
    clearTimeout(this._scanDebounce);
    this._scanDebounce = setTimeout(() => this._scanCards(), 160);
  }

  /** Find every card on screen and tell the brain where they are. */
  _scanCards() {
    const root = document.querySelector('home-assistant');
    if (!root) return;
    const seen = deepQuery(root, 'ha-card');
    const vw = window.innerWidth, vh = window.innerHeight;
    const cards = [];
    for (const el of seen) {
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 28) continue;
      if (r.bottom < -80 || r.top > vh + 80) continue;   // offscreen vertically
      cards.push({ el, entity: entityOfCard(el), x: r.left, y: r.top, w: r.width, h: r.height });
    }
    this._cards = cards;

    if (this._hass && this._hass.connection && cards.length) {
      const payload = cards.map(({ entity, x, y, w, h }) => ({ entity, x, y, w, h }));
      this._hass.connection.sendMessagePromise({
        type: 'fly_house/layout',
        cards: payload,
        viewport: { w: vw, h: vh },
        // The brain works out bearings from this, so it has to be where the
        // fly actually is on screen, not where the brain last guessed.
        fly: { x: this._fly.x / vw, y: this._fly.y / vh },
      }).catch(() => {});
    }
  }

  _maybeSwat(ev) {
    const f = this._fly;
    const dist = Math.hypot(ev.clientX - f.x, ev.clientY - f.y);
    if (dist > 60) return;
    // A hand coming at a fly is a looming stimulus, and looming is exactly what
    // LPLC2 is for. Report it as one rather than as a generic "poke".
    this._hass.callService('fly_house', 'loom', {
      strength: clamp(2.2 - dist / 40, 0.6, 2.2),
    }).catch(() => {});
    f.trail = [];
  }

  // ------------------------------------------------------------------ frame
  _frame(now) {
    const dt = Math.min(0.05, (now - this._lastFrame) / 1000);
    this._lastFrame = now;
    this._update(dt);
    this._draw();
    this._raf = requestAnimationFrame((t) => this._frame(t));
  }

  _update(dt) {
    const f = this._fly, b = this._brain;

    // Steer towards the heading the central complex is holding. The brain owns
    // the direction; the body just catches up to it at a finite rate.
    const delta = angleDelta(f.heading, b.heading || 0);
    const agility = b.mode === 'escape' ? 14 : 4;
    f.heading += clamp(delta, -agility * dt, agility * dt);
    f.heading = (f.heading + TAU) % TAU;

    // Banking. A fly leans into a turn, and it is the cue that makes a change
    // of direction read as deliberate rather than as a jump cut.
    f.bank += (clamp(delta * 2.2, -0.5, 0.5) - f.bank) * Math.min(1, dt * 5);

    const escaping = (b.escape || 0) > 0.15;
    const asleep = b.mode === 'sleep';

    // A fly walks far more than it flies. It takes off to cross open space or
    // when startled, and walks once it is on something -- so the mode here is
    // decided by whether it is over a card, not by a coin flip.
    const overCard = this._cardAt(f.x, f.y);
    const wantsToFly = escaping || !overCard || (b.speed || 0) > 0.55;
    f.airborne = wantsToFly;

    const pxPerSecond = escaping ? 820
      : asleep ? 0
      : wantsToFly ? 90 + 190 * (b.speed || 0)
      : 14 + 44 * (b.speed || 0);        // walking pace, much slower
    f.speed += (pxPerSecond - f.speed) * Math.min(1, dt * 6);
    f.mode = b.mode || 'groom';
    f.perch = wantsToFly ? null : overCard;

    const moved = f.speed * dt;
    f.x += Math.cos(f.heading) * moved;
    f.y += Math.sin(f.heading) * moved;
    stepGait(f, moved, this._config.scale, f.airborne);

    // Altitude: on a surface, or in the air, and the shadow says which.
    const targetZ = f.airborne ? (escaping ? 18 : 9) : 0;
    f.z += (targetZ - f.z) * Math.min(1, dt * 7);

    // Walls. Bounce off the viewport rather than wandering off it forever.
    const m = 26;
    if (f.x < m) { f.x = m; f.heading = Math.PI - f.heading; }
    if (f.x > window.innerWidth - m) { f.x = window.innerWidth - m; f.heading = Math.PI - f.heading; }
    if (f.y < m) { f.y = m; f.heading = -f.heading; }
    if (f.y > window.innerHeight - m) { f.y = window.innerHeight - m; f.heading = -f.heading; }
    f.heading = (f.heading + TAU) % TAU;

    f.wing += dt * (asleep ? 0 : (escaping ? 95 : (f.airborne ? 62 : 6)));

    if (escaping) {
      f.trail.push({ x: f.x, y: f.y, t: 0 });
      if (f.trail.length > 18) f.trail.shift();
    }
    for (const p of f.trail) p.t += dt;
    f.trail = f.trail.filter((p) => p.t < 0.45);
  }

  _cardAt(x, y) {
    for (const c of this._cards) {
      if (x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h) return c;
    }
    return null;
  }

  // ------------------------------------------------------------------- draw
  _draw() {
    const ctx = this._ctx, f = this._fly;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);

    if (f.mode === 'escape' && f.trail.length > 1) {
      ctx.save();
      ctx.strokeStyle = 'rgba(120,190,255,0.30)';
      ctx.lineWidth = 2; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(f.trail[0].x, f.trail[0].y);
      for (const p of f.trail) ctx.lineTo(p.x, p.y);
      ctx.stroke(); ctx.restore();
    }

    // Shadow first, offset by altitude -- it is the only cue that says whether
    // the fly is sitting on the card or hovering above it.
    ctx.save();
    ctx.translate(f.x + f.z * 0.7, f.y + f.z * 1.5);
    ctx.scale(1, 0.4);
    ctx.beginPath();
    ctx.arc(0, 0, 11 + f.z * 0.25, 0, TAU);
    ctx.fillStyle = `rgba(0,0,0,${clamp(0.26 - f.z * 0.008, 0.05, 0.26)})`;
    ctx.fill();
    ctx.restore();

    drawFly(ctx, f, this._config.scale, {
      airborne: f.airborne,
      escaping: f.mode === 'escape',
      asleep: f.mode === 'sleep',
    });

    if (this._config.show_debug) this._drawDebug(ctx);
  }

  _drawDebug(ctx) {
    ctx.save();
    ctx.lineWidth = 1;
    const b = this._brain;
    for (const c of this._cards) {
      // Show which card it has decided to go to, and the bearing it is
      // steering on -- otherwise "it walks about" is indistinguishable from
      // "it walks about at random", which is the whole question.
      const isGoal = b.goal_entity && c.entity === b.goal_entity;
      ctx.strokeStyle = isGoal ? 'rgba(255,190,90,0.85)' : 'rgba(80,200,255,0.30)';
      ctx.lineWidth = isGoal ? 2 : 1;
      ctx.strokeRect(c.x, c.y, c.w, c.h);
      if (isGoal) {
        ctx.beginPath();
        ctx.moveTo(this._fly.x, this._fly.y);
        ctx.lineTo(c.x + c.w / 2, c.y + c.h / 2);
        ctx.setLineDash([4, 5]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    ctx.fillStyle = 'rgba(10,14,26,0.85)';
    ctx.fillRect(10, 10, 300, 118);
    ctx.fillStyle = '#9fe8ff';
    ctx.font = '11px ui-monospace,SFMono-Regular,Menlo,monospace';
    const lines = [
      `mode      ${b.mode}`,
      `heading   ${((b.heading || 0) * 180 / Math.PI).toFixed(0)}°`,
      `speed     ${(b.speed || 0).toFixed(2)}   turn ${(b.turn || 0).toFixed(2)}`,
      `escape    ${(b.escape || 0).toFixed(3)}`,
      `valence   ${(b.valence || 0).toFixed(3)}`,
      `landmarks ${this._cards.length}`,
      `goal      ${b.goal_entity || '\u2014'}`,
    ];
    lines.forEach((t, i) => ctx.fillText(t, 20, 30 + i * 14));
    ctx.restore();
  }
}

customElements.define('housefly-overlay', HouseFlyOverlay);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'housefly-overlay',
  name: 'HouseFly Overlay',
  description: 'Lets the fly walk over this dashboard. Cards become landmarks it can see.',
  preview: false,
});
