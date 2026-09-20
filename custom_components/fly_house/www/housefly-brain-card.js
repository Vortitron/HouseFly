/**
 * housefly-brain-card -- the connectome, drawn with the fly's live activity in it.
 *
 * Every point is one real neuron at its real soma position, taken from the
 * FlyWire whole-brain reconstruction. Every point's brightness is that cell's
 * firing rate in the model running inside Home Assistant right now. Nothing is
 * decorative: if the ellipsoid body lights up on one side, that is the heading
 * bump, and it is pointing somewhere.
 *
 * Deliberately no WebGL and no external library. Five thousand points through
 * a hand-rolled projection into canvas 2D runs at 60fps on a phone, and a
 * Lovelace card that needs a CDN is a Lovelace card that breaks on a local-only
 * install.
 */

/* Every websocket call carries the fly it means, when the card has been told
   which one. Omitted, the backend falls back to the first fly -- which is the
   right answer for a house with one, and the wrong one for a house with
   several, where every card would otherwise watch the same insect. */
function forFly(config, message) {
  return config && config.entry_id ? { ...message, entry_id: config.entry_id } : message;
}

const TAU = Math.PI * 2;

/* Circuit palette. Warm for the sensory periphery, cool for the central brain,
   which is roughly how the published renderings of this dataset are coloured. */
const GROUP_STYLE = {
  compass:    { name: 'Compass (EPG/PEN/Δ7)', rgb: [90, 215, 255] },
  ring:       { name: 'Ring neurons (ER)',    rgb: [120, 160, 255] },
  steer:      { name: 'Steering (PFL/PFN)',   rgb: [150, 235, 210] },
  mb_kc:      { name: 'Kenyon cells',         rgb: [222, 165, 105] },
  mb_out:     { name: 'MBONs',                rgb: [255, 205, 120] },
  mb_dan:     { name: 'Dopaminergic',         rgb: [255, 125, 160] },
  mb_inh:     { name: 'APL (inhibitory)',     rgb: [190, 190, 200] },
  olfactory:  { name: 'Projection neurons',   rgb: [235, 140, 90] },
  loom:       { name: 'Looming (LPLC2/LC)',   rgb: [255, 170, 80] },
  descending: { name: 'Descending',           rgb: [255, 95, 85] },
  clock:      { name: 'Clock neurons',        rgb: [180, 255, 160] },
};

class HouseFlyBrainCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._rot = { x: -0.35, y: 0.5 };
    this._drag = null;
    this._activity = null;
    this._state = {};
  }

  setConfig(config) {
    this._config = { entry_id: null, autorotate: true, point_size: 1.0, ...config };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) { this._render(); this._connect(); }
  }

  getCardSize() { return 8; }
  disconnectedCallback() { this._teardown(); }

  _teardown() {
    if (this._raf) cancelAnimationFrame(this._raf);
    for (const key of ['_unsubState', '_unsubNeurons']) {
      if (this[key]) { this[key].then((f) => f && f()).catch(() => {}); this[key] = null; }
    }
  }

  // ------------------------------------------------------------------ setup
  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .wrap {
          position: relative; border-radius: var(--ha-card-border-radius, 12px);
          overflow: hidden; background: #070b14;
          border: 1px solid rgba(120,190,255,0.14);
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        }
        canvas { display: block; width: 100%; height: 380px; cursor: grab; touch-action: none; }
        canvas:active { cursor: grabbing; }
        .hud { position: absolute; pointer-events: none; color: #8fd8f5; font-size: 11px; }
        .tl { top: 12px; left: 14px; }
        .tr { top: 12px; right: 14px; text-align: right; }
        .bl { bottom: 12px; left: 14px; }
        .title { color: #d9f2ff; font-size: 13px; letter-spacing: 0.10em; text-transform: uppercase; }
        .sub { color: #5d7fa0; margin-top: 3px; }
        .big { color: #eaf8ff; font-size: 21px; margin-top: 2px; }
        .legend { display: flex; flex-wrap: wrap; gap: 3px 12px; max-width: 62%; }
        .legend div { display: flex; align-items: center; gap: 5px; color: #6f90ad; }
        .dot { width: 6px; height: 6px; border-radius: 50%; }
        .mode { text-transform: uppercase; letter-spacing: 0.08em; }
        .cite { padding: 8px 14px; font-size: 10px; color: #4a627c; background: #050810;
                border-top: 1px solid rgba(120,190,255,0.10); line-height: 1.5; }
        .cite b { color: #7fa8c8; font-weight: 500; }
      </style>
      <div class="wrap">
        <canvas id="c"></canvas>
        <div class="hud tl">
          <div class="title">Drosophila connectome</div>
          <div class="sub" id="counts">loading…</div>
        </div>
        <div class="hud tr">
          <div class="sub mode" id="mode">—</div>
          <div class="big" id="heading">—</div>
          <div class="sub" id="detail"></div>
        </div>
        <div class="hud bl"><div class="legend" id="legend"></div></div>
      </div>
      <div class="cite">
        <b>Connectivity</b> hemibrain v1.2, Scheffer et al. 2020 ·
        <b>Positions &amp; transmitters</b> FlyWire, Schlegel et al. 2024 · both CC-BY 4.0.
        Brightness is live model activity, not a recording.
      </div>`;

    this._canvas = this.shadowRoot.getElementById('c');
    this._ctx = this._canvas.getContext('2d');
    this._bindPointer();
    this._resize();
    new ResizeObserver(() => this._resize()).observe(this._canvas);
  }

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const r = this._canvas.getBoundingClientRect();
    if (!r.width) return;
    this._canvas.width = Math.floor(r.width * dpr);
    this._canvas.height = Math.floor(r.height * dpr);
    this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._w = r.width; this._h = r.height;
  }

  _bindPointer() {
    const c = this._canvas;
    c.addEventListener('pointerdown', (e) => {
      this._drag = { x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', (e) => {
      if (!this._drag) return;
      this._rot.y += (e.clientX - this._drag.x) * 0.008;
      this._rot.x += (e.clientY - this._drag.y) * 0.008;
      this._rot.x = Math.max(-1.4, Math.min(1.4, this._rot.x));
      this._drag = { x: e.clientX, y: e.clientY };
    });
    c.addEventListener('pointerup', () => { this._drag = null; });
    c.addEventListener('pointercancel', () => { this._drag = null; });
  }

  // ------------------------------------------------------------------- data
  async _connect() {
    const conn = this._hass && this._hass.connection;
    if (!conn) return;
    try {
      const geo = await conn.sendMessagePromise(
        forFly(this._config, { type: 'fly_house/connectome' }));
      this._geometry = this._prepare(geo);
      this._buildLegend();
      this.shadowRoot.getElementById('counts').textContent =
        `${geo.n.toLocaleString()} neurons · ${geo.n_connections.toLocaleString()} synapses`;
    } catch (err) {
      this.shadowRoot.getElementById('counts').textContent = 'no HouseFly instance found';
      return;
    }
    this._unsubState = conn.subscribeMessage(
      (m) => { this._state = m; },
      forFly(this._config, { type: 'fly_house/subscribe' })).catch(() => null);
    this._unsubNeurons = conn.subscribeMessage(
      (m) => { this._activity = this._decode(m.activity); },
      forFly(this._config, { type: 'fly_house/neurons' })).catch(() => null);
    this._raf = requestAnimationFrame((t) => this._frame(t));
  }

  _decode(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  /** Centre and scale the soma cloud, and pre-sort nothing -- depth changes every frame. */
  _prepare(geo) {
    const n = geo.n;
    const p = this._decodePositions(geo.positions);
    let cx = 0, cy = 0, cz = 0;
    for (let i = 0; i < n; i++) { cx += p[i * 3]; cy += p[i * 3 + 1]; cz += p[i * 3 + 2]; }
    cx /= n; cy /= n; cz /= n;
    let span = 1;
    for (let i = 0; i < n; i++) {
      span = Math.max(span, Math.abs(p[i * 3] - cx), Math.abs(p[i * 3 + 1] - cy),
                      Math.abs(p[i * 3 + 2] - cz));
    }
    const xyz = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      xyz[i * 3] = (p[i * 3] - cx) / span;
      xyz[i * 3 + 1] = (p[i * 3 + 1] - cy) / span;
      xyz[i * 3 + 2] = (p[i * 3 + 2] - cz) / span;
    }
    const colour = new Uint8Array(n * 3);
    geo.groups.forEach((g, i) => {
      const rgb = (GROUP_STYLE[g] || { rgb: [140, 160, 180] }).rgb;
      colour[i * 3] = rgb[0]; colour[i * 3 + 1] = rgb[1]; colour[i * 3 + 2] = rgb[2];
    });
    return { n, xyz, colour, groups: geo.groups, order: new Int32Array(n), depth: new Float32Array(n) };
  }

  _decodePositions(b64) {
    const bin = atob(b64);
    const buf = new ArrayBuffer(bin.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
    return new Float32Array(buf);
  }

  _buildLegend() {
    const el = this.shadowRoot.getElementById('legend');
    const present = [...new Set(this._geometry.groups)];
    el.innerHTML = present.map((g) => {
      const s = GROUP_STYLE[g] || { name: g, rgb: [140, 160, 180] };
      return `<div><span class="dot" style="background:rgb(${s.rgb.join(',')})"></span>${s.name}</div>`;
    }).join('');
  }

  // ------------------------------------------------------------------ frame
  _frame() {
    if (this._config.autorotate && !this._drag) this._rot.y += 0.0022;
    this._draw();
    this._raf = requestAnimationFrame(() => this._frame());
  }

  _draw() {
    const ctx = this._ctx, w = this._w, h = this._h;
    if (!ctx || !w) return;
    ctx.fillStyle = '#070b14';
    ctx.fillRect(0, 0, w, h);
    this._drawGrid(ctx, w, h);
    if (!this._geometry) return;

    const g = this._geometry;
    const { sin, cos } = Math;
    const cx = cos(this._rot.x), sx = sin(this._rot.x);
    const cy = cos(this._rot.y), sy = sin(this._rot.y);
    const scale = Math.min(w, h) * 0.46;
    const ox = w * 0.5, oy = h * 0.5;

    // Rotate, then sort back-to-front so the additive glow layers correctly.
    const px = new Float32Array(g.n), py = new Float32Array(g.n);
    for (let i = 0; i < g.n; i++) {
      const x = g.xyz[i * 3], y = g.xyz[i * 3 + 1], z = g.xyz[i * 3 + 2];
      const x1 = x * cy + z * sy;
      const z1 = -x * sy + z * cy;
      const y1 = y * cx - z1 * sx;
      const z2 = y * sx + z1 * cx;
      const persp = 1 / (1.9 + z2 * 0.5);
      px[i] = ox + x1 * scale * persp * 1.9;
      py[i] = oy + y1 * scale * persp * 1.9;
      g.depth[i] = z2;
      g.order[i] = i;
    }
    const order = Array.from(g.order).sort((a, b) => g.depth[a] - g.depth[b]);

    const act = this._activity;
    const size = this._config.point_size;
    ctx.globalCompositeOperation = 'lighter';
    for (const i of order) {
      const a = act ? act[i] / 255 : 0;
      const depthFade = 0.35 + 0.65 * (1 - (g.depth[i] + 1) / 2);
      const base = 0.13 * depthFade;
      const alpha = Math.min(1, base + a * 1.25);
      const r = (0.75 + a * 2.4) * size;
      ctx.fillStyle = `rgba(${g.colour[i * 3]},${g.colour[i * 3 + 1]},${g.colour[i * 3 + 2]},${alpha})`;
      ctx.beginPath();
      ctx.arc(px[i], py[i], r, 0, TAU);
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';

    this._drawCompassRing(ctx, w, h);
    this._updateHud();
  }

  /** Faint technical grid plus corner registration marks. */
  _drawGrid(ctx, w, h) {
    ctx.strokeStyle = 'rgba(90,150,210,0.055)';
    ctx.lineWidth = 1;
    const step = 34;
    ctx.beginPath();
    for (let x = 0; x <= w; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, h); }
    for (let y = 0; y <= h; y += step) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
    ctx.stroke();
    ctx.strokeStyle = 'rgba(130,190,240,0.30)';
    const m = 16, s = 5;
    for (const [x, y] of [[m, m], [w - m, m], [m, h - m], [w - m, h - m]]) {
      ctx.beginPath();
      ctx.moveTo(x - s, y); ctx.lineTo(x + s, y);
      ctx.moveTo(x, y - s); ctx.lineTo(x, y + s);
      ctx.stroke();
    }
  }

  /** The heading bump, drawn as the ellipsoid body actually is: a ring of wedges. */
  _drawCompassRing(ctx, w, h) {
    const prof = this._state.compass;
    if (!Array.isArray(prof) || !prof.length) return;
    const cx = w - 62, cy = h - 62, R = 34;
    const peak = Math.max(...prof, 1e-6);
    ctx.save();
    ctx.strokeStyle = 'rgba(120,190,255,0.20)';
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.stroke();
    const n = prof.length;
    for (let i = 0; i < n; i++) {
      const a0 = (i / n) * TAU - Math.PI / 2;
      const a1 = ((i + 1) / n) * TAU - Math.PI / 2;
      const v = prof[i] / peak;
      ctx.beginPath();
      ctx.arc(cx, cy, R, a0, a1);
      ctx.arc(cx, cy, R - 11, a1, a0, true);
      ctx.closePath();
      ctx.fillStyle = `rgba(90,215,255,${0.06 + v * 0.85})`;
      ctx.fill();
    }
    const hd = this._state.heading || 0;
    ctx.strokeStyle = '#eaf8ff'; ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(hd - Math.PI / 2) * (R - 14), cy + Math.sin(hd - Math.PI / 2) * (R - 14));
    ctx.stroke();
    ctx.fillStyle = '#5d7fa0';
    ctx.font = '9px ui-monospace, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('ELLIPSOID BODY', cx, cy + R + 14);
    ctx.restore();
  }

  _updateHud() {
    const s = this._state;
    const set = (id, v) => { const el = this.shadowRoot.getElementById(id); if (el) el.textContent = v; };
    set('mode', s.mode || '—');
    set('heading', s.heading == null ? '—' : `${((s.heading * 180) / Math.PI).toFixed(0)}°`);
    const bits = [];
    if (s.kc_active != null) bits.push(`${s.kc_active} KC active`);
    if (s.memory_depression != null) bits.push(`memory ${(s.memory_depression * 100).toFixed(1)}%`);
    set('detail', bits.join(' · '));
  }
}

customElements.define('housefly-brain-card', HouseFlyBrainCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'housefly-brain-card',
  name: 'HouseFly Connectome',
  description: 'Live activity rendered on the real Drosophila connectome.',
  preview: true,
});
