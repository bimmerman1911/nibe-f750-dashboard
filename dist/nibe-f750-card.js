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
// F750 parameter IDs; myUplink unique IDs are `${device_id}-${parameter_id}`.
// References and compatibility notes: docs/discovery.md.
const points = {outdoor:['40004'],room:['40033'],hot_water:['40013','40014'],supply:['40008'],return:['40012'],exhaust_air:['40025'],leaving_air:['40026'],evaporator:['40020'],condenser:['40019'],compressor_frequency:['43136'],heater_power:['43084'],operation:['49994']};
export function discoverEntities(registry, deviceId) {
  const rows = registry.filter(e => e.platform === 'myuplink' && e.device_id === deviceId && !e.disabled_by);
  const find = (ids, domains) => {
    for (const id of ids) {
      const matches = rows.filter(e => domains.includes(e.entity_id.split('.')[0]) && String(e.unique_id).endsWith(`-${id}`));
      if(matches.length === 1) return matches[0].entity_id;
      if(matches.length > 1) return undefined;
    }
  };
  const entities = Object.fromEntries(Object.entries(points).map(([key,ids])=>[key,find(ids,['sensor','number','select'])]).filter(([,id])=>id));
  const controls = Object.fromEntries([['heating',find(['47011'],['number'])],['hot_water',find(['47041'],['select','number'])]].filter(([,id])=>id));
  return {entities,controls};
}
const css = `
:host{display:block;color:#203344;color-scheme:light;font-family:var(--paper-font-body1_-_font-family,Inter,system-ui,sans-serif);--primary-text-color:#203344;--secondary-text-color:#596d7d;--ha-card-background:#fff;--divider-color:#dce6eb}*{box-sizing:border-box}
ha-card{display:block;background:#fff;color:#203344;border:1px solid #dce6eb;border-radius:24px;overflow:hidden;box-shadow:0 12px 40px #243c4b08}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:28px 30px;border-bottom:1px solid #e5edf0;background:linear-gradient(115deg,#f5fbf9,#fff 70%)}.eyebrow{font-size:11px;letter-spacing:.17em;text-transform:uppercase;color:#487468;font-weight:700}h1{font-size:27px;font-weight:550;letter-spacing:-.04em;margin:7px 0}h2{font-size:16px;font-weight:600;margin:0}p{color:#596d7d;font-size:13px;line-height:1.6;margin:6px 0}.pill{display:inline-block;border:1px solid #b7ded2;background:#edf8f3;color:#24715b;border-radius:25px;padding:8px 12px;font-size:12px}.demo{color:#895a14;background:#fff8e9;border-color:#ebd8ae}
.body{padding:24px 30px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}.stat{padding:17px;border:1px solid #e0e9ed;border-radius:16px;background:#f8fafb}.label{color:#596d7d;font-size:12px}.value{font-size:27px;letter-spacing:-.04em;margin-top:10px}.unit{font-size:13px;color:#596d7d;margin-left:5px}.sub{font-size:11px;color:#596d7d;margin-top:6px}
.panel{border:1px solid #dce6eb;border-radius:18px;padding:20px;min-width:0}.heading{display:flex;justify-content:space-between;gap:10px;align-items:center}.tag{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#596d7d}.legend{display:flex;flex-wrap:wrap;gap:10px 22px;padding:14px 0 0;font-size:11px;color:#526777}.legend span{display:flex;gap:7px;align-items:center}.legend i{width:20px;height:3px;border-radius:4px;background:var(--line)}.scheme-scroll{overflow-x:auto;border-radius:12px;scrollbar-color:#adc8c2 #f1f6f5}.scheme-scroll:focus-visible{outline:2px solid #268b73;outline-offset:3px}.scroll-hint{display:none}svg{display:block;width:100%;min-width:820px;height:auto;margin:12px 0}svg text{font-family:inherit;fill:#203344;font-size:12px}svg .muted{fill:#596d7d;font-size:11px}svg .section-label{fill:#637886;font-size:10px;letter-spacing:1.6px;font-weight:600}svg .node{fill:#fff;stroke:#b5c8d1;stroke-width:1.5}svg .pipe{fill:none;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}svg .ref-high{stroke:#9171ba}svg .ref-low{stroke:#3d9c9a}svg .hot{stroke:#dd8051}svg .cold{stroke:#5a96bf}svg .air{stroke:#9db4bf;stroke-width:2;stroke-dasharray:5 5;fill:none}svg .flow{stroke-dasharray:3 14;stroke:#ffffffbb;stroke-width:2;animation:flow 3s linear infinite}svg .flow.paused{animation:none;stroke:transparent}@keyframes flow{to{stroke-dashoffset:-68}}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px 22px;border-top:1px solid #e5edf0;padding-top:18px}.metric{display:flex;flex-direction:column;gap:6px;font-size:12px}.metric span{color:#596d7d}.metric b{font-size:14px;font-weight:550}.controls{margin-top:18px}.control-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}label{display:block;font-size:12px;color:#596d7d;margin-bottom:8px}select,input,button{font:inherit;border:1px solid #cbdcde;border-radius:10px;background:#fff;color:#203344;padding:10px;max-width:100%}select,input{width:100%}button{cursor:pointer;background:#edf8f3;color:#216c57;white-space:nowrap}button:hover{background:#e0f1e9}button:disabled{opacity:.45;cursor:default}.row{display:flex;gap:8px}.notice{min-height:22px;font-size:12px;color:#216c57;margin-top:12px}.future{display:flex;gap:20px;align-items:center;justify-content:space-between;margin-top:18px;background:#f5f9fc;border:1px dashed #c8dce6;border-radius:16px;padding:18px}.future p{max-width:650px}.empty{padding:12px;border:1px dashed #cbdcde;border-radius:10px;font-size:12px;color:#596d7d}footer{padding-top:18px;color:#596d7d;font-size:11px;line-height:1.6}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #268b73;outline-offset:3px}
@media(max-width:700px){header,.body{padding:20px}.control-grid{grid-template-columns:1fr}.stats,.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.future{align-items:flex-start;flex-direction:column}h1{font-size:23px}.scroll-hint{display:block;font-size:11px}.heading{flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){svg .flow{animation:none}}
`;
export class NibeF750Card extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this._busy = false; }
  setConfig(config) {
    if (!config) throw new Error('Card configuration is required.');
    this._manual = config.entities !== undefined;
    this._controlOverrides = config.controls;
    this._selectedDevice = config.device_id;
    this.config = {title:'F750 · Energy overview', entities:{}, ...config};
    this._discoveryMessage = this._manual ? '' : 'Discovering your myUplink heat pump…';
    this._discovered = false;
    this.render();
    this.discover();
  }
  set hass(hass) {
    this._hass = hass;
    this.discover();
    const ids = [...Object.values(this.config?.entities || {}), ...Object.values(this.config?.controls || {})];
    const changed = !this._lastStates || ids.some(id => this._lastStates[id] !== hass.states[id]);
    this._lastStates = Object.fromEntries(ids.map(id => [id, hass.states[id]]));
    if (changed) this.render();
  }
  async discover(refresh = false) {
    if (!this.config || this._manual || !this._hass?.callWS || this._discovering || (this._discovered && !refresh)) return;
    this._discovering = true;
    const config = this.config;
    try {
      const [registry,devices] = await Promise.all([
        this._hass.callWS({type:'config/entity_registry/list'}),
        this._hass.callWS({type:'config/device_registry/list'}),
      ]);
      if(this.config !== config) return;
      const ids = new Set(registry.filter(e=>e.platform==='myuplink').map(e=>e.device_id));
      const candidates = devices.filter(d=>ids.has(d.id));
      this._devices = candidates;
      const f750 = candidates.filter(d=>/f\s*750/i.test(`${d.model || ''} ${d.name || ''}`));
      const selected = this._selectedDevice || config.device_id || (f750.length===1 ? f750[0].id : candidates.length===1 ? candidates[0].id : null);
      const device = candidates.find(d=>d.id===selected);
      this._selectedDevice = device?.id;
      const found = device ? discoverEntities(registry,device.id) : {entities:{},controls:{}};
      this.config = {...config,entities:found.entities,controls:{...found.controls,...this._controlOverrides}};
      this._discoveryMessage = !device ? (candidates.length ? 'Choose your heat pump below.' : 'No myUplink devices found. Set up the built-in myUplink integration, then retry.') : `${device.name_by_user || device.name || device.model || 'myUplink'} · ${Object.keys(found.entities).length} readings discovered. Missing readings may not be exposed or enabled.`;
      this._discovered = true;
    } catch {
      this._discoveryMessage = 'Discovery failed. Check your Home Assistant connection and registry access, then retry.';
      this._discovered = true;
    } finally {
      this._discovering = false;
      this.render();
    }
  }
  static getStubConfig() { return {type:'custom:nibe-f750-card'}; }
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
    if (!id) return `<div class="empty">${title}: ${this._manual ? 'map a writable myUplink entity to enable.' : 'no supported enabled myUplink control discovered.'}</div>`;
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
    const active = this.shadowRoot.activeElement;
    const drafts = active?.matches('input,select') ? [[active.id, active.value]] : [];
    const running = this.available(this.state('compressor_frequency')) && Number(this.state('compressor_frequency').state)>0;
    const flow = running ? 'flow' : 'flow paused';
    const mapped = Object.values(this.config.entities), available = mapped.filter(id=>this.available(this._hass?.states[id])).length;
    this.shadowRoot.innerHTML = `<style>${css}</style><ha-card>
      <header><div><div class="eyebrow">NIBE / Home energy</div><h1>${esc(this.config.title)}</h1><p>Exhaust-air heat pump · powered by myUplink</p></div><span class="pill ${this.config.demo?'demo':''}">${this.config.demo?'Demo data':`${available}/${mapped.length} readings available`}</span></header>
      <div class="body">${!this._manual ? `<div class="panel" style="margin-bottom:18px"><p>${esc(this._discoveryMessage)}</p>${this._devices?.length>1 ? `<label for="device">Heat pump</label><select id="device"><option value="">Choose a heat pump</option>${this._devices.map(d=>`<option value="${esc(d.id)}" ${d.id===(this._selectedDevice || this.config.device_id)?'selected':''}>${esc(d.name_by_user || d.name || d.model || d.id)}</option>`).join('')}</select>`:''}<button id="discover" style="margin-top:8px">Refresh discovery</button></div>`:''}<div class="stats">${['outdoor','room','hot_water','compressor_frequency'].map(k=>`<div class="stat"><div class="label">${readings[k][0]}</div><div class="value">${this.value(k)}<span class="unit">${this.available(this.state(k))?this.unit(k):''}</span></div><div class="sub">${k==='compressor_frequency'?'Variable-speed compressor':k==='hot_water'?'Domestic hot water':k==='outdoor'?'At your home':'Indoor comfort'}</div></div>`).join('')}</div>
      <section class="panel"><div class="heading"><h2>From recovered air to home comfort</h2><span class="tag">F750 · System overview</span></div><p>Refrigerant and heating water exchange heat at the condenser. The two fluids stay separate.</p>
      <div class="legend" aria-label="Circuit legend"><span><i style="--line:#9171ba"></i>High-pressure refrigerant</span><span><i style="--line:#3d9c9a"></i>Low-pressure refrigerant</span><span><i style="--line:#dd8051"></i>Heating supply</span><span><i style="--line:#5a96bf"></i>Heating return</span></div>
      <p class="scroll-hint">Swipe the diagram to follow the full system →</p>
      <div class="scheme-scroll" tabindex="0" role="region" aria-label="Combined circuit diagram; scroll horizontally on small screens">
      <svg viewBox="0 0 1000 440" role="img" aria-labelledby="scheme-title scheme-description">
      <title id="scheme-title">Combined F750 refrigerant and hydraulic circuits</title><desc id="scheme-description">Extract air transfers heat to the evaporator. Refrigerant flows through the compressor, condenser and expansion valve. The condenser transfers heat across separate fluid channels into heating water serving space heating and the hot water tank. Paths are conceptual; flow is not measured.</desc>
      <rect x="12" y="24" width="532" height="392" rx="18" fill="#f6faf9"/>
      <rect x="552" y="24" width="436" height="392" rx="18" fill="#faf8f5"/>
      <text class="section-label" x="34" y="52">REFRIGERANT / HEAT RECOVERY</text><text class="section-label" x="576" y="52">HYDRAULICS / HEAT DISTRIBUTION</text>
      <!-- Refrigerant loop terminates on the left side of the shared exchanger. -->
      <path class="pipe ref-low" d="M160 190V130H280"/>
      <path class="pipe ref-high" d="M340 130H466V190M466 270V350H322"/>
      <path class="pipe ref-low" d="M298 350H160V270"/>
      <path class="pipe ${flow}" d="M160 190V130H466V350H160V270"/>
      <!-- Water loop terminates on the right side: no shared fluid junction. -->
      <path class="pipe hot" d="M518 190V130H885V212M735 130V266"/>
      <path class="pipe cold" d="M885 260V374H518V270M735 334V374"/>
      <!-- Air side is separate from the closed refrigerant loop. -->
      <path class="air" d="M65 140V215H110M110 245H65V318"/>
      <path d="M105 210L113 215L105 220M60 310L65 318L70 310" fill="none" stroke="#9db4bf" stroke-width="2"/>
      <text x="36" y="100">Extract air</text><text class="muted" x="36" y="119">${this.value('exhaust_air')} ${this.unit('exhaust_air')}</text>
      <text x="36" y="342">Discharge air</text><text class="muted" x="36" y="361">${this.value('leaving_air')} ${this.unit('leaving_air')}</text>
      <rect class="node" x="112" y="190" width="96" height="80" rx="12"/>
      <path d="M127 205L143 218L127 231L143 244L127 257M191 205L175 218L191 231L175 244L191 257" fill="none" stroke="#67aaa6" stroke-width="2"/>
      <text x="225" y="229">Evaporator</text><text class="muted" x="225" y="249">BT16 · ${this.value('evaporator')} ${this.unit('evaporator')}</text>
      <circle class="node" cx="310" cy="130" r="30"/><path d="M299 143L325 130L299 117Z" fill="#9171ba"/>
      <text x="310" y="81" text-anchor="middle">Compressor</text><text class="muted" x="310" y="190" text-anchor="middle">${this.value('compressor_frequency')} ${this.unit('compressor_frequency')}</text>
      <path class="node" d="M298 338L322 362V338L298 362Z"/>
      <text class="muted" x="310" y="393" text-anchor="middle">Expansion valve</text>
      <!-- Condenser: two isolated channels and a thermal transfer interface. -->
      <rect class="node" x="440" y="190" width="104" height="80" rx="12"/>
      <path d="M466 190V270" stroke="#9171ba" stroke-width="5"/><path d="M518 190V270" stroke="#dd8051" stroke-width="5"/>
      <path d="M486 201L498 212L486 223L498 234L486 245L498 258" fill="none" stroke="#b5c8d1" stroke-width="2"/>
      <path d="M475 230H506L501 225M506 230L501 235" fill="none" stroke="#bd793e" stroke-width="1.5"/>
      <text x="492" y="96" text-anchor="middle">Condenser</text>
      <text class="muted" x="560" y="300">Heat transfer</text>
      <text class="muted" x="448" y="317" text-anchor="end">Liquid line · ${this.value('condenser')} ${this.unit('condenser')}</text>
      <!-- Auxiliary heater and distribution are illustrative, not valve telemetry. -->
      <rect class="node" x="592" y="109" width="65" height="42" rx="10"/><path d="M605 130H612L617 119L624 141L630 119L636 130H645" fill="none" stroke="#dd8051" stroke-width="2"/>
      <text x="624" y="81" text-anchor="middle">Auxiliary heater</text><text class="muted" x="624" y="176" text-anchor="middle">${this.value('heater_power')} ${this.unit('heater_power')}</text>
      <text x="833" y="105" text-anchor="middle">Supply · ${this.value('supply')} ${this.unit('supply')}</text>
      <rect class="node" x="833" y="212" width="104" height="48" rx="9"/>
      <path d="M850 221V251M867 221V251M884 221V251M901 221V251M918 221V251" stroke="#dd8051" stroke-width="4"/>
      <text x="885" y="190" text-anchor="middle">Space heating</text>
      <rect class="node" x="695" y="245" width="80" height="107" rx="22"/>
      <path class="pipe hot" d="M735 245V267Q763 280 735 291Q707 302 735 313"/><path class="pipe cold" d="M735 313V352"/>
      <text x="790" y="295">Hot water tank</text><text class="muted" x="790" y="315">${this.value('hot_water')} ${this.unit('hot_water')}</text>
      <text class="muted" x="878" y="398" text-anchor="middle">Return · ${this.value('return')} ${this.unit('return')}</text>
      </svg></div>
      <div class="metrics">${['exhaust_air','leaving_air','supply','return','electrical_power','cop','heater_power','operation'].map(k=>this.metric(k)).join('')}</div>
      <p class="sub" style="margin-top:16px">Conceptual connections · branch selection and water flow are not measured. Moving markers indicate compressor operation only.</p></section>
      <section class="panel controls"><div class="heading"><h2>Comfort controls</h2><span class="tag">Manual settings</span></div><p>Changes use your existing Home Assistant entities and require confirmation.</p><div class="control-grid">${this.control('heating','Heating adjustment')}${this.control('hot_water','Hot water mode')}</div><div class="notice" role="status" aria-live="polite"></div></section>
      <section class="future"><div><div class="eyebrow">On the roadmap</div><h2 style="margin-top:8px">Smarter heat. Better timing.</h2><p>Electricity prices, weather forecasts and measured efficiency will inform future compressor and auxiliary-heater optimization.</p></div><span class="pill demo">Smart control · planned</span></section>
      <footer>${this.config.demo?'Illustrative readings only. No connection to a real heat pump.':'Readings follow Home Assistant’s myUplink updates (typically every 60 seconds).'} Diagrams are conceptual, not installation schematics. COP is shown only when you map a measured or calculated entity; it is never inferred here.</footer></div></ha-card>`;
    for (const [id,value] of drafts) { const el=this.shadowRoot.getElementById(id); if(el) { el.value=value; el.focus(); } }
    this.shadowRoot.querySelectorAll('[data-apply]').forEach(b=>b.addEventListener('click',()=>this.apply(b.dataset.apply)));
    this.shadowRoot.getElementById('discover')?.addEventListener('click',()=>this.discover(true));
    this.shadowRoot.getElementById('device')?.addEventListener('change',e=>{this._selectedDevice=e.target.value;this.discover(true);});
  }
}
if (!customElements.get('nibe-f750-card')) customElements.define('nibe-f750-card', NibeF750Card);
window.customCards = window.customCards || [];
window.customCards.push({type:'nibe-f750-card',name:'NIBE F750 Dashboard',description:'Circuit diagrams and comfort controls using built-in myUplink entities.',preview:false});
