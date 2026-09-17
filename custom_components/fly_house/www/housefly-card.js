/**
 * HouseFly Custom Lovelace Card
 * Animated fly + compound eye + sparking brain + hunger
 * Pure vanilla JS (no build step)
 */

class HouseFlyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._brainNodes = [];
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Please define an entity (binary_sensor.fly_house_active)');
    }
    this.config = config;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.updateContent();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        .housefly-card {
          padding: 16px;
          background: var(--ha-card-background, #1a1a2e);
          border-radius: 8px;
          color: var(--primary-text-color, #fff);
          overflow: hidden;
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 14px;
        }
        .title { font-size: 20px; font-weight: bold; }
        .main-content {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          margin-bottom: 12px;
        }
        @media (max-width: 520px) {
          .main-content { grid-template-columns: 1fr; }
        }
        .panel {
          padding: 12px;
          background: rgba(0, 0, 0, 0.25);
          border-radius: 8px;
        }
        .fly-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          min-height: 140px;
        }
        .fly-stage {
          width: 160px;
          height: 110px;
          position: relative;
          cursor: pointer;
        }
        .fly-stage svg { width: 100%; height: 100%; overflow: visible; }
        .mode-badge {
          padding: 4px 12px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: bold;
          text-transform: uppercase;
        }
        .mode-idle { background: #4a4a6e; }
        .mode-wander { background: #2d6a6a; }
        .mode-escape { background: #8b3a3a; animation: pulse 0.6s infinite; }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.65; }
        }
        .panel-title {
          font-size: 13px;
          opacity: 0.8;
          margin-bottom: 8px;
        }
        .ommatidia-grid {
          display: grid;
          grid-template-columns: repeat(16, 1fr);
          gap: 1px;
          background: #000;
          padding: 2px;
          border-radius: 4px;
        }
        .ommatidium {
          aspect-ratio: 1;
          border-radius: 50%;
          background: #222;
          transition: background-color 0.25s;
        }
        .brain-canvas {
          width: 100%;
          height: 110px;
          border-radius: 4px;
          background: radial-gradient(ellipse at center, #1e1e3a 0%, #0a0a14 100%);
        }
        .stats {
          display: flex;
          gap: 10px;
          margin-bottom: 12px;
          flex-wrap: wrap;
        }
        .stat {
          flex: 1;
          min-width: 100px;
          padding: 10px;
          background: rgba(0, 0, 0, 0.22);
          border-radius: 8px;
        }
        .stat-label { font-size: 11px; opacity: 0.7; margin-bottom: 2px; }
        .stat-value { font-size: 17px; font-weight: bold; }
        .hunger-bar {
          width: 100%;
          height: 7px;
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
          overflow: hidden;
          margin-top: 4px;
        }
        .hunger-fill {
          height: 100%;
          background: linear-gradient(90deg, #4ade80, #facc15, #ef4444);
          transition: width 0.3s;
        }
        .actions { display: flex; gap: 8px; }
        .action-button {
          flex: 1;
          padding: 12px;
          background: var(--primary-color, #03a9f4);
          border: none;
          border-radius: 8px;
          color: white;
          font-weight: bold;
          cursor: pointer;
        }
        .action-button:active { transform: scale(0.98); }
        .feed-button { background: #10b981; }
        .fly-status { margin-top: 6px; font-size: 13px; opacity: 0.85; }
        .vome-footer {
          margin-top: 12px;
          text-align: center;
          font-size: 11px;
          opacity: 0.4;
        }
        .vome-footer a { color: inherit; text-decoration: none; }
        .vome-footer a:hover { text-decoration: underline; opacity: 0.9; }

        /* Mode / hunger reactive fly animations */
        .fly-body { transform-origin: 60px 40px; }
        .wing-left, .wing-right { transform-box: fill-box; }
        .anim-idle .wing-left, .anim-idle .wing-right {
          animation: wingFlap 0.35s infinite;
        }
        .anim-wander .wing-left, .anim-wander .wing-right {
          animation: wingFlap 0.14s infinite;
        }
        .anim-wander .fly-body {
          animation: buzz 0.28s infinite, wander 2.4s ease-in-out infinite;
        }
        .anim-escape .wing-left, .anim-escape .wing-right {
          animation: wingFlap 0.08s infinite;
        }
        .anim-escape .fly-body {
          animation: buzz 0.12s infinite, panic 0.5s ease-in-out infinite;
        }
        .hunger-high .fly-body { filter: saturate(1.4) hue-rotate(-10deg); }
        .hunger-mid .fly-body { filter: saturate(1.1); }
        @keyframes wingFlap {
          0%, 100% { transform: rotate(0deg); opacity: 0.65; }
          50% { transform: rotate(-28deg); opacity: 0.95; }
        }
        .wing-right { animation-delay: 0.07s !important; }
        @keyframes buzz {
          0%, 100% { transform: translate(0, 0); }
          25% { transform: translate(1.5px, -1.5px); }
          50% { transform: translate(-1.5px, 1px); }
          75% { transform: translate(1px, 1.5px); }
        }
        @keyframes wander {
          0%, 100% { translate: 0 0; }
          33% { translate: 10px -6px; }
          66% { translate: -8px 4px; }
        }
        @keyframes panic {
          0%, 100% { translate: 0 0; rotate: 0deg; }
          25% { translate: 14px -10px; rotate: 8deg; }
          50% { translate: -12px 8px; rotate: -10deg; }
          75% { translate: 8px 10px; rotate: 5deg; }
        }
      </style>
      <div class="housefly-card">
        <div class="header">
          <div class="title">🪰 HouseFly</div>
          <div id="mode-badge" class="mode-badge mode-idle">IDLE</div>
        </div>
        <div class="main-content">
          <div class="panel fly-container">
            <div class="fly-stage anim-idle" id="fly-stage"></div>
            <div class="fly-status" id="fly-status">Status</div>
          </div>
          <div class="panel">
            <div class="panel-title">👁️ Compound eye</div>
            <div class="ommatidia-grid" id="ommatidia-grid"></div>
          </div>
          <div class="panel" style="grid-column: 1 / -1;">
            <div class="panel-title">🧠 Reservoir sparks</div>
            <canvas class="brain-canvas" id="brain-canvas" width="480" height="110"></canvas>
          </div>
        </div>
        <div class="stats">
          <div class="stat">
            <div class="stat-label">Spikes</div>
            <div class="stat-value" id="spikes">0</div>
          </div>
          <div class="stat">
            <div class="stat-label">Hunger</div>
            <div class="stat-value" id="hunger-value">0%</div>
            <div class="hunger-bar"><div class="hunger-fill" id="hunger-fill" style="width:0%"></div></div>
          </div>
          <div class="stat">
            <div class="stat-label">Energy</div>
            <div class="stat-value" id="energy">0.00</div>
          </div>
        </div>
        <div class="actions">
          <button class="action-button" id="poke-button">💥 Poke</button>
          <button class="action-button feed-button" id="feed-button">🍎 Feed</button>
        </div>
        <div class="vome-footer">
          <a href="https://vome.io" target="_blank" rel="noopener noreferrer">Away? Peek via Vome →</a>
        </div>
      </div>
    `;

    const stage = this.shadowRoot.getElementById('fly-stage');
    stage.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80">
        <g class="fly-body">
          <ellipse cx="60" cy="40" rx="9" ry="13" fill="#2a2a2a"/>
          <ellipse cx="60" cy="27" rx="7" ry="9" fill="#1a1a1a"/>
          <circle cx="60" cy="18" r="6" fill="#2a2a2a"/>
          <circle cx="56" cy="17" r="3" fill="#8b0000" opacity="0.85"/>
          <circle cx="64" cy="17" r="3" fill="#8b0000" opacity="0.85"/>
          <circle cx="55.5" cy="16.5" r="1" fill="#ff5555"/>
          <circle cx="63.5" cy="16.5" r="1" fill="#ff5555"/>
          <line x1="57" y1="13" x2="52" y2="7" stroke="#444" stroke-width="1"/>
          <line x1="63" y1="13" x2="68" y2="7" stroke="#444" stroke-width="1"/>
          <circle cx="52" cy="7" r="1.2" fill="#555"/>
          <circle cx="68" cy="7" r="1.2" fill="#555"/>
          <g class="wing-left">
            <ellipse cx="45" cy="30" rx="22" ry="12" fill="#c8d0ff" opacity="0.7" stroke="#8899cc" stroke-width="0.6"/>
          </g>
          <g class="wing-right">
            <ellipse cx="75" cy="30" rx="22" ry="12" fill="#c8d0ff" opacity="0.7" stroke="#8899cc" stroke-width="0.6"/>
          </g>
          <line x1="55" y1="48" x2="48" y2="58" stroke="#333" stroke-width="1.2"/>
          <line x1="60" y1="50" x2="58" y2="62" stroke="#333" stroke-width="1.2"/>
          <line x1="65" y1="48" x2="72" y2="58" stroke="#333" stroke-width="1.2"/>
        </g>
      </svg>
    `;

    const grid = this.shadowRoot.getElementById('ommatidia-grid');
    for (let i = 0; i < 256; i++) {
      const facet = document.createElement('div');
      facet.className = 'ommatidium';
      grid.appendChild(facet);
    }

    this._initBrainNodes();
    this._drawBrain(0, 0);

    stage.addEventListener('click', () => this.callService('poke'));
    this.shadowRoot.getElementById('poke-button').addEventListener('click', () => this.callService('poke'));
    this.shadowRoot.getElementById('feed-button').addEventListener('click', () => this.callService('feed'));
  }

  _initBrainNodes() {
    this._brainNodes = [];
    const n = 28;
    for (let i = 0; i < n; i++) {
      this._brainNodes.push({
        x: 20 + Math.random() * 440,
        y: 15 + Math.random() * 80,
        r: 2 + Math.random() * 2.5,
        phase: Math.random() * Math.PI * 2,
      });
    }
  }

  _drawBrain(spikes, energy) {
    const canvas = this.shadowRoot.getElementById('brain-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const activity = Math.min(1, (Number(spikes) || 0) / 80 + (Number(energy) || 0));
    const nodes = this._brainNodes;
    const t = Date.now() / 1000;

    // edges
    ctx.lineWidth = 0.8;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d = Math.hypot(dx, dy);
        if (d < 90) {
          const pulse = 0.15 + 0.55 * activity * (0.5 + 0.5 * Math.sin(t * 4 + a.phase + b.phase));
          ctx.strokeStyle = `rgba(120, 200, 255, ${pulse * (1 - d / 90)})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }

    // nodes
    for (const n of nodes) {
      const glow = 0.4 + 0.6 * activity * (0.5 + 0.5 * Math.sin(t * 6 + n.phase));
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + glow * 2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(80, 220, 255, ${0.15 + glow * 0.35})`;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(200, 240, 255, ${0.55 + glow * 0.45})`;
      ctx.fill();
    }

    if (!this._brainAnim) {
      this._brainAnim = true;
      const tick = () => {
        if (!this.isConnected) {
          this._brainAnim = false;
          return;
        }
        const spikesEl = this.shadowRoot.getElementById('spikes');
        const energyEl = this.shadowRoot.getElementById('energy');
        const s = spikesEl ? parseFloat(spikesEl.textContent) || 0 : 0;
        const e = energyEl ? parseFloat(energyEl.textContent) || 0 : 0;
        this._drawBrain(s, e);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  }

  updateContent() {
    if (!this._hass || !this.config) return;

    const entityId = this.config.entity;
    const state = this._hass.states[entityId];
    if (!state) return;

    const brainEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_brain');
    const hungerEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_hunger');
    const retinaEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_retina');
    const spikesEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_spikes');
    const modeEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_mode');

    const hungerState = this._hass.states[hungerEntity];
    const retinaState = this._hass.states[retinaEntity];
    const spikesState = this._hass.states[spikesEntity];
    const modeState = this._hass.states[modeEntity];

    const mode = (modeState?.state || 'idle').toLowerCase();
    const modeBadge = this.shadowRoot.getElementById('mode-badge');
    modeBadge.textContent = mode.toUpperCase();
    modeBadge.className = `mode-badge mode-${mode}`;

    const spikes = spikesState?.state || '0';
    this.shadowRoot.getElementById('spikes').textContent = spikes;

    const hunger = hungerState ? parseInt(hungerState.state, 10) : 0;
    this.shadowRoot.getElementById('hunger-value').textContent = `${hunger}%`;
    this.shadowRoot.getElementById('hunger-fill').style.width = `${hunger}%`;

    const energy = state.attributes.energy || 0;
    this.shadowRoot.getElementById('energy').textContent = Number(energy).toFixed(3);

    const hungerIcon = hunger > 80 ? '🍽️' : hunger > 50 ? '😋' : hunger > 20 ? '🙂' : '😌';
    this.shadowRoot.getElementById('fly-status').textContent = `${hungerIcon} ${mode}`;

    const stage = this.shadowRoot.getElementById('fly-stage');
    const hungerClass = hunger > 70 ? 'hunger-high' : hunger > 40 ? 'hunger-mid' : '';
    const anim = mode === 'escape' ? 'anim-escape' : mode === 'wander' ? 'anim-wander' : 'anim-idle';
    stage.className = `fly-stage ${anim} ${hungerClass}`.trim();

    this.updateOmmatidia(retinaState);
  }

  updateOmmatidia(retinaState) {
    if (!retinaState || !retinaState.attributes.ommatidia_hex) return;
    const hexString = retinaState.attributes.ommatidia_hex;
    const facets = this.shadowRoot.getElementById('ommatidia-grid').querySelectorAll('.ommatidium');
    for (let i = 0; i < Math.min(hexString.length, facets.length); i++) {
      const value = parseInt(hexString[i], 16);
      const brightness = (value / 15) * 255;
      facets[i].style.backgroundColor = `rgb(${brightness}, ${brightness * 0.9}, ${brightness * 0.7})`;
    }
  }

  callService(service) {
    if (!this._hass) return;
    const serviceData = service === 'feed'
      ? { amount: 0.3, food_type: 'sugar' }
      : { strength: 1.0 };
    this._hass.callService('fly_house', service, serviceData);
  }

  getCardSize() {
    return 7;
  }
}

customElements.define('housefly-card', HouseFlyCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'housefly-card',
  name: 'HouseFly Card',
  description: 'Animated fruit fly with compound eye, sparking brain, and hunger',
  preview: true,
});
