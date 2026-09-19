/**
 * housefly-eye-card -- gives the fly an eye, and shows you what it sees with it.
 *
 * The model is in housefly-vision.js; this is the plumbing and the picture. The
 * picture is worth a word, because the usual version of this is a camera feed
 * with a box drawn round a person, and that is not what is happening here.
 *
 * What is drawn is the LPLC2 population: 63 receptive fields tiling the visual
 * field, each one a cell, each one's brightness its own response this instant.
 * That is the actual state of the actual model, not an illustration of it. When
 * something comes at the camera you watch a patch of cells light up where it is
 * -- which is what retinotopy means, and it is why the fly can be told *where*
 * the threat was and not merely that there was one.
 *
 * Privacy, plainly: frames are read into a canvas in this page and never leave
 * it. What goes to Home Assistant is two numbers about ten times a second, an
 * expansion rate and an angle. There is no way to reconstruct a picture from
 * that, and nothing is recorded.
 */

import { FlyEye, CELLS_X, CELLS_Y, FOV_X } from './housefly-vision.js';

/* The card reports at most this often. The eye itself runs at the display's
   frame rate, because a correlator fed at 10 Hz is measuring something else --
   but the brain only thinks every couple of seconds, so sending every frame
   would be 50 messages per think. The peak between reports is what is sent,
   which is the number that matters for a transient. */
const REPORT_HZ = 10;

/* Below this, nothing is sent at all. Not a threshold on the response -- the
   escape threshold lives in the brain, which is the whole point -- just a floor
   to keep an idle camera from chattering at the websocket. */
