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
  condenser_water_out: ['Condenser water outlet', '°C'], air_flow: ['Extract airflow', ''],
  reference_air_flow: ['Reference airflow', ''],
  hot_water_charge: ['Hot water control', '°C'], hot_gas: ['Hot gas', '°C'], suction: ['Suction gas', '°C'],
  heating_supply: ['Heating supply after buffer', '°C'], heating_return: ['Heating return after buffer', '°C'], heater_out: ['Water after immersion heater', '°C'],
};
// F750 parameter IDs; myUplink unique IDs are `${device_id}-${parameter_id}`.
// References and compatibility notes: docs/discovery.md.
const points = {outdoor:['40004'],room:['40033'],hot_water:['40013'],supply:['40008'],return:['40012'],exhaust_air:['40025'],leaving_air:['40026'],evaporator:['40020'],condenser:['40019'],compressor_frequency:['43136'],heater_power:['43084'],operation:['49994'],condenser_water_out:['40017'],air_flow:['40050'],reference_air_flow:['43124'],hot_water_charge:['40014'],hot_gas:['40018'],suction:['40022'],heating_supply:['40047'],heating_return:['40048'],heater_out:[]};
// API names can vary from the older F-series register catalog. Match only
// explicit measurement names/BT designations, scoped to the selected device.
const aliases = {
  outdoor: [/(?:^| )outdoor temperature(?: bt1)?$/, /(?:^| )bt1(?: outdoor temperature)?$/],
  room: [/(?:^| )(?:room|indoor) temperature(?: bt50)?$/, /(?:^| )bt50(?: room temp(?:erature)?(?: s1)?)?$/],
  hot_water: [/(?:^| )hot water (?:top|temperature top)(?: bt7)?$/, /(?:^| )bt7(?: hw top)?$/],
  supply: [/(?:^| )(?:supply|flow) (?:line )?temp(?:erature)?(?: (?:s1|bt2))?$/, /(?:^| )bt2(?: supply temp(?:erature)? s1)?$/],
  return: [/(?:^| )return (?:line )?temp(?:erature)?(?: bt3)?$/, /(?:^| )bt3(?: return temp(?:erature)?)?$/],
  exhaust_air: [/(?:^| )(?:exhaust|extract) air (?:temp(?:erature)?)(?: (?:1|bt20))?$/, /(?:^| )bt20$/],
  leaving_air: [/(?:^| )(?:vented|discharge|leaving) air temp(?:erature)?(?: (?:1|bt21))?$/, /(?:^| )bt21$/],
  evaporator: [/(?:^| )evaporator temp(?:erature)?(?: bt16)?$/, /(?:^| )bt16$/],
  condenser: [/(?:^| )liquid line(?: temp(?:erature)?)?(?: bt15)?$/, /(?:^| )bt15$/],
  compressor_frequency: [/(?:^| )(?:current|actual) compressor frequency$/, /(?:^| )compressor frequency(?: actual)?$/],
  heater_power: [/(?:^| )(?:internal )?(?:electrical addition|auxiliary heater|additional heater) power$/, /(?:^| )int el add power$/],
  operation: [/(?:^| )(?:current priority|priority|operating mode)$/],
  condenser_water_out: [/(?:^| )bt12 (?:condensor|condenser) out$/, /(?:^| )(?:condenser|condensor) (?:out|outlet|water outlet|outlet temperature)(?: bt12)?$/],
  air_flow: [/(?:^| )bs1 air flow$/, /(?:^| )(?:extract|exhaust) air ?flow$/],
  reference_air_flow: [/(?:^| )reference air speed sensor$/, /(?:^| )reference air ?flow$/, /(?:^| )air ?flow (?:ref|reference)$/],
  hot_water_charge: [/(?:^| )hot water (?:charging|control)(?: bt6)?$/, /(?:^| )bt6 hw load$/],
  hot_gas: [/(?:^| )(?:bt14 )?hot gas temp(?:erature)?(?: bt14)?$/],
  suction: [/(?:^| )(?:bt17 )?suction(?: gas)?(?: temp(?:erature)?)?(?: bt17)?$/],
  heating_supply: [/(?:^| )bt61 supply radiator temp$/, /(?:^| )(?:heating medium flow|supply temperature) after buffer(?: vessel)?(?: bt61)?$/, /(?:^| )bt61$/],
  heating_return: [/(?:^| )bt62 return radiator temp$/, /(?:^| )(?:heating medium return|return temperature) after buffer(?: vessel)?(?: bt62)?$/, /(?:^| )bt62$/],
  heater_out: [/(?:^| )bt63$/, /(?:^| )(?:heating medium supply|supply temperature) after (?:immersion|inline) heater(?: bt63)?$/],
};
const normalize = text => String(text || '').toLowerCase().replace(/[\u00ad]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
export function discoverEntities(registry, deviceId, states = {}) {
  const rows = registry.filter(e => e.platform === 'myuplink' && e.device_id === deviceId && !e.disabled_by);
  const find = (ids, domains) => {
    for (const id of ids) {
      const matches = rows.filter(e => domains.includes(e.entity_id.split('.')[0]) && String(e.unique_id).endsWith(`-${id}`));
      if(matches.length === 1) return matches[0].entity_id;
      if(matches.length > 1) return undefined;
    }
  };
  const entities = Object.fromEntries(Object.entries(points).map(([key,ids])=>{
    const byId = find(ids,['sensor','number','select']);
    if(byId) return [key,byId];
    const matches = rows.filter(e=>e.entity_id.startsWith('sensor.') && !/-raw$/.test(e.unique_id) &&
      !(key==='compressor_frequency' && [e.original_name,e.name,states[e.entity_id]?.attributes?.friendly_name,e.entity_id.slice(7)].some(name=>/\b(target|request|requested|min|max|minimum|maximum)\b/.test(normalize(name)))) &&
      [e.original_name,e.name,states[e.entity_id]?.attributes?.friendly_name,e.entity_id.slice(7)].some(name=>
        (aliases[key] || []).some(pattern=>pattern.test(normalize(name)))));
    return [key,matches.length===1 ? matches[0].entity_id : undefined];
  }).filter(([,id])=>id));
  const controls = Object.fromEntries([['heating',find(['47011'],['number'])],['hot_water',find(['47041'],['select','number'])]].filter(([,id])=>id));
  return {entities,controls};
}
// Owner-supplied empirical power model: f in Hz, BT12 in °C, result in kW.
// Condenser heat is derived independently from air-side Q + modeled P;
// corrupt liquid-flow readings, reported power and history are never used.
export function calculateHeat(states, entities) {
  const read = (key,kind) => {
    const s=states[entities[key]];
    if(!s || String(s.state ?? '').trim()==='' || ['unknown','unavailable'].includes(s.state)) return null;
    const n=Number(s.state), unit=String(s.attributes?.unit_of_measurement || '').toLowerCase().replace(/\s/g,'').replace(/³/g,'3');
    if(!Number.isFinite(n)) return null;
    if(kind==='frequency') return unit==='hz'?n:null;
    if(kind==='temperature') return unit==='°c'?n:unit==='°f'?(n-32)*5/9:null;
    if(kind==='flow') return ['l/min','l/m'].includes(unit)?n/60000:unit==='l/s'?n/1000:unit==='m3/h'?n/3600:unit==='m3/s'?n:null;
    return null;
  };
  const f=read('compressor_frequency','frequency'),bt12=read('condenser_water_out','temperature');
  const coefficient=bt12===null?null:0.0161+0.000208*(bt12-45);
  const power=f!==null && f>=0 && coefficient!==null && coefficient>=0 ? f*coefficient : null;
  const compressor=Number.isFinite(power)?power:null;
  const extract=read('exhaust_air','temperature'),discharge=read('leaving_air','temperature');
  const reference=read('reference_air_flow','flow'),measured=read('air_flow','flow');
  const useReference=reference!==null && reference>=0;
  const air=useReference?reference:measured;
  const sensible=air!==null && air>=0 && extract!==null && discharge!==null && extract>=discharge ? 1.2*1.006*air*(extract-discharge) : null;
  const qEvaporator=Number.isFinite(sensible)?sensible:null;
  const sum=qEvaporator!==null && compressor!==null?qEvaporator+compressor:null;
  const qCondenser=Number.isFinite(sum)?sum:null;
  return {compressor,compressorMethod:compressor!==null?'frequency-bt12':null,qCondenser,qEvaporator,evaporatorMethod:qEvaporator!==null?(useReference?'reference-sensible':'sensible'):null};
}
const css = `
:host{container-type:inline-size;display:block;color:#203344;color-scheme:light;font-family:var(--paper-font-body1_-_font-family,Inter,system-ui,sans-serif);--primary-text-color:#203344;--secondary-text-color:#596d7d;--ha-card-background:#fff;--divider-color:#dce6eb}*{box-sizing:border-box}
ha-card{display:block;background:#fff;color:#203344;border:1px solid #dce6eb;border-radius:24px;overflow:hidden;box-shadow:0 12px 40px #243c4b08}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 26px;border-bottom:1px solid #e5edf0;background:linear-gradient(115deg,#f5fbf9,#fff 70%)}.eyebrow{font-size:11px;letter-spacing:.17em;text-transform:uppercase;color:#487468;font-weight:700}h1{font-size:27px;font-weight:550;letter-spacing:-.04em;margin:7px 0}h2{font-size:16px;font-weight:600;margin:0}p{color:#596d7d;font-size:13px;line-height:1.6;margin:6px 0}.pill{display:inline-block;border:1px solid #b7ded2;background:#edf8f3;color:#24715b;border-radius:25px;padding:8px 12px;font-size:12px}.demo{color:#895a14;background:#fff8e9;border-color:#ebd8ae}
.body{padding:20px 26px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}.stat{padding:17px;border:1px solid #e0e9ed;border-radius:16px;background:#f8fafb}.label{color:#596d7d;font-size:12px}.value{font-size:27px;letter-spacing:-.04em;margin-top:10px}.unit{font-size:13px;color:#596d7d;margin-left:5px}.sub{font-size:11px;color:#596d7d;margin-top:6px}
.panel{border:1px solid #dce6eb;border-radius:18px;padding:20px;min-width:0}.heading{display:flex;justify-content:space-between;gap:10px;align-items:center}.tag{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#596d7d}.legend{display:flex;flex-wrap:wrap;gap:10px 22px;padding:14px 0 0;font-size:11px;color:#526777}.legend span{display:flex;gap:7px;align-items:center}.legend i{width:20px;height:3px;border-radius:4px;background:var(--line)}.scheme-scroll{overflow-x:auto;border-radius:12px;scrollbar-color:#adc8c2 #f1f6f5}.scheme-scroll:focus-visible{outline:2px solid #268b73;outline-offset:3px}.scroll-hint{display:none}.portrait{display:none}svg{display:block;width:100%;min-width:820px;height:auto;margin:12px 0}svg text{font-family:inherit;fill:#203344;font-size:12px}svg .muted{fill:#596d7d;font-size:11px}svg .section-label{fill:#637886;font-size:10px;letter-spacing:1.6px;font-weight:600}svg .node{fill:#fff;stroke:#b5c8d1;stroke-width:1.5}svg .pipe{fill:none;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}svg .ref-high{stroke:#9171ba}svg .ref-low{stroke:#3d9c9a}svg .hot{stroke:#dd8051}svg .cold{stroke:#5a96bf}svg .air{stroke:#9db4bf;stroke-width:2;stroke-dasharray:5 5;fill:none}svg .sensor-dot{fill:#fff;stroke:#466779;stroke-width:1.5}svg .sensor-leader{fill:none;stroke:#a2b5bf;stroke-width:1}svg .sensor-code{font-size:10px;fill:#667c8c}svg .direction{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}svg .direction.air{stroke-dasharray:none}svg .flow{stroke-dasharray:3 14;stroke:#ffffffbb;stroke-width:2;animation:flow 3s linear infinite}svg .flow.air-motion{stroke:#527f92}svg .flow.paused{animation:none;stroke:transparent}@keyframes flow{to{stroke-dashoffset:-68}}
.more{margin-top:18px;color:#596d7d;font-size:12px}.more summary{cursor:pointer;padding:8px 0}.more p{font-size:12px}.more .discovery{margin:10px 0 18px}.more .discovery button{margin-top:8px}.schematic{padding:8px;border:0}.more .metrics{margin:16px 0}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px 22px;border-top:1px solid #e5edf0;padding-top:18px}.metric{display:flex;flex-direction:column;gap:6px;font-size:12px}.metric span{color:#596d7d}.metric b{font-size:14px;font-weight:550}.controls{margin-top:18px}.control-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}label{display:block;font-size:12px;color:#596d7d;margin-bottom:8px}select,input,button{font:inherit;border:1px solid #cbdcde;border-radius:10px;background:#fff;color:#203344;padding:10px;max-width:100%}select,input{width:100%}button{cursor:pointer;background:#edf8f3;color:#216c57;white-space:nowrap}button:hover{background:#e0f1e9}button:disabled{opacity:.45;cursor:default}.row{display:flex;gap:8px}.notice{font-size:12px;color:#216c57}.notice:not(:empty){margin-top:12px}.empty{padding:12px;border:1px dashed #cbdcde;border-radius:10px;font-size:12px;color:#596d7d}footer{padding-top:18px;color:#596d7d;font-size:11px;line-height:1.6}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #268b73;outline-offset:3px}
@container(max-width:700px){header,.body{padding:20px}.control-grid{grid-template-columns:1fr}.stats,.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:23px}.scheme-scroll{overflow:visible}.landscape{display:none}.portrait{display:block;min-width:0}.portrait text{font-size:14px}.portrait .muted{font-size:13px}.portrait .section-label{font-size:10px}.portrait .sensor-code{font-size:12px}.panel{padding:16px}header,.body{padding:16px}.legend{gap:10px 14px}select,input{font-size:16px;min-height:44px}button{min-height:44px}header .pill{flex-shrink:0}.heading{flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){svg .sensor-dot{fill:#fff;stroke:#466779;stroke-width:1.5}svg .sensor-leader{fill:none;stroke:#a2b5bf;stroke-width:1}svg .sensor-code{font-size:10px;fill:#667c8c}svg .direction{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}svg .direction.air{stroke-dasharray:none}svg .flow{animation:none}}
`;
export class NibeF750Card extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this._busy = false; }
  setConfig(config) {
    if (!config) throw new Error('Card configuration is required.');
    this._manual = config.entities !== undefined;
    this._controlOverrides = config.controls;
    this._selectedDevice = config.device_id;
    this.config = {title:'F750', entities:{}, ...config};
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
      const found = device ? discoverEntities(registry,device.id,this._hass.states) : {entities:{},controls:{}};
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
  heatValue(key) {
    const n=this._heat[key];
    return n===null?'—':`${new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(n)} kW`;
  }
  control(key, title) {
    const id = this.config.controls?.[key], s = this._hass?.states[id];
    if (!id) return `<div class="empty">${title} unavailable</div>`;
    const domain = id.split('.')[0];
    if (!['number','select'].includes(domain) || !this.available(s)) return `<div class="empty">${title} unavailable</div>`;
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
  sensor(id,key,x,y,tx,ty,anchor='start') {
    return `<g class="sensor" data-sensor="${id}"><title>${id} · ${readings[key][0]}</title><path class="sensor-leader" d="M${x} ${y}L${tx} ${ty-8}"/><circle class="sensor-dot" cx="${x}" cy="${y}" r="3"/><text x="${tx}" y="${ty}" text-anchor="${anchor}"><tspan class="sensor-code">${id}</tspan><tspan x="${tx}" dy="18">${this.value(key)} ${this.available(this.state(key))?this.unit(key):''}</tspan></text></g>`;
  }
  diagram(portrait,a) {
    const prefix=portrait?'p':'l';
    const pipe=(name,d,color,active)=>`<g data-flow="${name}"><path class="pipe ${color}" d="${d}"/><path class="pipe flow ${active?'':'paused'} ${color==='air'?'air-motion':''}" d="${d}"/></g>`;
    const arrow=(x,y,angle,color)=>`<path class="direction ${color}" d="M-5 -4L1 0L-5 4" transform="translate(${x} ${y}) rotate(${angle})"/>`;
    const sensor=(...args)=>this.sensor(...args);
    const compressor=(x,y)=>`<circle class="node" cx="${x}" cy="${y}" r="25"/><path d="M${x-9} ${y+11}L${x+14} ${y}L${x-9} ${y-11}Z" fill="#9171ba"/><text x="${x}" y="${y+48}" text-anchor="middle">${this.value('compressor_frequency')} ${this.unit('compressor_frequency')}</text><text x="${x}" y="${y+70}" text-anchor="middle">P = ${this.heatValue('compressor')}</text>`;
    const heater=(x,y)=>`<g data-component="heater"><title>EB1 · common immersion heater before QN10</title><rect class="node" x="${x-32}" y="${y-18}" width="64" height="36" rx="9"/><path d="M${x-23} ${y}H${x-16}L${x-10} ${y-10}L${x-3} ${y+10}L${x+4} ${y-10}L${x+10} ${y}H${x+23}" fill="none" stroke="#dd8051" stroke-width="2"/><text x="${x}" y="${y+43}" text-anchor="middle">${this.value('heater_power')} ${this.unit('heater_power')}</text></g>`;
    const valve=(x,y)=>`<g data-component="diverter"><title>QN10 · changeover valve, heating or DHW</title><circle class="node" cx="${x}" cy="${y}" r="9"/><text class="sensor-code" x="${x-14}" y="${y+32}">QN10</text></g>`;
    const radiator=(x,y)=>`<rect class="node" x="${x-40}" y="${y}" width="80" height="50" rx="9"/><path d="M${x-26} ${y+10}V${y+40}M${x-13} ${y+10}V${y+40}M${x} ${y+10}V${y+40}M${x+13} ${y+10}V${y+40}M${x+26} ${y+10}V${y+40}" stroke="#dd8051" stroke-width="3"/>`;
    const buffer=(x,y)=>`<g data-component="buffer"><title>Heating buffer vessel, simplified</title><rect class="node" x="${x-24}" y="${y}" width="48" height="35" rx="10"/><path d="M${x-13} ${y+12}H${x+13}M${x-13} ${y+23}H${x+13}" stroke="#c8d9df"/></g>`;
    const shell=portrait?'0 0 400 1110':'0 25 1160 530';
    const desc='BT20 inlet air and BT21 outlet air are on the air duct. BT14 hot gas, BT17 suction, BT15 liquid line and BT16 evaporator are on the refrigerant side. BT12 is before the common heater; BT63 is after it and before QN10. BT61 and BT62 are on the heating circuit after the buffer. BT7 and BT6 are tank sensors. Arrows show normal flow; motion is illustrative, not measured flow.';
    return `<svg class="${portrait?'portrait':'landscape'}" viewBox="${shell}" role="img" aria-labelledby="${prefix}-title ${prefix}-desc"><title id="${prefix}-title">Combined F750 refrigerant and hydraulic circuits</title><desc id="${prefix}-desc">${desc}</desc>${portrait?`
      <rect x="6" y="35" width="388" height="410" rx="18" fill="#f6faf9"/><rect x="6" y="450" width="388" height="650" rx="18" fill="#faf8f5"/>
      ${pipe('refrigerant-suction','M100 210V130H195','ref-low',a.refrigerant)}
      ${pipe('refrigerant-discharge','M245 130H345V400H250','ref-high',a.refrigerant)}
      ${pipe('refrigerant-liquid','M170 400H100V365','ref-high',a.refrigerant)}
      ${pipe('refrigerant-evaporator','M100 335V270','ref-low',a.refrigerant)}
      ${pipe('air-inlet','M30 100V230H70','air',a.air)}
      ${pipe('air-outlet','M70 250H30V350','air',a.air)}
      ${arrow(30,205,90,'air')}${arrow(30,338,90,'air')}${arrow(310,130,0,'ref-high')}${arrow(100,295,-90,'ref-low')}
      <rect class="node" x="70" y="210" width="60" height="60" rx="12"/><path d="M80 220L91 232L80 244L91 258M120 220L109 232L120 244L109 258" fill="none" stroke="#67aaa6" stroke-width="2"/>
      ${compressor(220,130)}<path class="node" d="M89 335L111 365V335L89 365Z"/>
      <rect class="node" x="170" y="375" width="80" height="80" rx="12"/><path d="M170 400H250" stroke="#9171ba" stroke-width="5"/><path d="M170 432H250" stroke="#dd8051" stroke-width="5"/><path d="M178 413L190 421L202 413L214 421L226 413L240 421" fill="none" stroke="#b5c8d1" stroke-width="2"/>
      ${sensor('BT20','exhaust_air',30,155,8,65)}
      ${sensor('BT21','leaving_air',30,310,8,380)}
      ${sensor('BT17','suction',150,130,140,70)}
      ${sensor('BT14','hot_gas',300,130,350,70,'end')}
      ${sensor('BT16','evaporator',100,240,160,235)}<text x="160" y="285">Q = ${this.heatValue('qEvaporator')}</text>
      ${sensor('BT15','condenser',130,400,210,333,'end')}
      ${pipe('water-common-supply','M250 432H370V535H220','hot',a.water)}
      ${pipe('water-heating-supply','M220 535H95V790','hot',a.heating)}
      ${pipe('water-dhw-supply','M220 535V640H310V875','hot',a.dhw)}
      ${pipe('water-heating-return','M95 840V1060','cold',a.heating)}
      ${pipe('water-dhw-coil','M310 875Q340 895 310 915Q280 935 310 955','hot',a.dhw)}
      ${pipe('water-dhw-return','M310 955V1060H95','cold',a.dhw)}
      ${pipe('water-common-return','M95 1060H15V432H170','cold',a.water)}
      ${arrow(370,505,90,'hot')}${arrow(270,535,180,'hot')}${arrow(95,680,90,'hot')}${arrow(310,790,90,'hot')}${arrow(95,1010,90,'cold')}${arrow(225,1060,180,'cold')}${arrow(15,700,-90,'cold')}
      ${heater(320,535)}${valve(220,535)}${buffer(95,705)}${radiator(95,790)}
      <rect class="node" x="270" y="850" width="90" height="145" rx="22"/><path class="pipe hot" d="M310 850V875Q340 895 310 915Q280 935 310 955"/><path class="pipe cold" d="M310 955V995"/><path class="pipe flow ${a.dhw?'':'paused'}" d="M310 850V875Q340 895 310 915Q280 935 310 955V995"/>
      ${sensor('BT12','condenser_water_out',310,432,315,470,'end')}
      ${sensor('BT3','return',105,432,115,470)}<text x="210" y="510" text-anchor="middle">Q = ${this.heatValue('qCondenser')}</text>
      ${sensor('BT63','heater_out',250,535,268,595,'end')}
      ${sensor('BT61','heating_supply',95,765,150,750)}
      ${sensor('BT62','heating_return',95,990,150,1005)}
      ${sensor('BT7','hot_water',350,870,380,825,'end')}
      ${sensor('BT6','hot_water_charge',350,970,380,1020,'end')}
    `:`
      <rect x="6" y="35" width="545" height="505" rx="18" fill="#f6faf9"/><rect x="560" y="35" width="590" height="505" rx="18" fill="#faf8f5"/>
      ${pipe('refrigerant-suction','M165 220V130H295','ref-low',a.refrigerant)}
      ${pipe('refrigerant-discharge','M345 130H466V220','ref-high',a.refrigerant)}
      ${pipe('refrigerant-liquid','M466 300V410H332','ref-high',a.refrigerant)}
      ${pipe('refrigerant-evaporator','M308 410H165V300','ref-low',a.refrigerant)}
      ${pipe('air-inlet','M65 115V240H120','air',a.air)}${pipe('air-outlet','M120 280H55V420','air',a.air)}
      ${arrow(65,210,90,'air')}${arrow(55,400,90,'air')}${arrow(430,130,0,'ref-high')}${arrow(165,360,-90,'ref-low')}
      <rect class="node" x="120" y="220" width="90" height="80" rx="12"/><path d="M132 233L145 247L132 261L145 285M198 233L185 247L198 261L185 285" fill="none" stroke="#67aaa6" stroke-width="2"/>
      ${compressor(320,130)}<path class="node" d="M308 398L332 422V398L308 422Z"/>
      <rect class="node" x="440" y="220" width="104" height="80" rx="12"/><path d="M466 220V300" stroke="#9171ba" stroke-width="5"/><path d="M518 220V300" stroke="#dd8051" stroke-width="5"/><path d="M486 231L498 243L486 255L498 267L486 279L498 290" fill="none" stroke="#b5c8d1" stroke-width="2"/>
      ${sensor('BT20','exhaust_air',65,175,12,95)}${sensor('BT21','leaving_air',55,375,12,455)}
      ${sensor('BT17','suction',230,130,200,85)}${sensor('BT14','hot_gas',400,130,430,85,'end')}
      ${sensor('BT16','evaporator',165,260,245,250)}<text x="245" y="302">Q = ${this.heatValue('qEvaporator')}</text>
      ${sensor('BT15','condenser',466,350,425,345,'end')}
      ${pipe('water-common-supply','M518 220V115H790','hot',a.water)}
      ${pipe('water-heating-supply','M790 115H970V240','hot',a.heating)}
      ${pipe('water-dhw-supply','M790 115V335','hot',a.dhw)}
      ${pipe('water-heating-return','M970 290V470H790','cold',a.heating)}
      ${pipe('water-dhw-coil','M790 335Q830 350 790 370Q750 390 790 410','hot',a.dhw)}
      ${pipe('water-dhw-return','M790 410V470','cold',a.dhw)}
      ${pipe('water-common-return','M790 470H518V300','cold',a.water)}
      ${arrow(590,115,0,'hot')}${arrow(850,115,0,'hot')}${arrow(970,220,90,'hot')}${arrow(790,275,90,'hot')}${arrow(970,420,90,'cold')}${arrow(620,470,180,'cold')}
      ${heater(660,115)}${valve(790,115)}${buffer(970,145)}${radiator(970,240)}
      <rect class="node" x="735" y="310" width="110" height="130" rx="24"/><path class="pipe hot" d="M790 310V335Q830 350 790 370Q750 390 790 410"/><path class="pipe cold" d="M790 410V440"/><path class="pipe flow ${a.dhw?'':'paused'}" d="M790 310V335Q830 350 790 370Q750 390 790 410V440"/>
      ${sensor('BT12','condenser_water_out',560,115,560,65)}${sensor('BT63','heater_out',730,115,740,65,'end')}
      ${sensor('BT3','return',550,470,560,510)}<text x="590" y="345">Q = ${this.heatValue('qCondenser')}</text>
      ${sensor('BT61','heating_supply',970,205,1030,190)}${sensor('BT62','heating_return',970,390,1030,405)}
      ${sensor('BT7','hot_water',835,335,875,325)}${sensor('BT6','hot_water_charge',835,415,875,445)}
    `}</svg>`;
  }
  render() {
    if (!this.config) return;
    // Preserve an in-progress setting while cloud readings refresh.
    const active = this.shadowRoot.activeElement;
    const drafts = active?.matches('input,select') ? [[active.id, active.value]] : [];
    const running = this.available(this.state('compressor_frequency')) && Number(this.state('compressor_frequency').state)>0;
    const mode=normalize(this.state('operation')?.state);
    const water=running || (this.available(this.state('heater_power')) && Number(this.state('heater_power').state)>0);
    const dhw=/hot water|dhw/.test(mode),heating=!dhw && /heating/.test(mode);
    const air=['air_flow','reference_air_flow'].some(k=>this.available(this.state(k)) && Number(this.state(k).state)>0);
    const activity={refrigerant:running,water,heating:water&&heating,dhw:water&&dhw,air};
    this._heat=calculateHeat(this._hass?.states || {},this.config.entities);
    const mapped = Object.values(this.config.entities), available = mapped.filter(id=>this.available(this._hass?.states[id])).length;
    this.shadowRoot.innerHTML = `<style>${css}</style><ha-card>
      <header><div><h1>${esc(this.config.title)}</h1></div><span class="pill ${this.config.demo?'demo':''}" title="${available}/${mapped.length} readings available">${this.config.demo?'Demo data':this.available(this.state('operation'))?this.value('operation'):'myUplink'}</span></header>
      <div class="body"><div class="stats">${['outdoor','room','hot_water','compressor_frequency'].map(k=>`<div class="stat"><div class="label">${readings[k][0]}${k==='outdoor'?' · BT1':k==='room'?' · BT50':k==='hot_water'?' · BT7':''}</div><div class="value">${this.value(k)}<span class="unit">${this.available(this.state(k))?this.unit(k):''}</span></div></div>`).join('')}</div>
      <section class="panel schematic">
      <div class="scheme-scroll" tabindex="0" role="region" aria-label="Combined circuit diagram">
      ${this.diagram(false,activity)}${this.diagram(true,activity)}</div>
      </section>
      <section class="panel controls"><h2>Comfort</h2><div class="control-grid">${this.control('heating','Heating adjustment')}${this.control('hot_water','Hot water mode')}</div><div class="notice" role="status" aria-live="polite"></div></section>

      <details id="details" class="more" ${this._detailsOpen || (!this._manual && this._discovered && !this._selectedDevice)?'open':''}><summary>Details</summary>
      ${!this._manual ? `<div class="discovery"><p>${esc(this._discoveryMessage)}</p>${this._devices?.length>1 ? `<label for="device">Heat pump</label><select id="device"><option value="">Choose a heat pump</option>${this._devices.map(d=>`<option value="${esc(d.id)}" ${d.id===(this._selectedDevice || this.config.device_id)?'selected':''}>${esc(d.name_by_user || d.name || d.model || d.id)}</option>`).join('')}</select>`:''}<button id="discover">Refresh discovery</button></div>`:''}
      <div class="metrics">${['reference_air_flow','supply','electrical_power','cop','operation'].map(k=>this.metric(k)).join('')}</div>
      <p>Arrows show normal flow. Animation is illustrative, not measured flow; QN10 selects heating or DHW. The common heater is upstream of both branches. BT30 is a backup thermostat, not a displayed temperature sensor. BT1/BT50 are outside/room sensors in the top cards.</p>
      <p>Q and P are estimates. Air-side Q excludes condensation/freezing heat. Condenser Q = evaporator Q + P; auxiliary heat is separate.</p>
      <p>P = f × [0.0161 + 0.000208 × (BT12 − 45)] kW. Air Q = 0.000335 × m³/h × ΔT.</p>
      </details></div></ha-card>`;
    for (const [id,value] of drafts) { const el=this.shadowRoot.getElementById(id); if(el) { el.value=value; el.focus(); } }
    this.shadowRoot.querySelectorAll('[data-apply]').forEach(b=>b.addEventListener('click',()=>this.apply(b.dataset.apply)));
    this.shadowRoot.getElementById('details')?.addEventListener('toggle',e=>{this._detailsOpen=e.target.open;});
    this.shadowRoot.getElementById('discover')?.addEventListener('click',()=>this.discover(true));
    this.shadowRoot.getElementById('device')?.addEventListener('change',e=>{this._selectedDevice=e.target.value;this.discover(true);});
  }
}
if (!customElements.get('nibe-f750-card')) customElements.define('nibe-f750-card', NibeF750Card);
window.customCards = window.customCards || [];
window.customCards.push({type:'nibe-f750-card',name:'NIBE F750 Dashboard',description:'Circuit diagrams and comfort controls using built-in myUplink entities.',preview:false});
