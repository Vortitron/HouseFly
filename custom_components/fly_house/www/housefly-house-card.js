/**
 * housefly-house-card -- the demo house as a floor plan, drawn from live state.
 *
 * A list of entity rows tells you what is on. It does not tell you that the
 * kitchen is next to the hallway, that somebody just walked from one to the
 * other, or that the fly is sitting in the bedroom. Those are spatial facts and
 * they want a spatial picture, and the fly's whole premise is that a house is a
 * place rather than a list -- the compass takes bearings to things, the
 * mushroom body learns which room smelled of what. A plan is the honest view of
 * that.
 *
 * Everything drawn here is read from Home Assistant state. The glow in a room
 * is that light's actual brightness attribute; the warmth of the floor is that
 * room's actual temperature sensor against the others; the figure is that
 * room's motion sensor. Nothing is animated on a timer for effect.
 *
 * Deliberately SVG rather than canvas: a floor plan is a handful of rectangles
 * that change slowly, the browser is better at that than a 60 fps repaint loop,
 * and it stays crisp on a phone.
 */

const ROOMS = [
  { id: 'kitchen', name: 'Kitchen', x: 0, y: 0, w: 52, h: 46 },
  { id: 'living_room', name: 'Living room', x: 52, y: 0, w: 48, h: 46 },
  { id: 'bedroom', name: 'Bedroom', x: 52, y: 46, w: 48, h: 36 },
  { id: 'hallway', name: 'Hallway', x: 0, y: 46, w: 52, h: 36 },
];

/* The front door, and the radar that watches the approach to it. The demo's
   simulated occupant walks in through here, which is why the radar sits at the
   hallway end and points out. */
const DOOR = { x: 4, y: 82, w: 18 };

