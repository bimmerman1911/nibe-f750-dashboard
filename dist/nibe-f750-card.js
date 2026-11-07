/* NIBE F750 Dashboard — MIT license. Uses Home Assistant's built-in myUplink entities. */
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const readings = {
  outdoor: ['Outdoor', '°C'], room: ['Indoor', '°C'], hot_water: ['Hot water', '°C'],
  supply: ['Heating supply', '°C'], return: ['Heating return', '°C'],
  exhaust_air: ['Extract air', '°C'], leaving_air: ['Discharge air', '°C'],
  evaporator: ['Evaporator', '°C'], condenser: ['Condenser', '°C'],
  compressor_frequency: ['Compressor', 'Hz'], heater_power: ['Auxiliary heater', 'kW'],
  electrical_power: ['Electrical input', 'kW'], cop: ['COP', ''], electricity_price: ['Electricity price', ''],
  operation: ['Operating mode', ''],
};
const css = `
:host{display:block;color:var(--primary-text-color,#e6edf5);font-family:var(--paper-font-body1_-_font-family,Inter,system-ui,sans-serif)}*{box-sizing:border-box}
ha-card{display:block;background:var(--ha-card-background,#101b29);border:1px solid var(--divider-color,#293847);border-radius:24px;overflow:hidden;box-shadow:0 12px 36px #0002}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:28px 30px;border-bottom:1px solid #8199ac25}.eyebrow{font-size:11px;letter-spacing:.17em;text-transform:uppercase;color:#83a0b6;font-weight:700}h1{font-size:27px;font-weight:550;letter-spacing:-.04em;margin:7px 0}h2{font-size:16px;font-weight:550;margin:0}p{color:var(--secondary-text-color,#9aafc2);font-size:13px;line-height:1.6;margin:6px 0}.pill{display:inline-block;border:1px solid #729b9640;background:#52cdb312;color:#68d9bf;border-radius:25px;padding:8px 12px;font-size:12px}.demo{color:#ffce86;background:#ffce8610;border-color:#ffce8650}
.body{padding:24px 30px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}.stat{padding:17px;border:1px solid #8199ac25;border-radius:16px;background:#8199ac06}.label{color:var(--secondary-text-color,#9aafc2);font-size:12px}.value{font-size:27px;letter-spacing:-.04em;margin-top:10px}.unit{font-size:13px;color:#8da6bc;margin-left:5px}.sub{font-size:11px;color:#8da6bc;margin-top:6px}
.circuits{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel{border:1px solid #8199ac25;border-radius:18px;padding:20px;min-width:0}.heading{display:flex;justify-content:space-between;gap:10px;align-items:center}.tag{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#8da6bc}svg{display:block;width:100%;height:auto;margin:12px 0}svg text{font-family:inherit;fill:var(--primary-text-color,#e6edf5);font-size:11px}svg .muted{fill:#91a8bb;font-size:10px}svg .node{fill:var(--ha-card-background,#101b29);stroke:#516b80;stroke-width:1.5}svg .hot{stroke:#f5a06a}svg .cold{stroke:#61b7e8}svg .pipe{fill:none;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}svg .flow{stroke-dasharray:3 14;stroke:#ffffff88;stroke-width:2;animation:flow 3s linear infinite}svg .flow.paused{animation:none;stroke:transparent}@keyframes flow{to{stroke-dashoffset:-68}}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;border-top:1px solid #8199ac25;padding-top:14px}.metric{display:flex;justify-content:space-between;gap:8px;font-size:12px}.metric span{color:#91a8bb}.controls{margin-top:18px}.control-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}label{display:block;font-size:12px;color:var(--secondary-text-color,#9aafc2);margin-bottom:8px}select,input,button{font:inherit;border:1px solid #8199ac40;border-radius:10px;background:var(--ha-card-background,#101b29);color:inherit;padding:10px;max-width:100%}select,input{width:100%}button{cursor:pointer;background:#5ad0b71a;color:#70ddc4;white-space:nowrap}button:disabled{opacity:.45;cursor:default}.row{display:flex;gap:8px}.notice{min-height:22px;font-size:12px;color:#8edac7;margin-top:12px}.future{display:flex;gap:20px;align-items:center;justify-content:space-between;margin-top:18px;background:#64b7f408;border:1px dashed #64b7f440;border-radius:16px;padding:18px}.future p{max-width:650px}.empty{padding:12px;border:1px dashed #8199ac40;border-radius:10px;font-size:12px;color:#9aafc2}footer{padding-top:18px;color:#8da6bc;font-size:11px;line-height:1.6}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #6ddfc5;outline-offset:3px}
@media(max-width:700px){header,.body{padding:20px}.circuits,.control-grid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.future{align-items:flex-start;flex-direction:column}h1{font-size:23px}}@media(prefers-reduced-motion:reduce){svg .flow{animation:none}}
`;