const REPORT_FLOOR = 0.01;

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; }
  .head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  h2 { margin: 0 0 2px; font-size: 1.05rem; font-weight: 600; }
  .sub { margin: 0 0 12px; opacity: 0.7; font-size: 0.82rem; line-height: 1.45; }
  .stage { position: relative; width: 100%; aspect-ratio: 4 / 3; border-radius: 10px;
           overflow: hidden; background: #0b0d10; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  video { display: none; }
  .idle { position: absolute; inset: 0; display: flex; flex-direction: column;
          align-items: center; justify-content: center; gap: 12px; text-align: center;
          padding: 20px; color: #cfd6df; }
  .idle p { margin: 0; max-width: 34ch; font-size: 0.82rem; line-height: 1.5; opacity: 0.8; }
  button { font: inherit; padding: 9px 16px; border-radius: 999px; cursor: pointer;
           border: 1px solid rgba(255,255,255,0.25); background: rgba(255,255,255,0.08);
           color: inherit; }
  button:hover { background: rgba(255,255,255,0.16); }
  .readout { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
  .cell { background: var(--secondary-background-color); border-radius: 8px; padding: 8px 10px; }
  .cell .k { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.6; }
  .cell .v { font-size: 1.15rem; font-variant-numeric: tabular-nums; }
  .note { margin-top: 10px; font-size: 0.76rem; opacity: 0.6; line-height: 1.5; }
  .warn { color: #ffcc66; }
`;

class HouseFlyEyeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._eye = new FlyEye();
    this._last = 0;
    this._peak = 0;
    this._peakAz = 0;
    this._sent = 0;
    this._out = null;
    this._running = false;
  }

  setConfig(config) {
    this._config = { camera_entity: null, ...config };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._render();
  }

  getCardSize() { return 7; }

  disconnectedCallback() { this._stop(); }

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="head"><h2>Let it see you</h2></div>
        <p class="sub">
          Its looming detectors work on photons, the way the animal's do:
          photoreceptors, T4/T5 motion correlators, then the LPLC2 population.
          Every circle below is one LPLC2 cell, lit by its own response right now.
        </p>
        <div class="stage">
          <video playsinline muted></video>
          <canvas></canvas>
          <div class="idle">
            <p>Nothing leaves this page. Frames are read into a canvas here; what
               reaches Home Assistant is an expansion rate and an angle, about ten
               times a second. Nothing is recorded.</p>
            <button>Use my camera</button>
          </div>
        </div>
        <div class="readout">
          <div class="cell"><div class="k">Expansion</div><div class="v" id="exp">--</div></div>
          <div class="cell"><div class="k">Where</div><div class="v" id="az">--</div></div>
          <div class="cell"><div class="k">Escape</div><div class="v" id="esc">--</div></div>
        </div>
        <p class="note" id="note">
          Move your hand towards the camera. Slowly does nothing and waving sideways
          does nothing -- the cell only answers to its own patch of sky expanding,
          which is what those four dendritic branches are for.
        </p>
      </ha-card>`;

    this._video = root.querySelector('video');
    this._canvas = root.querySelector('canvas');
    this._idle = root.querySelector('.idle');
    root.querySelector('button').addEventListener('click', () => this._useWebcam());

    if (this._config.camera_entity) this._useHaCamera();
  }

  async _useWebcam() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240, facingMode: 'user' }, audio: false,
      });
      this._stream = stream;
      this._video.srcObject = stream;
      await this._video.play();
      this._begin();
    } catch (err) {
      this._idle.querySelector('p').textContent =
        `No camera available: ${err && err.name ? err.name : err}. ` +
        'The approach slider and the radar drive the same pathway if you would rather use those.';
    }
  }

  /* A Home Assistant camera, proxied by Home Assistant itself. That matters for
     more than tidiness: the proxy is same-origin, so the canvas is not tainted
     and its pixels can be read back. A camera fetched straight from its own
     address would render fine and then refuse to be read, which is a confusing
     way to fail. */
  _useHaCamera() {
    const entity = this._hass.states[this._config.camera_entity];
    if (!entity) {
      this._idle.querySelector('p').textContent =
        `No such camera: ${this._config.camera_entity}`;
      return;
    }
    const token = entity.attributes.access_token;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = `/api/camera_proxy_stream/${this._config.camera_entity}?token=${token}`;
    img.onload = () => { this._source = img; this._begin(); };
    img.onerror = () => {
      this._idle.querySelector('p').textContent =
        'That camera would not stream. A still-image camera cannot drive this: ' +
        'optic flow needs frames close enough together to correspond.';
    };
    this._source = img;
    // An MJPEG stream fires load once and then keeps painting, so start anyway.
    setTimeout(() => { if (!this._running) this._begin(); }, 1200);
  }

  _begin() {
    if (this._running) return;
    this._running = true;
    this._idle.style.display = 'none';
    this._scratch = document.createElement('canvas');
    this._scratch.width = 80;
    this._scratch.height = 60;
    this._scratchCtx = this._scratch.getContext('2d', { willReadFrequently: true });
    this._last = performance.now();
    this._loop();
  }

  _stop() {
    this._running = false;
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this._stream) {
      for (const track of this._stream.getTracks()) track.stop();
      this._stream = null;
    }
  }

  _loop = () => {
    if (!this._running) return;
    this._raf = requestAnimationFrame(this._loop);
    const now = performance.now();
    const dt = Math.min(0.2, (now - this._last) / 1000);
    if (dt < 1 / 70) return;              // one step per displayed frame, no more
    this._last = now;

    const src = this._source || this._video;
    const w = src.videoWidth || src.naturalWidth || src.width;
    const h = src.videoHeight || src.naturalHeight || src.height;
    if (!w || !h) return;

    try {
      this._scratchCtx.drawImage(src, 0, 0, this._scratch.width, this._scratch.height);
    } catch (err) {
      return;                              // stream not ready yet
    }
    const frame = this._scratchCtx.getImageData(0, 0, this._scratch.width, this._scratch.height);
    this._eye.sample(frame.data, this._scratch.width, this._scratch.height);
    const out = this._eye.step(dt);
    this._out = out;

    if (out.expansion > this._peak) {
      this._peak = out.expansion;
      this._peakAz = out.azimuth;
    }
    if (now - this._sent > 1000 / REPORT_HZ) {
      this._sent = now;
      if (this._peak > REPORT_FLOOR) this._report(this._peak, this._peakAz);
      this._peak = 0;
    }
    this._draw(out);
  };

  _report(expansion, azimuth) {
    this._hass.connection
      .sendMessagePromise({ type: 'fly_house/vision', expansion, azimuth })
      .catch(() => { /* the integration may be reloading; the next frame will do */ });
  }

  _draw(out) {
    const canvas = this._canvas;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== rect.width * dpr) {
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    }
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    ctx.save();
    ctx.scale(dpr, dpr);
    const w = W / dpr;
    const h = H / dpr;

    // The camera image, dimmed right down. It is context, not the subject --
    // the subject is the population drawn over it.
    ctx.globalAlpha = 0.28;
    try {
      ctx.drawImage(this._source || this._video, 0, 0, w, h);
    } catch (err) { /* nothing to draw yet */ }
    ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(8,10,14,0.45)';
    ctx.fillRect(0, 0, w, h);

    // The LPLC2 population, in retinotopic order, each cell at its own place in
    // the visual field. Brightness is that cell's response.
    const cells = out.cells;
    const rx = w / CELLS_X;
    const ry = h / CELLS_Y;
    for (let c = 0; c < cells.length; c++) {
      const cx = ((c % CELLS_X) + 0.5) * rx;
      const cy = (((c / CELLS_X) | 0) + 0.5) * ry;
      const v = Math.min(1, cells[c] / 0.8);
      const r = Math.min(rx, ry) * (0.16 + 0.30 * v);
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, ${Math.round(170 - 90 * v)}, ${Math.round(80 - 60 * v)}, ${0.18 + 0.75 * v})`;
      ctx.fill();
    }

    // Ring the winning cell. Which one it is *is* the answer to "where".
    if (out.expansion > REPORT_FLOOR) {
      const c = out.peak;
      const cx = ((c % CELLS_X) + 0.5) * rx;
      const cy = (((c / CELLS_X) | 0) + 0.5) * ry;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.min(rx, ry) * 0.62, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255,255,255,0.75)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    ctx.restore();

    this._updateReadout(out);
  }

  _updateReadout(out) {
    const root = this.shadowRoot;
    const set = (id, text, cls) => {
      const el = root.getElementById(id);
      if (!el) return;
      el.textContent = text;
      el.className = `v${cls ? ` ${cls}` : ''}`;
    };
    set('exp', out.expansion.toFixed(2));
    const deg = (out.azimuth * 180) / Math.PI;
    set('az', out.expansion > REPORT_FLOOR
      ? `${deg > 0 ? 'right' : 'left'} ${Math.abs(deg).toFixed(0)}°`
      : '—');
    // The threshold is not enforced here. It is a property of the network, and
    // this readout is only saying which side of it the eye's output falls on.
    set('esc', out.expansion > 0.1 ? 'fires' : 'below threshold',
        out.expansion > 0.1 ? 'warn' : '');

    const note = root.getElementById('note');
    if (note) {
      note.innerHTML = out.selfMotion
        ? '<span class="warn">The camera itself is moving</span>, so the looming response is '
          + 'suppressed &mdash; the whole field is flowing one way, which is what a turn looks '
          + 'like and not what an approach looks like. Hold it still.'
        : 'Move your hand towards the camera. Slowly does nothing and waving sideways does '
          + 'nothing &mdash; the cell only answers to its own patch of sky expanding, which is '
          + 'what those four dendritic branches are for.';
    }
  }
}

customElements.define('housefly-eye-card', HouseFlyEyeCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'housefly-eye-card',
  name: 'HouseFly eye',
  description: 'Gives the fly a real looming detector, fed by a camera. Frames stay in the page.',
});

export { HouseFlyEyeCard, FOV_X };