const SVG_W = 100;
const SVG_H = 92;

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; }
  h2 { margin: 0 0 2px; font-size: 1.05rem; font-weight: 600; }
  .sub { margin: 0 0 12px; opacity: 0.7; font-size: 0.82rem; line-height: 1.45; }
  svg { width: 100%; height: auto; display: block; border-radius: 10px; background: #0b0d10; }
  .room { cursor: pointer; }
  .wall { fill: none; stroke: rgba(255,255,255,0.22); stroke-width: 0.6; }
  .label { fill: rgba(255,255,255,0.62); font-size: 3.1px; font-weight: 600;
           letter-spacing: 0.08px; pointer-events: none; }
  .temp { fill: rgba(255,255,255,0.4); font-size: 2.6px; pointer-events: none;
          font-variant-numeric: tabular-nums; }
  .legend { margin-top: 10px; font-size: 0.75rem; opacity: 0.6; line-height: 1.5; }
`;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

class HouseFlyHouseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._built = false;
  }

  setConfig(config) {
    this._config = { title: 'The house', ...config };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._paint();
  }

  getCardSize() { return 6; }

  _build() {
    this._built = true;
    const rooms = ROOMS.map((r) => `
      <g class="room" data-room="${r.id}">
        <rect id="floor-${r.id}" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}"
              fill="#12161d"/>
        <rect id="glow-${r.id}" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}"
              fill="url(#lamp)" opacity="0"/>
        <rect class="wall" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}"/>
        <text class="label" x="${r.x + 3}" y="${r.y + 6}">${r.name}</text>
        <text class="temp" id="temp-${r.id}" x="${r.x + 3}" y="${r.y + 10}"></text>
        <circle id="socket-${r.id}" cx="${r.x + r.w - 4}" cy="${r.y + 5}" r="1.5"
                fill="rgba(255,255,255,0.18)"/>
        <g id="person-${r.id}" opacity="0"
           transform="translate(${r.x + r.w / 2}, ${r.y + r.h / 2 + 4})">
          <circle cx="0" cy="-3.4" r="1.5" fill="#8ee6ff"/>
          <path d="M0 -1.9 L0 2.2 M-1.9 -0.4 L1.9 -0.4 M0 2.2 L-1.6 5 M0 2.2 L1.6 5"
                stroke="#8ee6ff" stroke-width="0.7" fill="none" stroke-linecap="round"/>
        </g>
      </g>`).join('');

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <h2>${this._config.title}</h2>
        <p class="sub">Every room here is fake and everything you can see is live state — the
          glow is that light's real brightness, the tint of the floor is its real temperature
          against the others. Tap a room to switch its light.</p>
        <svg viewBox="0 0 ${SVG_W} ${SVG_H}" role="img" aria-label="Floor plan of the demo house">
          <defs>
            <radialGradient id="lamp" cx="50%" cy="40%" r="70%">
              <stop offset="0%" stop-color="#ffd98a" stop-opacity="0.85"/>
              <stop offset="100%" stop-color="#ffb347" stop-opacity="0.05"/>
            </radialGradient>
            <linearGradient id="beam" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stop-color="#5ad7ff" stop-opacity="0.45"/>
              <stop offset="100%" stop-color="#5ad7ff" stop-opacity="0"/>
            </linearGradient>
          </defs>
          ${rooms}
          <polygon id="radar-beam" points="0,0" fill="url(#beam)" opacity="0"/>
          <rect x="${DOOR.x}" y="${DOOR.y - 0.6}" width="${DOOR.w}" height="1.2"
                fill="#0b0d10" stroke="rgba(255,255,255,0.35)" stroke-width="0.4"/>
          <text class="temp" x="${DOOR.x}" y="${DOOR.y + 4}">front door</text>
          <circle id="radar-dot" cx="${DOOR.x + DOOR.w / 2}" cy="${DOOR.y - 2}" r="1.1"
                  fill="#5ad7ff" opacity="0.5"/>
          <text class="temp" id="radar-range" x="${DOOR.x + DOOR.w + 3}" y="${DOOR.y - 1}"></text>
        </svg>
        <p class="legend" id="legend"></p>
      </ha-card>`;

    this.shadowRoot.querySelectorAll('.room').forEach((g) => {
      g.addEventListener('click', () => this._toggle(g.dataset.room));
    });
  }

  _toggle(room) {
    // The demo's lights carry a _2 suffix where an orphaned registry entry took
    // the plain slug, so resolve by whichever exists rather than guessing.
    const id = [`light.${room}`, `light.${room}_2`].find((e) => this._hass.states[e]);
    if (id) this._hass.callService('light', 'toggle', { entity_id: id });
  }

  _state(id) {
    return this._hass.states[id];
  }

  _paint() {
    const root = this.shadowRoot;
    const temps = [];
    for (const r of ROOMS) {
      const t = this._state(`sensor.${r.id}_temperature`);
      if (t) temps.push(parseFloat(t.state));
    }
    const lo = temps.length ? Math.min(...temps) : 0;
    const hi = temps.length ? Math.max(...temps) : 1;

    for (const r of ROOMS) {
      const light = this._state(`light.${r.id}`) || this._state(`light.${r.id}_2`);
      const glow = root.getElementById(`glow-${r.id}`);
      if (light && light.state === 'on') {
        const b = light.attributes.brightness;
        // A light that is on at brightness 1 is still on, so the floor of this
        // range matters more than the top: never let "on" render as "off".
        glow.setAttribute('opacity', (0.22 + 0.78 * clamp((b ?? 255) / 255, 0, 1)).toFixed(3));
      } else {
        glow.setAttribute('opacity', '0');
      }

      // Warmth of the floor, relative to the other rooms rather than absolute.
      // An absolute scale on four rooms spanning three degrees is a flat grey.
      const temp = this._state(`sensor.${r.id}_temperature`);
      const floor = root.getElementById(`floor-${r.id}`);
      if (temp && hi > lo) {
        const f = clamp((parseFloat(temp.state) - lo) / (hi - lo), 0, 1);
        floor.setAttribute('fill', `rgb(${(18 + 26 * f) | 0}, ${(22 + 8 * f) | 0}, ${(29 - 6 * f) | 0})`);
        root.getElementById(`temp-${r.id}`).textContent = `${parseFloat(temp.state).toFixed(1)}°`;
      }

      const socket = this._state(`switch.${r.id}_socket`);
      root.getElementById(`socket-${r.id}`).setAttribute(
        'fill', socket && socket.state === 'on' ? '#7dffa8' : 'rgba(255,255,255,0.18)');

      // Somebody is in the room if either source says so: the manual motion
      // toggle a visitor can press, or the simulated occupant walking its
      // circuit. Neither is more real than the other here -- they are both
      // template sensors -- and the plan should not care which.
      const here = [`binary_sensor.${r.id}_motion`, `binary_sensor.${r.id}_occupied`]
        .some((e) => { const st = this._state(e); return st && st.state === 'on'; });
      root.getElementById(`person-${r.id}`).setAttribute('opacity', here ? '1' : '0');
    }

    this._paintRadar();
    this._paintLegend();
  }

  /* The radar's beam, drawn at its actual reported range. This is the one part
     of the plan that is a measurement rather than a state: the cone is as long
     as the thing it can currently see is far away. */
  _paintRadar() {
    const root = this.shadowRoot;
    const range = this._state('sensor.radar_moving_distance');
    const beam = root.getElementById('radar-beam');
    const label = root.getElementById('radar-range');
    if (!range || Number.isNaN(parseFloat(range.state))) {
      beam.setAttribute('opacity', '0');
      label.textContent = '';
      return;
    }
    const cm = parseFloat(range.state);
    const present = cm < 450;
    // 500 cm of radar range drawn across 34 plan units of hallway.
    const reach = clamp((cm / 500) * 34, 2, 34);
    const ox = DOOR.x + DOOR.w / 2;
    const oy = DOOR.y - 2;
    const half = reach * 0.42;
    beam.setAttribute('points',
      `${ox},${oy} ${ox - half},${oy - reach} ${ox + half},${oy - reach}`);
    beam.setAttribute('opacity', present ? '0.95' : '0.35');
    label.textContent = present ? `${(cm / 100).toFixed(1)} m` : '';
  }

  _paintLegend() {
    const fly = this._state('sensor.housefly_mode');
    const escaping = this._state('binary_sensor.housefly_escaping');
    const goal = fly && fly.attributes.goal_entity;
    const bits = [];
    if (fly) bits.push(`The fly is <b>${fly.state}</b>`);
    if (escaping && escaping.state === 'on') bits.push('<b>and bolting</b>');
    else if (goal) bits.push(`heading for <b>${goal.split('.').pop().replace(/_/g, ' ')}</b>`);
    const legend = this.shadowRoot.getElementById('legend');
    if (legend) legend.innerHTML = bits.join(', ') || '';
  }
}

customElements.define('housefly-house-card', HouseFlyHouseCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'housefly-house-card',
  name: 'HouseFly house plan',
  description: 'The demo house as a floor plan, drawn from live state.',
});

export { HouseFlyHouseCard };