export class NibeF750Card extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this._busy = false; }
  setConfig(config) {
    if (!config || !config.entities || typeof config.entities !== 'object') throw new Error('Configure entities using your Home Assistant myUplink entity IDs.');
    this.config = {title:'F750 · Energy overview', ...config};
    this.render();
  }
  set hass(hass) {
    this._hass = hass;
    const ids = [...Object.values(this.config?.entities || {}), ...Object.values(this.config?.controls || {})];
    const changed = !this._lastStates || ids.some(id => this._lastStates[id] !== hass.states[id]);
    this._lastStates = Object.fromEntries(ids.map(id => [id, hass.states[id]]));
    if (changed) this.render();
  }
  getCardSize() { return 12; }
  getGridOptions() { return {columns:24, min_columns:6, rows:12}; }
  state(key) { return this._hass?.states[this.config?.entities?.[key]]; }
  available(s) { return !!s && !['unknown','unavailable',''].includes(s.state); }
  value(key) {
    const s = this.state(key);
    if (!this.available(s)) return '—';
    const n = Number(s.state);
    return esc(Number.isFinite(n) ? new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(n) : s.state);
  }
  unit(key) { return esc(this.state(key)?.attributes?.unit_of_measurement ?? readings[key][1]); }
  metric(key) { return `<div class="metric"><span>${readings[key][0]}</span><b>${this.value(key)} ${this.available(this.state(key)) ? this.unit(key) : ''}</b></div>`; }
  control(key, title) {
    const id = this.config.controls?.[key], s = this._hass?.states[id];
    if (!id) return `<div class="empty">${title}: map a writable myUplink entity to enable.</div>`;
    const domain = id.split('.')[0];
    if (!['number','select'].includes(domain) || !this.available(s)) return `<div class="empty">${title}: entity unavailable or unsupported (use number/select).</div>`;
    const a = s.attributes;
    const field = domain === 'select' ? `<select id="${key}" aria-label="${title}">${(a.options || []).map(o => `<option value="${esc(o)}" ${o===s.state?'selected':''}>${esc(o)}</option>`).join('')}</select>` : `<input id="${key}" aria-label="${title}" type="number" value="${esc(s.state)}" min="${esc(a.min ?? '')}" max="${esc(a.max ?? '')}" step="${esc(a.step ?? 'any')}">`;
    return `<div><label for="${key}">${title}${a.unit_of_measurement ? ` · ${esc(a.unit_of_measurement)}`:''}</label><div class="row">${field}<button data-apply="${key}" ${this._busy?'disabled':''}>Apply</button></div></div>`;
  }
  async apply(key) {
    if (this._busy) return;
    const id = this.config.controls?.[key], s = this._hass?.states[id];
    if (!this.available(s)) return;
    const domain = id.split('.')[0], input = this.shadowRoot.getElementById(key);
    if (!input || !['number','select'].includes(domain)) return;
    const raw = input.value, value = Number(raw);
    if (domain==='number' && (raw.trim()==='' || !Number.isFinite(value) || !input.checkValidity())) { this.notice('Enter a valid value within the entity limits.'); return; }
    if (domain==='select' && !(s.attributes.options || []).includes(raw)) return;
    if (!window.confirm(`Set ${s.attributes.friendly_name || id} to ${raw}? This changes the heat pump setting.`)) return;
    this._busy = true;
    this.shadowRoot.querySelectorAll('[data-apply]').forEach(b=>b.disabled=true);
    try {
      await this._hass.callService(domain, domain==='number'?'set_value':'select_option', {entity_id:id, ...(domain==='number'?{value}:{option:raw})});
      this.notice(this.config.demo ? 'Demo setting updated. No heat pump is connected.' : 'Command sent. Waiting for the next myUplink update.');
    } catch { this.notice('Setting could not be sent. Check entity availability, permissions, and your myUplink subscription.'); }
    finally { this._busy=false; this.shadowRoot.querySelectorAll('[data-apply]').forEach(b=>b.disabled=false); }
  }
  notice(message) { this.shadowRoot.querySelector('[role="status"]').textContent = message; }
  render() {
    if (!this.config) return;
    // Preserve an in-progress setting while cloud readings refresh.
    const drafts = [...this.shadowRoot.querySelectorAll('input,select')].map(e=>[e.id,e.value]);
    const running = this.available(this.state('compressor_frequency')) && Number(this.state('compressor_frequency').state)>0;
    const flow = running ? 'flow' : 'flow paused';
    const mapped = Object.values(this.config.entities), available = mapped.filter(id=>this.available(this._hass?.states[id])).length;
    this.shadowRoot.innerHTML = `<style>${css}</style><ha-card>
      <header><div><div class="eyebrow">NIBE / Home energy</div><h1>${esc(this.config.title)}</h1><p>Exhaust-air heat pump · powered by myUplink</p></div><span class="pill ${this.config.demo?'demo':''}">${this.config.demo?'Demo data':`${available}/${mapped.length} readings available`}</span></header>
      <div class="body"><div class="stats">${['outdoor','room','hot_water','compressor_frequency'].map(k=>`<div class="stat"><div class="label">${readings[k][0]}</div><div class="value">${this.value(k)}<span class="unit">${this.available(this.state(k))?this.unit(k):''}</span></div><div class="sub">${k==='compressor_frequency'?'Variable-speed compressor':k==='hot_water'?'Domestic hot water':k==='outdoor'?'At your home':'Indoor comfort'}</div></div>`).join('')}</div>
      <div class="circuits"><section class="panel"><div class="heading"><h2>Refrigerant circuit</h2><span class="tag">Heat recovery</span></div><p>Recovering energy from your home’s extract air</p>
      <svg viewBox="0 0 420 265" role="img" aria-label="Conceptual refrigerant loop: evaporator, compressor, condenser, expansion valve"><path class="pipe hot" d="M120 72H310V199H210"/><path class="pipe cold" d="M210 199H105V72H120"/><path class="pipe ${flow}" d="M105 72H310V199H105Z"/>
      <rect class="node" x="57" y="103" width="96" height="64" rx="12"/><text x="105" y="129" text-anchor="middle">Evaporator</text><text class="muted" x="105" y="148" text-anchor="middle">${this.value('evaporator')} ${this.unit('evaporator')}</text>
      <circle class="node" cx="210" cy="72" r="35"/><path d="M197 83L224 72L197 61Z" fill="#f5a06a"/><text x="210" y="20" text-anchor="middle">Compressor · ${this.value('compressor_frequency')} ${this.unit('compressor_frequency')}</text>
      <rect class="node" x="263" y="103" width="96" height="64" rx="12"/><text x="311" y="129" text-anchor="middle">Condenser</text><text class="muted" x="311" y="148" text-anchor="middle">${this.value('condenser')} ${this.unit('condenser')}</text>
      <path class="node" d="M194 187L226 211V187L194 211Z"/><text class="muted" x="210" y="240" text-anchor="middle">Expansion valve</text></svg>
      <div class="metrics">${['exhaust_air','leaving_air','electrical_power','cop'].map(k=>this.metric(k)).join('')}</div></section>
      <section class="panel"><div class="heading"><h2>Hydraulic circuit</h2><span class="tag">Home comfort</span></div><p>Heat distribution & domestic hot water</p>
      <svg viewBox="0 0 420 265" role="img" aria-label="Conceptual hydraulic circuit from heat pump to space heating and hot water tank"><path class="pipe hot" d="M100 95H310V117M215 95V165"/><path class="pipe cold" d="M310 155V214H100V168M215 203V214"/><path class="pipe ${flow}" d="M100 95H310V214H100Z"/>
      <rect class="node" x="49" y="91" width="102" height="81" rx="12"/><text x="100" y="124" text-anchor="middle">Heat pump</text><text class="muted" x="100" y="144" text-anchor="middle">NIBE F750</text>
      <rect class="node" x="266" y="115" width="89" height="43" rx="7"/><path d="M282 123V150M296 123V150M310 123V150M324 123V150M338 123V150" stroke="#f5a06a" stroke-width="3"/><text x="310" y="65" text-anchor="middle">Space heating</text>
      <rect class="node" x="187" y="154" width="56" height="59" rx="15"/><path d="M198 167Q234 174 198 184Q234 195 198 201" fill="none" stroke="#f5a06a" stroke-width="2"/><text class="muted" x="215" y="243" text-anchor="middle">Hot water · ${this.value('hot_water')} ${this.unit('hot_water')}</text>
      <text x="185" y="79" text-anchor="middle">${this.value('supply')} ${this.unit('supply')}</text><text class="muted" x="105" y="240" text-anchor="middle">Return ${this.value('return')} ${this.unit('return')}</text></svg>
      <div class="metrics">${['supply','return','heater_power','operation'].map(k=>this.metric(k)).join('')}</div></section></div>
      <section class="panel controls"><div class="heading"><h2>Comfort controls</h2><span class="tag">Manual settings</span></div><p>Changes use your existing Home Assistant entities and require confirmation.</p><div class="control-grid">${this.control('heating','Heating adjustment')}${this.control('hot_water','Hot water mode')}</div><div class="notice" role="status" aria-live="polite"></div></section>
      <section class="future"><div><div class="eyebrow">On the roadmap</div><h2 style="margin-top:8px">Smarter heat. Better timing.</h2><p>Electricity prices, weather forecasts and measured efficiency will inform future compressor and auxiliary-heater optimization.</p></div><span class="pill demo">Smart control · planned</span></section>
      <footer>${this.config.demo?'Illustrative readings only. No connection to a real heat pump.':'Readings follow Home Assistant’s myUplink updates (typically every 60 seconds).'} Diagrams are conceptual, not installation schematics. COP is shown only when you map a measured or calculated entity; it is never inferred here.</footer></div></ha-card>`;
    for (const [id,value] of drafts) { const el=this.shadowRoot.getElementById(id); if(el) el.value=value; }
    this.shadowRoot.querySelectorAll('[data-apply]').forEach(b=>b.addEventListener('click',()=>this.apply(b.dataset.apply)));
  }
}
if (!customElements.get('nibe-f750-card')) customElements.define('nibe-f750-card', NibeF750Card);
window.customCards = window.customCards || [];
window.customCards.push({type:'nibe-f750-card',name:'NIBE F750 Dashboard',description:'Circuit diagrams and comfort controls using built-in myUplink entities.',preview:false});
