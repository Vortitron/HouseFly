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

    const escaping = (b.escape || 0) > 0.15;
    const asleep = b.mode === 'sleep';
    const pxPerSecond = escaping ? 900 : (asleep ? 0 : 60 + 170 * (b.speed || 0));
    f.speed += ((pxPerSecond) - f.speed) * Math.min(1, dt * 6);
    f.mode = b.mode || 'groom';

    // Perching: a fly at rest sits on something. Pick the card underneath it.
    const wantsPerch = !escaping && (b.speed || 0) < 0.22 && !asleep;
    if (wantsPerch && !f.perch) f.perch = this._cardAt(f.x, f.y);
    if (escaping || (b.speed || 0) > 0.4) f.perch = null;

    f.x += Math.cos(f.heading) * f.speed * dt;
    f.y += Math.sin(f.heading) * f.speed * dt;

    // Altitude: flies are on a surface or in the air, and the shadow should say
    // which. Perched means z=0, flying means lifted.
    const targetZ = f.perch ? 0 : (escaping ? 16 : 7);
    f.z += (targetZ - f.z) * Math.min(1, dt * 7);

    // Walls. Bounce off the viewport rather than wandering off it forever.
    const m = 26;
    if (f.x < m) { f.x = m; f.heading = Math.PI - f.heading; }
    if (f.x > window.innerWidth - m) { f.x = window.innerWidth - m; f.heading = Math.PI - f.heading; }
    if (f.y < m) { f.y = m; f.heading = -f.heading; }
    if (f.y > window.innerHeight - m) { f.y = window.innerHeight - m; f.heading = -f.heading; }
    f.heading = (f.heading + TAU) % TAU;

    f.wing += dt * (asleep ? 0 : (escaping ? 90 : (f.perch ? 8 : 55)));

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

    ctx.save();
    ctx.translate(f.x, f.y - f.z);
    ctx.rotate(f.heading + Math.PI / 2);
    ctx.scale(this._config.scale, this._config.scale);
    this._drawFly(ctx, f);
    ctx.restore();

    if (this._config.show_debug) this._drawDebug(ctx);
  }

  _drawFly(ctx, f) {
    const flapping = f.mode !== 'sleep' && (!f.perch || f.mode === 'escape');
    const flap = Math.sin(f.wing) * (flapping ? 1 : 0.1);

    // Legs
    ctx.strokeStyle = 'rgba(28,24,22,0.85)';
    ctx.lineWidth = 1.1;
    const legs = [[-4, -1, -11, -7], [-4.5, 2, -12, 3], [-4, 5, -10, 12],
                  [4, -1, 11, -7], [4.5, 2, 12, 3], [4, 5, 10, 12]];
    const gait = f.perch ? Math.sin(f.wing * 1.2) * 1.6 : 0;
    for (const [x1, y1, x2, y2] of legs) {
      ctx.beginPath(); ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(x2 * 0.6, y1 + 3, x2, y2 + (x1 < 0 ? gait : -gait));
      ctx.stroke();
    }

    // Wings: blurred ellipses when flying, folded over the back when perched.
    ctx.save();
    ctx.globalAlpha = flapping ? 0.32 : 0.55;
    ctx.fillStyle = '#cfe0f5';
    ctx.strokeStyle = 'rgba(150,175,205,0.7)';
    ctx.lineWidth = 0.5;
    for (const side of [-1, 1]) {
      ctx.save();
      ctx.translate(side * 2.5, 1);
      ctx.rotate(side * (flapping ? (0.5 + flap * 0.55) : 0.16));
      ctx.beginPath();
      ctx.ellipse(side * 6.5, 2, 11, 4.2, 0, 0, TAU);
      ctx.fill(); ctx.stroke();
      ctx.restore();
    }
    ctx.restore();

    // Abdomen, thorax, head
    const grad = ctx.createLinearGradient(0, -8, 0, 12);
    grad.addColorStop(0, '#4a4239'); grad.addColorStop(1, '#221d19');
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.ellipse(0, 6, 4.6, 8, 0, 0, TAU); ctx.fill();
    ctx.fillStyle = '#39322b';
    ctx.beginPath(); ctx.ellipse(0, -1.5, 4.4, 5.2, 0, 0, TAU); ctx.fill();
    ctx.fillStyle = '#2b2520';
    ctx.beginPath(); ctx.ellipse(0, -7.5, 3.9, 3.4, 0, 0, TAU); ctx.fill();

    // Compound eyes. Red, because Drosophila melanogaster, and because it is
    // the one detail everyone recognises.
    for (const side of [-1, 1]) {
      const eye = ctx.createRadialGradient(side * 2.2, -8.6, 0.3, side * 2.4, -8, 3.1);
      eye.addColorStop(0, '#ff6b5a'); eye.addColorStop(0.55, '#d0261c'); eye.addColorStop(1, '#7d0f0c');
      ctx.fillStyle = eye;
      ctx.beginPath(); ctx.ellipse(side * 2.4, -8, 2.5, 2.9, side * 0.2, 0, TAU); ctx.fill();
    }
    ctx.strokeStyle = 'rgba(40,34,30,0.9)'; ctx.lineWidth = 0.9;
    for (const side of [-1, 1]) {
      ctx.beginPath(); ctx.moveTo(side * 1.4, -10);
      ctx.quadraticCurveTo(side * 3, -13.5, side * 2.2, -15.5); ctx.stroke();
    }
  }

  _drawDebug(ctx) {
    ctx.save();
    ctx.strokeStyle = 'rgba(80,200,255,0.45)';
    ctx.lineWidth = 1;
    for (const c of this._cards) ctx.strokeRect(c.x, c.y, c.w, c.h);
    const b = this._brain;
    ctx.fillStyle = 'rgba(10,14,26,0.85)';
    ctx.fillRect(10, 10, 232, 104);
    ctx.fillStyle = '#9fe8ff';
    ctx.font = '11px ui-monospace,SFMono-Regular,Menlo,monospace';
    const lines = [
      `mode      ${b.mode}`,
      `heading   ${((b.heading || 0) * 180 / Math.PI).toFixed(0)}°`,
      `speed     ${(b.speed || 0).toFixed(2)}   turn ${(b.turn || 0).toFixed(2)}`,
      `escape    ${(b.escape || 0).toFixed(3)}`,
      `valence   ${(b.valence || 0).toFixed(3)}`,
      `landmarks ${this._cards.length}`,
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
