/**
 * HouseFly Custom Lovelace Card
 * 
 * Displays animated fly + compound eye ommatidia + brain + hunger
 * Pure vanilla JS (no build step required)
 */

class HouseFlyCard extends HTMLElement {
	constructor() {
		super();
		this.attachShadow({ mode: 'open' });
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
				}
				.header {
					display: flex;
					align-items: center;
					justify-content: space-between;
					margin-bottom: 16px;
				}
				.title {
					font-size: 20px;
					font-weight: bold;
				}
				.main-content {
					display: grid;
					grid-template-columns: 1fr 1fr;
					gap: 16px;
					margin-bottom: 16px;
				}
				.fly-container {
					display: flex;
					flex-direction: column;
					align-items: center;
					padding: 16px;
					background: rgba(0, 0, 0, 0.2);
					border-radius: 8px;
				}
				.fly-svg {
					width: 120px;
					height: 80px;
					margin-bottom: 8px;
					cursor: pointer;
				}
				.fly-svg:hover {
					opacity: 0.8;
				}
				.mode-badge {
					padding: 4px 12px;
					border-radius: 12px;
					font-size: 12px;
					font-weight: bold;
					text-transform: uppercase;
				}
				.mode-idle { background: #4a4a6e; }
				.mode-wander { background: #4a6e6e; }
				.mode-escape { background: #6e4a4a; }
				.ommatidia-container {
					padding: 16px;
					background: rgba(0, 0, 0, 0.2);
					border-radius: 8px;
				}
				.ommatidia-title {
					font-size: 14px;
					margin-bottom: 8px;
					opacity: 0.8;
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
					transition: background-color 0.3s;
				}
				.stats {
					display: flex;
					gap: 16px;
					margin-bottom: 16px;
					flex-wrap: wrap;
				}
				.stat {
					flex: 1;
					min-width: 120px;
					padding: 12px;
					background: rgba(0, 0, 0, 0.2);
					border-radius: 8px;
				}
				.stat-label {
					font-size: 12px;
					opacity: 0.7;
					margin-bottom: 4px;
				}
				.stat-value {
					font-size: 18px;
					font-weight: bold;
				}
				.hunger-bar {
					width: 100%;
					height: 8px;
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
				.actions {
					display: flex;
					gap: 8px;
				}
				.action-button {
					flex: 1;
					padding: 12px;
					background: var(--primary-color, #03a9f4);
					border: none;
					border-radius: 8px;
					color: white;
					font-weight: bold;
					cursor: pointer;
					transition: background 0.2s;
				}
				.action-button:hover {
					opacity: 0.9;
				}
				.action-button:active {
					transform: scale(0.98);
				}
				.feed-button {
					background: #10b981;
				}
				.vome-footer {
					margin-top: 12px;
					text-align: center;
					font-size: 11px;
					opacity: 0.4;
					letter-spacing: 0.02em;
				}
				.vome-footer a {
					color: inherit;
					text-decoration: none;
				}
				.vome-footer a:hover {
					opacity: 0.85;
					text-decoration: underline;
				}
			</style>
			<div class="housefly-card">
				<div class="header">
					<div class="title">🪰 HouseFly</div>
					<div id="mode-badge" class="mode-badge mode-idle">IDLE</div>
				</div>
				<div class="main-content">
					<div class="fly-container">
						<div class="fly-svg" id="fly-svg"></div>
						<div id="fly-status">Status</div>
					</div>
					<div class="ommatidia-container">
						<div class="ommatidia-title">👁️ Compound Eye</div>
						<div class="ommatidia-grid" id="ommatidia-grid"></div>
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
						<div class="hunger-bar">
							<div class="hunger-fill" id="hunger-fill" style="width: 0%"></div>
						</div>
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

		// Load fly SVG
		this.shadowRoot.getElementById('fly-svg').innerHTML = `
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80" width="120" height="80">
				<style>
					@keyframes wingFlap {
						0%, 100% { transform: rotate(0deg); opacity: 0.6; }
						50% { transform: rotate(-25deg); opacity: 0.9; }
					}
					@keyframes buzz {
						0%, 100% { transform: translate(0, 0); }
						25% { transform: translate(1px, -1px); }
						50% { transform: translate(-1px, 1px); }
						75% { transform: translate(1px, 1px); }
					}
					.wing-left { animation: wingFlap 0.15s infinite; transform-origin: 55px 35px; }
					.wing-right { animation: wingFlap 0.15s infinite 0.075s; transform-origin: 65px 35px; }
					.fly-body { animation: buzz 0.3s infinite; }
				</style>
				<g class="fly-body">
					<ellipse cx="60" cy="40" rx="8" ry="12" fill="#2a2a2a"/>
					<ellipse cx="60" cy="28" rx="6" ry="8" fill="#1a1a1a"/>
					<circle cx="60" cy="20" r="5" fill="#2a2a2a"/>
					<circle cx="57" cy="19" r="2.5" fill="#8b0000" opacity="0.8"/>
					<circle cx="63" cy="19" r="2.5" fill="#8b0000" opacity="0.8"/>
					<circle cx="56.5" cy="18.5" r="0.8" fill="#ff4444"/>
					<circle cx="62.5" cy="18.5" r="0.8" fill="#ff4444"/>
					<line x1="58" y1="16" x2="55" y2="12" stroke="#333" stroke-width="0.8"/>
					<line x1="62" y1="16" x2="65" y2="12" stroke="#333" stroke-width="0.8"/>
					<circle cx="55" cy="12" r="1" fill="#444"/>
					<circle cx="65" cy="12" r="1" fill="#444"/>
					<g class="wing-left">
						<ellipse cx="50" cy="32" rx="18" ry="10" fill="#e0e0ff" opacity="0.7" stroke="#9999cc" stroke-width="0.5"/>
					</g>
					<g class="wing-right">
						<ellipse cx="70" cy="32" rx="18" ry="10" fill="#e0e0ff" opacity="0.7" stroke="#9999cc" stroke-width="0.5"/>
					</g>
					<line x1="56" y1="45" x2="50" y2="52" stroke="#333" stroke-width="1"/>
					<line x1="60" y1="46" x2="58" y2="54" stroke="#333" stroke-width="1"/>
					<line x1="64" y1="45" x2="70" y2="52" stroke="#333" stroke-width="1"/>
				</g>
			</svg>
		`;

		// Initialize ommatidia grid
		const grid = this.shadowRoot.getElementById('ommatidia-grid');
		for (let i = 0; i < 256; i++) {
			const facet = document.createElement('div');
			facet.className = 'ommatidium';
			facet.dataset.index = i;
			grid.appendChild(facet);
		}

		// Add event listeners
		this.shadowRoot.getElementById('fly-svg').addEventListener('click', () => this.callService('poke'));
		this.shadowRoot.getElementById('poke-button').addEventListener('click', () => this.callService('poke'));
		this.shadowRoot.getElementById('feed-button').addEventListener('click', () => this.callService('feed'));
	}

	updateContent() {
		if (!this._hass || !this.config) return;

		const entityId = this.config.entity;
		const state = this._hass.states[entityId];
		if (!state) return;

		// Get related sensors
		const brainEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_brain');
		const hungerEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_hunger');
		const retinaEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_retina');
		const spikesEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_spikes');
		const modeEntity = entityId.replace('binary_sensor.fly_house_active', 'sensor.fly_house_mode');

		const brainState = this._hass.states[brainEntity];
		const hungerState = this._hass.states[hungerEntity];
		const retinaState = this._hass.states[retinaEntity];
		const spikesState = this._hass.states[spikesEntity];
		const modeState = this._hass.states[modeEntity];

		// Update mode badge
		const mode = modeState?.state || 'idle';
		const modeBadge = this.shadowRoot.getElementById('mode-badge');
		modeBadge.textContent = mode.toUpperCase();
		modeBadge.className = `mode-badge mode-${mode}`;

		// Update spikes
		this.shadowRoot.getElementById('spikes').textContent = spikesState?.state || '0';

		// Update hunger
		const hunger = hungerState ? parseInt(hungerState.state) : 0;
		this.shadowRoot.getElementById('hunger-value').textContent = `${hunger}%`;
		this.shadowRoot.getElementById('hunger-fill').style.width = `${hunger}%`;

		// Update energy
		const energy = state.attributes.energy || 0;
		this.shadowRoot.getElementById('energy').textContent = energy.toFixed(3);

		// Update fly status
		const hungerIcon = hunger > 80 ? '🍽️' : hunger > 50 ? '😋' : hunger > 20 ? '🙂' : '😌';
		this.shadowRoot.getElementById('fly-status').textContent = `${hungerIcon} ${mode}`;

		// Update ommatidia
		this.updateOmmatidia(retinaState);
	}

	updateOmmatidia(retinaState) {
		if (!retinaState || !retinaState.attributes.ommatidia_hex) return;

		const hexString = retinaState.attributes.ommatidia_hex;
		const grid = this.shadowRoot.getElementById('ommatidia-grid');
		const facets = grid.querySelectorAll('.ommatidium');

		for (let i = 0; i < Math.min(hexString.length, facets.length); i++) {
			const hexChar = hexString[i];
			const value = parseInt(hexChar, 16);
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
		return 5;
	}
}

customElements.define('housefly-card', HouseFlyCard);

window.customCards = window.customCards || [];
window.customCards.push({
	type: 'housefly-card',
	name: 'HouseFly Card',
	description: 'Displays animated fruit fly with compound eye, hunger, and brain activity',
	preview: true,
});
