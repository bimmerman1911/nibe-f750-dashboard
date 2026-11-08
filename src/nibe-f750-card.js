/* NIBE F750 Dashboard — MIT license. Uses Home Assistant's built-in myUplink entities. */
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const readings = {
  outdoor: ['Outdoor', '°C'], room: ['Indoor', '°C'], room_c1:['Indoor · C1','°C'], room_c2:['Indoor · C2','°C'],
  degree_minutes:['Degree minutes',''],system_status:['Status',''],heater_limit:['Maximum inline power','kW'], hot_water: ['Hot water', '°C'],
  supply: ['Heating supply', '°C'], return: ['Heating return', '°C'],
  exhaust_air: ['Extract air', '°C'], leaving_air: ['Discharge air', '°C'],
  evaporator: ['Evaporator', '°C'], condenser: ['Condenser', '°C'],
  compressor_frequency: ['Compressor', 'Hz'], heater_power: ['Auxiliary heater', 'kW'],
  electrical_power: ['Electrical input', 'kW'], cop: ['COP', ''], electricity_price: ['Electricity price', ''],
  operation: ['Operating mode', ''], compressor_status: ['Compressor status', ''], shower_minutes: ['Shower time', 'min'],
  condenser_water_out: ['Condenser water outlet', '°C'], air_flow: ['Extract airflow', ''],
  reference_air_flow: ['Reference airflow', ''], pump_speed: ['GP1 speed', '%'],
  hot_water_charge: ['Hot water control', '°C'], hot_gas: ['Hot gas', '°C'], suction: ['Suction gas', '°C'],
  heating_supply: ['Heating supply after buffer', '°C'], heating_return: ['Heating return after buffer', '°C'], heater_out: ['Water after immersion heater', '°C'],
};
// F750 parameter IDs; myUplink unique IDs are `${device_id}-${parameter_id}`.
// References and compatibility notes: docs/discovery.md.
const points = {degree_minutes:[],system_status:[],heater_limit:[],pump_speed:[],outdoor:['40004'],room:['40033'],hot_water:['40013'],supply:['40008'],return:['40012'],exhaust_air:['40025'],leaving_air:['40026'],evaporator:['40020'],condenser:['40019'],compressor_frequency:['43136'],heater_power:['43084'],operation:['49994'],compressor_status:['43427','43435'],shower_minutes:[],condenser_water_out:['40017'],air_flow:['40050'],reference_air_flow:['43124'],hot_water_charge:['40014'],hot_gas:['40018'],suction:['40022'],heating_supply:['40047'],heating_return:['40048'],heater_out:[]};
// API names can vary from the older F-series register catalog. Match only
// explicit measurement names/BT designations, scoped to the selected device.
const aliases = {
  degree_minutes:[/(?:^| )degree minutes(?: [0-9]+)?$/],
  system_status:[/^(?:vp )?status$/],
  heater_limit:[/(?:^| )(?:set )?max(?:imum)? (?:electrical add|electrical addition|inline heater power)$/],
  pump_speed: [/(?:^| )speed heating medium pump 1$/, /(?:^| )heating medium pump (?:1 |gp1 )?speed$/, /(?:^| )gp1 speed$/],
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
  compressor_status: [/(?:^| )(?:current )?(?:compressor status|status compressor|compressor state)(?: ep14)?$/],
  shower_minutes: [/(?:^| )(?:available |remaining |estimated )?(?:shower|showering) (?:minutes|time|duration)(?: remaining|available)?$/],
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
    const byId = find(ids,key==='compressor_status'?['sensor','binary_sensor']:['sensor','number','select']);
    if(byId) return [key,byId];
    const matches = rows.filter(e=>e.entity_id.startsWith(key==='heater_limit'?'select.':'sensor.') && !/-raw$/.test(e.unique_id) &&
      !(key==='compressor_frequency' && [e.original_name,e.name,states[e.entity_id]?.attributes?.friendly_name,e.entity_id.slice(7)].some(name=>/\b(target|request|requested|min|max|minimum|maximum)\b/.test(normalize(name)))) &&
      [e.original_name,e.name,states[e.entity_id]?.attributes?.friendly_name,e.entity_id.slice(7)].some(name=>
        (aliases[key] || []).some(pattern=>pattern.test(normalize(name)))));
    return [key,matches.length===1 ? matches[0].entity_id : undefined];
  }).filter(([,id])=>id));
  for(const [key,id] of Object.entries({degree_minutes:'sensor.vp_degree_minutes_2',system_status:'sensor.vp_status',heater_limit:'select.vp_set_max_electrical_add'})) {
    if(rows.some(e=>e.entity_id===id))entities[key]=id;
  }
  return {entities};
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
  const cop=qCondenser!==null && compressor>0?qCondenser/compressor:null;
  return {cop,compressor,compressorMethod:compressor!==null?'frequency-bt12':null,qCondenser,qEvaporator,evaporatorMethod:qEvaporator!==null?(useReference?'reference-sensible':'sensible'):null};
}
export function calculateShowerTime(states,entities,options={}) {
  const number=key=>{
    const s=states[entities[key]],value=String(s?.state??'').trim();
    return s && value!=='' && Number.isFinite(Number(value)) ? {value:Number(value),unit:String(s.attributes?.unit_of_measurement||'').toLowerCase().trim()} : null;
  };
  const direct=number('shower_minutes');
  const factor=direct ? ({min:1,minutes:1,s:1/60,h:60})[direct.unit] : undefined;
  if(direct && factor!==undefined && direct.value>=0) return {minutes:direct.value*factor,estimated:false};
  const toC=s=>s?.unit==='°c'?s.value:s?.unit==='°f'?(s.value-32)*5/9:null;
  const top=toC(number('hot_water')),bottom=toC(number('hot_water_charge'));
  const {tank_volume_l:volume=180,cold_water_c:cold=10,shower_temperature_c:target=40,flow_l_min:flow=10}=options;
  if([top,bottom].some(v=>v===null) || ![volume,cold,target,flow].every(Number.isFinite) || volume<=0 || flow<=0 || target<=cold) return null;
  const minutes=top<target ? 0 : Math.max(0,volume*((top+bottom)/2-cold)/(target-cold)/flow);
  return Number.isFinite(minutes)?{minutes,estimated:true,volume,cold,target,flow}:null;
}
const css = `
:host{container-type:inline-size;display:block;color:#203344;color-scheme:light;font-family:var(--paper-font-body1_-_font-family,Inter,system-ui,sans-serif)}*{box-sizing:border-box}ha-card{display:block;background:#fff;color:#203344;border:1px solid #dce6eb;border-radius:20px;overflow:hidden}.body{padding:8px}.schematic{padding:4px}.scheme-scroll{overflow-x:auto;border-radius:12px}.scheme-scroll:focus-visible{outline:2px solid #268b73;outline-offset:2px}.portrait{display:none}svg{display:block;width:100%;min-width:820px;height:auto;margin:0}svg text{font-family:inherit;fill:#203344;font-size:12px}svg .muted{fill:#596d7d;font-size:11px}svg .node{fill:#fff;stroke:#b5c8d1;stroke-width:1.5}svg .pipe{fill:none;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}svg .ref-high{stroke:#9171ba}svg .ref-low{stroke:#3d9c9a}svg .hot{stroke:#dd8051}svg .cold{stroke:#5a96bf}svg .pipe.air-in,svg .pipe.air-out{stroke-width:2;stroke-dasharray:5 5}svg .air-in{stroke:#dfa49c}svg .air-out{stroke:#9ac6e1}svg .sensor-dot{fill:#fff;stroke:#466779;stroke-width:1.5}svg .sensor-leader{fill:none;stroke:#a2b5bf;stroke-width:1}svg .sensor-code{font-size:10px;fill:#667c8c}svg .direction{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}svg .direction.air-in{stroke:#c54d43}svg .direction.air-out{stroke:#3988c2}svg .ambient-house{fill:none;stroke:#b5c8d1;stroke-width:1.5}svg .demo-label{fill:#895a14;font-size:10px}svg .energy{font-size:15px;font-weight:700}svg .shower{font-size:14px;font-weight:600}svg .flow{stroke-dasharray:3 14;stroke:#ffffffbb;stroke-width:2;animation:flow 3s linear infinite}svg .flow.air-in{stroke:#c54d43}svg .flow.air-out{stroke:#3988c2}svg .flow.paused{animation:none;opacity:0}@keyframes flow{to{stroke-dashoffset:-68}}.setup{padding:12px;color:#596d7d;font-size:12px}.setup p{line-height:1.5}.setup label{display:block;margin-bottom:8px}.setup button,.setup select{font:inherit;border:1px solid #cbdcde;border-radius:10px;background:#fff;color:#203344;padding:10px;max-width:100%;min-height:44px}.setup select{width:100%}.setup button{margin-top:8px;cursor:pointer}button:focus-visible,select:focus-visible{outline:2px solid #268b73;outline-offset:3px}
@container(max-width:700px){.scheme-scroll{overflow:visible}.landscape{display:none}.portrait{display:block;min-width:0}.portrait text{font-size:14px}.portrait .muted{font-size:13px}.portrait .sensor-code{font-size:12px}.portrait .energy{font-size:16px}.portrait .demo-label{font-size:10px}.setup select{font-size:16px}}@media(prefers-reduced-motion:reduce){svg .flow{animation:none}}
`;
export class NibeF750Card extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); }
  setConfig(config) {
    if (!config) throw new Error('Card configuration is required.');
    this._manual = config.entities !== undefined;
    this._selectedDevice = config.device_id;
    this.config = {title:'F750', entities:{}, ...config};
    this._discoveryMessage = this._manual ? '' : 'Discovering your myUplink heat pump…';
    this._discovered = false; this._discoveryFailed=false;
    this.render();
    this.discover();
  }
  set hass(hass) {
    this._hass = hass;
    this.discover();
    const ids = [...new Set([...Object.values(this.config?.entities || {}),'sensor.ovanvaning_temperature','sensor.nedervaning_temperature',...Object.keys(hass.states).filter(id=>id.startsWith('weather.'))])];
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
      const weathers=registry.filter(e=>e.entity_id.startsWith('weather.')&&!e.disabled_by);
      const smhi=weathers.filter(e=>e.platform==='smhi');
      this._weather=smhi.length===1?smhi[0].entity_id:weathers.length===1?weathers[0].entity_id:null;
      const f750 = candidates.filter(d=>/f\s*750/i.test(`${d.model || ''} ${d.name || ''}`));
      const selected = this._selectedDevice || config.device_id || (f750.length===1 ? f750[0].id : candidates.length===1 ? candidates[0].id : null);
      const device = candidates.find(d=>d.id===selected);
      this._selectedDevice = device?.id;
      const found = device ? discoverEntities(registry,device.id,this._hass.states) : {entities:{}};
      this.config = {...config,entities:found.entities};
      this._discoveryFailed=false;
      this._discoveryMessage = !device ? (candidates.length ? 'Choose your heat pump below.' : 'No myUplink devices found. Set up the built-in myUplink integration, then retry.') : `${device.name_by_user || device.name || device.model || 'myUplink'} · ${Object.keys(found.entities).length} readings discovered. Missing readings may not be exposed or enabled.`;
      this._discovered = true;
    } catch {
      this._discoveryFailed=true;
      this._discoveryMessage = 'Discovery failed. Check your Home Assistant connection and registry access, then retry.';
      this._discovered = true;
    } finally {
      this._discovering = false;
      this.render();
    }
  }
  static getStubConfig() { return {type:'custom:nibe-f750-card'}; }
  getCardSize() {
    const measured=this.shadowRoot.querySelector('ha-card')?.getBoundingClientRect().height;
    if(measured>0)return Math.ceil(measured/50);
    const width=this.clientWidth||400,content=Math.max(0,width-26);
    return Math.ceil((26+(width<=700?content*1335/400:Math.max(820,content)*620/1160))/50);
  }
  getGridOptions() { return {columns:24, min_columns:6, rows:'auto'}; }
  state(key) {
    let id=this.config?.entities?.[key];
    if(!id&&key==='room_c1')id=!this._manual&&this._hass?.states['sensor.ovanvaning_temperature']?'sensor.ovanvaning_temperature':this.config?.entities?.room;
    if(!id&&key==='room_c2'&&!this._manual)id='sensor.nedervaning_temperature';
    return this._hass?.states[id];
  }
  weatherState() {
    const states=this._hass?.states||{};
    const backend=Object.values(states).find(s=>s.attributes?.controller_domain==='nibe_f750'&&s.attributes?.forecast)?.attributes?.forecast?.weather_entity;
    const candidates=Object.keys(states).filter(id=>id.startsWith('weather.'));
    return states[this.config?.weather_entity||backend||this._weather||(candidates.length===1?candidates[0]:null)];
  }
  heaterLimit() {
    const state=this.state('heater_limit');
    if(!this.available(state))return '—';
    const match=String(state.state).match(/^\s*(\d+(?:[.,]\d+)?)\s*(kw|w)?\s*$/i);
    if(!match)return '—';
    const n=Number(match[1].replace(',','.'))/((match[2]||state.attributes?.unit_of_measurement||'kW').toLowerCase()==='w'?1000:1);
    return `${new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(n)} kW`;
  }
  weatherIcon() {
    const current=this.weatherState(),condition=this.available(current)?current.state:'unavailable';
    const sun='<circle cx="27" cy="33" r="7"/><path d="M27 20V23M27 43V46M14 33H17M37 33H40M18 24L20 26M34 40L36 42M18 42L20 40M34 26L36 24"/>';
    const cloud='<path d="M16 40C9 40 10 29 18 30C18 18 34 18 36 29C47 27 49 41 40 41H16Z" fill="#dcebf5"/>';
    let shape=cloud;
    if(condition==='sunny')shape=sun;
    else if(condition==='clear-night')shape='<path d="M35 21A13 13 0 1 0 39 43A14 14 0 0 1 35 21Z" fill="#dcebf5"/>';
    else if(condition==='partlycloudy')shape=sun+cloud;
    else if(['rainy','pouring','lightning-rainy'].includes(condition))shape=cloud+'<path d="M19 45L16 51M29 45L26 51M39 45L36 51"/>';
    if(['lightning','lightning-rainy'].includes(condition))shape=(condition==='lightning'?cloud:shape)+'<path d="M29 32L22 44H29L24 54L37 39H30L34 32Z" fill="#d8ac55" stroke="#b78a38"/>';
    if(['snowy','snowy-rainy'].includes(condition))shape=cloud+'<path d="M19 45V53M15 49H23M34 45V53M30 49H38"/>';
    if(condition==='fog')shape=cloud+'<path d="M12 45H43M16 50H39"/>';
    if(['windy','windy-variant'].includes(condition))shape='<path d="M12 29H34Q44 29 39 23Q35 19 32 24M12 35H40Q49 35 44 42Q40 46 37 41M15 42H28"/>';
    if(condition==='exceptional')shape='<path d="M27 20L43 48H11Z"/><path d="M27 29V38M27 42V44"/>';
    if(condition==='unavailable'||!['sunny','clear-night','partlycloudy','cloudy','rainy','pouring','lightning','lightning-rainy','snowy','snowy-rainy','fog','windy','windy-variant','exceptional'].includes(condition))shape=cloud+'<text x="27" y="36" text-anchor="middle" style="font-size:12px;stroke:none">?</text>';
    return `<g data-weather-condition="${esc(condition)}" role="img" aria-label="Weather: ${esc(condition.replaceAll('-',' '))}" fill="none" stroke="#719bb9" stroke-width="1.8" stroke-linecap="round">${shape}</g>`;
  }
  ambientDeck(portrait) {
    const house='<path d="M15 33L27 22L39 33V48H15Z" fill="none" stroke="#6d9b82" stroke-width="2"/>';
    const tile=(id,key,x,y,width,color,icon='',height=78)=>{
      const raw=this.value(key),status=key==='system_status';
      const full=String(this.state(key)?.state||'—');
      const text=status?esc(full.length>42?full.slice(0,39)+'…':full):raw;
      return `<g data-reading="${key}" ${['BT1','C1','C2'].includes(id)?`data-sensor="${id}"`:''} class="ambient-panel" transform="translate(${x} ${y})"><title>${esc(readings[key][0])} · ${esc(full)}</title><rect width="${width}" height="${height}" rx="14" fill="${color}"/>${icon}<text x="${icon?52:16}" y="${height===54?18:26}" class="muted">${readings[key][0]}</text><text x="${width-12}" y="${height===54?18:26}" text-anchor="end" class="sensor-code">${id}</text><text x="${icon?52:16}" y="${height===54?40:53}" style="font-size:${status?13:18}px;font-weight:600">${text} ${this.available(this.state(key))?this.unit(key):''}</text></g>`;
    };
    return tile('BT1','outdoor',8,-57,portrait?184:190,'#edf5fb',this.weatherIcon())+
      tile('C1','room_c1',portrait?208:214,-57,portrait?184:190,'#eef7f1',house)+
      tile('C2','room_c2',portrait?8:420,portrait?33:-57,portrait?184:190,'#eef7f1',house)+
      tile('DM','degree_minutes',portrait?208:626,portrait?33:-57,portrait?184:190,'#faf3e7')+
      tile('','system_status',portrait?8:832,portrait?123:-57,portrait?384:318,'#f2f0f8','',portrait?54:78)+
      (this.config.demo?`<text class="demo-label" x="${portrait?390:1140}" y="${portrait?188:30}" text-anchor="end">Demo</text>`:'');
  }
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
  copLabel(x,y,running) {
    const cop=running && Number.isFinite(this._heat.cop)?this._heat.cop:null;
    const value=cop===null?'—':new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(cop);
    return `<g data-cop><title>Estimated heating COP = condenser Q / compressor P. Excludes inline heater; based on the air-side sensible heat estimate.</title><text class="energy" x="${x}" y="${y}" text-anchor="middle">COP ≈ ${value}</text></g>`;
  }
  sensor(id,key,x,y,tx,ty,anchor='start') {
    return `<g class="sensor" data-sensor="${id}"><title>${id} · ${readings[key][0]}</title><path class="sensor-leader" d="M${x} ${y}L${tx} ${ty-8}"/><circle class="sensor-dot" cx="${x}" cy="${y}" r="3"/><text x="${tx}" y="${ty}" text-anchor="${anchor}"><tspan class="sensor-code">${id}</tspan><tspan x="${tx}" dy="18">${this.value(key)} ${this.available(this.state(key))?this.unit(key):''}</tspan></text></g>`;
  }
  showerLabel(x,y,anchor='start') {
    const result=calculateShowerTime(this._hass?.states||{},this.config.entities,this.config.shower);
    const value=result?`${result.estimated?'≈ ':''}${Math.floor(result.minutes)} min`:'— min';
    const title=result?.estimated?`Estimated shower time: ${result.volume} L tank, average BT6/BT7, ${result.target}°C shower, ${result.cold}°C cold inlet, ${result.flow} L/min. Ideal mixing; stratification and draw-off cooling are not resolved.`:'Available shower time; reported minutes when exposed, otherwise estimate needs BT6 and BT7.';
    return `<g data-shower="${result?.estimated?'estimated':result?'reported':'unavailable'}"><title>${esc(title)}</title><text class="shower" x="${x}" y="${y}" text-anchor="${anchor}">${value}</text></g>`;
  }

  diagram(portrait,a) {
    const prefix=portrait?'p':'l';
    const pipe=(name,d,color,active)=>`<g data-flow="${name}"><path class="pipe ${color}" d="${d}"/><path class="pipe flow ${active?'':'paused'} ${color.startsWith('air')?color:''}" d="${d}"/></g>`;
    const arrow=(x,y,angle,color)=>`<path class="direction ${color}" d="M-5 -4L1 0L-5 4" transform="translate(${x} ${y}) rotate(${angle})"/>`;
    const sensor=(...args)=>this.sensor(...args);
    const compressor=(x,y)=>`<circle class="node" cx="${x}" cy="${y}" r="25"/><path d="M${x-9} ${y+11}L${x+14} ${y}L${x-9} ${y-11}Z" fill="#9171ba"/><text x="${x}" y="${y+48}" text-anchor="middle">${this.value('compressor_frequency')} ${this.unit('compressor_frequency')}</text><text x="${x}" y="${y+70}" text-anchor="middle" class="energy">P = ${this.heatValue('compressor')}</text>`;
    const heater=(x,y)=>`<g data-component="heater"><title>EB1 · common immersion heater before QN10</title><rect class="node" x="${x-32}" y="${y-18}" width="64" height="36" rx="9"/><path d="M${x-23} ${y}H${x-16}L${x-10} ${y-10}L${x-3} ${y+10}L${x+4} ${y-10}L${x+10} ${y}H${x+23}" fill="none" stroke="#dd8051" stroke-width="2"/><text x="${x}" y="${y+43}" text-anchor="middle">${this.value('heater_power')} ${this.unit('heater_power')} (${this.heaterLimit()})</text></g>`;
    const valve=(x,y)=>`<g data-component="diverter"><title>QN10 · changeover valve, heating or DHW</title><circle class="node" cx="${x}" cy="${y}" r="9"/><text class="sensor-code" x="${x-14}" y="${y+32}">QN10</text></g>`;
    const radiator=(x,y)=>`<rect class="node" x="${x-40}" y="${y}" width="80" height="50" rx="9"/><path d="M${x-26} ${y+10}V${y+40}M${x-13} ${y+10}V${y+40}M${x} ${y+10}V${y+40}M${x+13} ${y+10}V${y+40}M${x+26} ${y+10}V${y+40}" stroke="#dd8051" stroke-width="3"/>`;
    const pump=(x,y,angle,tx,ty)=>`<g data-component="circulation-pump"><title>GP1 · heating-medium pump on the common return to the condenser</title><circle class="node" cx="${x}" cy="${y}" r="14"/><path d="M-7 -8L9 0L-7 8Z" fill="#5a96bf" transform="translate(${x} ${y}) rotate(${angle})"/><text x="${tx}" y="${ty}" text-anchor="middle">${this.value('pump_speed')} %</text></g>`;
    const shell=portrait?'0 -65 400 1335':'0 -65 1160 620';
    const desc='BT20 inlet air and BT21 outlet air are on the air duct. BT14 hot gas, BT17 suction, BT15 liquid line and BT16 evaporator are on the refrigerant side. BT12 is before the common heater; BT63 is after it and before QN10. BT61 and BT62 are on the heating circuit after the buffer. BT7 and BT6 are tank sensors. Arrows show normal flow; motion is illustrative, not measured flow.';
    return `<svg class="${portrait?'portrait':'landscape'}" viewBox="${shell}" role="img" aria-labelledby="${prefix}-title ${prefix}-desc"><title id="${prefix}-title">Combined F750 refrigerant and hydraulic circuits</title><desc id="${prefix}-desc">${desc}</desc>${this.ambientDeck(portrait)}<g transform="translate(0 ${portrait?160:0})">${portrait?`
      <rect x="6" y="35" width="388" height="410" rx="18" fill="#f6faf9"/><rect x="6" y="450" width="388" height="650" rx="18" fill="#faf8f5"/>
      ${pipe('refrigerant-suction','M100 210V130H195','ref-low',a.refrigerant)}
      ${pipe('refrigerant-discharge','M245 130H345V400H250','ref-high',a.refrigerant)}
      ${pipe('refrigerant-liquid','M170 400H100V365','ref-high',a.refrigerant)}
      ${pipe('refrigerant-evaporator','M100 335V270','ref-low',a.refrigerant)}
      ${pipe('air-inlet','M30 100V230H70','air-in',a.air)}
      ${pipe('air-outlet','M70 250H30V350','air-out',a.air)}
      ${arrow(30,205,90,'air-in')}${arrow(30,338,90,'air-out')}${arrow(310,130,0,'ref-high')}${arrow(100,295,-90,'ref-low')}
      <rect class="node" x="70" y="210" width="60" height="60" rx="12"/><path d="M80 220L91 232L80 244L91 258M120 220L109 232L120 244L109 258" fill="none" stroke="#67aaa6" stroke-width="2"/>
      ${compressor(220,130)}<path class="node" d="M89 335L111 365V335L89 365Z"/>
      <rect class="node" x="170" y="375" width="80" height="80" rx="12"/><path d="M170 400H250" stroke="#9171ba" stroke-width="5"/><path d="M170 432H250" stroke="#dd8051" stroke-width="5"/><path d="M178 413L190 421L202 413L214 421L226 413L240 421" fill="none" stroke="#b5c8d1" stroke-width="2"/>
      ${sensor('BT20','exhaust_air',30,155,8,65)}
      ${sensor('BT21','leaving_air',30,310,8,380)}
      ${sensor('BT17','suction',150,130,140,70)}
      ${sensor('BT14','hot_gas',300,130,350,70,'end')}
      ${sensor('BT16','evaporator',100,240,160,235)}<text x="160" y="285" class="energy">Q = ${this.heatValue('qEvaporator')}</text>
      ${sensor('BT15','condenser',130,400,210,333,'end')}${this.copLabel(270,345,a.refrigerant)}
      ${pipe('water-common-supply','M250 432H370V535H220','hot',a.water)}
      ${pipe('water-heating-supply','M220 535H95V790','hot',a.heating)}
      ${pipe('water-dhw-supply','M220 535V640H310V875','hot',a.dhw)}
      ${pipe('water-heating-return','M95 840V1060','cold',a.heating)}
      ${pipe('water-dhw-coil','M310 875Q340 895 310 915Q280 935 310 955','hot',a.dhw)}
      ${pipe('water-dhw-return','M310 955V1060H95','cold',a.dhw)}
      ${pipe('water-common-return','M95 1060H15V432H170','cold',a.water)}
      ${arrow(370,505,90,'hot')}${arrow(270,535,180,'hot')}${arrow(95,680,90,'hot')}${arrow(310,790,90,'hot')}${arrow(95,1010,90,'cold')}${arrow(225,1060,180,'cold')}${arrow(15,650,-90,'cold')}
      ${heater(320,535)}${valve(220,535)}${radiator(95,790)}${pump(15,700,-90,48,732)}
      <rect class="node" x="270" y="850" width="90" height="145" rx="22"/><path class="pipe hot" d="M310 850V875Q340 895 310 915Q280 935 310 955"/><path class="pipe cold" d="M310 955V995"/><path class="pipe flow ${a.dhw?'':'paused'}" d="M310 850V875Q340 895 310 915Q280 935 310 955V995"/>
      ${sensor('BT12','condenser_water_out',310,432,315,470,'end')}
      ${sensor('BT3','return',105,432,115,470)}<text x="210" y="510" text-anchor="middle" class="energy">Q = ${this.heatValue('qCondenser')}</text>
      ${sensor('BT63','heater_out',250,535,268,595,'end')}
      ${sensor('BT61','heating_supply',95,765,150,750)}
      ${sensor('BT62','heating_return',95,990,150,1005)}
      ${this.showerLabel(315,1020,'middle')}${sensor('BT7','hot_water',350,870,380,825,'end')}
      ${sensor('BT6','hot_water_charge',350,970,380,1020,'end')}
    `:`
      <rect x="6" y="35" width="545" height="505" rx="18" fill="#f6faf9"/><rect x="560" y="35" width="590" height="505" rx="18" fill="#faf8f5"/>
      ${pipe('refrigerant-suction','M165 220V130H295','ref-low',a.refrigerant)}
      ${pipe('refrigerant-discharge','M345 130H466V220','ref-high',a.refrigerant)}
      ${pipe('refrigerant-liquid','M466 300V410H332','ref-high',a.refrigerant)}
      ${pipe('refrigerant-evaporator','M308 410H165V300','ref-low',a.refrigerant)}
      ${pipe('air-inlet','M65 115V240H120','air-in',a.air)}${pipe('air-outlet','M120 280H55V420','air-out',a.air)}
      ${arrow(65,210,90,'air-in')}${arrow(55,400,90,'air-out')}${arrow(430,130,0,'ref-high')}${arrow(165,360,-90,'ref-low')}
      <rect class="node" x="120" y="220" width="90" height="80" rx="12"/><path d="M132 233L145 247L132 261L145 285M198 233L185 247L198 261L185 285" fill="none" stroke="#67aaa6" stroke-width="2"/>
      ${compressor(320,130)}<path class="node" d="M308 398L332 422V398L308 422Z"/>
      <rect class="node" x="440" y="220" width="104" height="80" rx="12"/><path d="M466 220V300" stroke="#9171ba" stroke-width="5"/><path d="M518 220V300" stroke="#dd8051" stroke-width="5"/><path d="M486 231L498 243L486 255L498 267L486 279L498 290" fill="none" stroke="#b5c8d1" stroke-width="2"/>
      ${sensor('BT20','exhaust_air',65,175,12,95)}${sensor('BT21','leaving_air',55,375,12,455)}
      ${sensor('BT17','suction',230,130,200,85)}${sensor('BT14','hot_gas',400,130,430,85,'end')}
      ${sensor('BT16','evaporator',165,260,245,250)}<text x="245" y="302" class="energy">Q = ${this.heatValue('qEvaporator')}</text>
      ${sensor('BT15','condenser',466,350,425,345,'end')}${this.copLabel(320,355,a.refrigerant)}
      ${pipe('water-common-supply','M518 220V115H790','hot',a.water)}
      ${pipe('water-heating-supply','M790 115H970V240','hot',a.heating)}
      ${pipe('water-dhw-supply','M790 115V335','hot',a.dhw)}
      ${pipe('water-heating-return','M970 290V470H790','cold',a.heating)}
      ${pipe('water-dhw-coil','M790 335Q830 350 790 370Q750 390 790 410','hot',a.dhw)}
      ${pipe('water-dhw-return','M790 410V470','cold',a.dhw)}
      ${pipe('water-common-return','M790 470H518V300','cold',a.water)}
      ${arrow(590,115,0,'hot')}${arrow(850,115,0,'hot')}${arrow(970,220,90,'hot')}${arrow(790,275,90,'hot')}${arrow(970,420,90,'cold')}${arrow(590,470,180,'cold')}
      ${heater(660,115)}${valve(790,115)}${radiator(970,240)}${pump(640,470,180,640,510)}
      <rect class="node" x="735" y="310" width="110" height="130" rx="24"/><path class="pipe hot" d="M790 310V335Q830 350 790 370Q750 390 790 410"/><path class="pipe cold" d="M790 410V440"/><path class="pipe flow ${a.dhw?'':'paused'}" d="M790 310V335Q830 350 790 370Q750 390 790 410V440"/>
      ${sensor('BT12','condenser_water_out',560,115,560,65)}${sensor('BT63','heater_out',730,115,740,65,'end')}
      ${sensor('BT3','return',550,470,560,510)}<text x="590" y="345" class="energy">Q = ${this.heatValue('qCondenser')}</text>
      ${sensor('BT61','heating_supply',970,205,1030,190)}${sensor('BT62','heating_return',970,390,1030,405)}
      ${this.showerLabel(790,463,'middle')}${sensor('BT7','hot_water',835,335,875,325)}${sensor('BT6','hot_water_charge',835,415,875,445)}
    `}</g></svg>`;
  }
  render() {
    if (!this.config) return;
    const frequency=this.state('compressor_frequency');
    const status=normalize(this.state('compressor_status')?.state);
    const explicitOff=/^(0|20|100|false)$/.test(status) || /(?:^| )(?:off|stopped|stopping|blocked|disabled|standby)(?: |$)/.test(status);
    const running=this.available(frequency) && Number(frequency.state)>0 && !explicitOff;
    const mode=normalize(this.state('operation')?.state);
    const water=running || (this.available(this.state('heater_power')) && Number(this.state('heater_power').state)>0);
    const dhw=/hot water|dhw/.test(mode),heating=!dhw && /heating/.test(mode);
    const air=['air_flow','reference_air_flow'].some(k=>this.available(this.state(k)) && Number(this.state(k).state)>0);
    const activity={refrigerant:running,water,heating:water&&heating,dhw:water&&dhw,air};
    this._heat=calculateHeat(this._hass?.states || {},this.config.entities);
    this.shadowRoot.innerHTML = `<style>${css}</style><ha-card><div class="body">
      <section class="panel schematic">
      <div class="scheme-scroll" tabindex="0" role="region" aria-label="Combined circuit diagram">
      ${this.diagram(false,activity)}${this.diagram(true,activity)}</div>
      </section>
      ${!this._manual && (!this._selectedDevice || this._discoveryFailed) ? `<div class="setup"><p>${esc(this._discoveryMessage)}</p>${this._devices?.length>1 ? `<label for="device">Heat pump</label><select id="device"><option value="">Choose a heat pump</option>${this._devices.map(d=>`<option value="${esc(d.id)}" ${d.id===(this._selectedDevice || this.config.device_id)?'selected':''}>${esc(d.name_by_user || d.name || d.model || d.id)}</option>`).join('')}</select>`:''}<button id="discover">Retry discovery</button></div>`:''}
      </div></ha-card>`;
    this.shadowRoot.getElementById('discover')?.addEventListener('click',()=>this.discover(true));
    this.shadowRoot.getElementById('device')?.addEventListener('change',e=>{this._selectedDevice=e.target.value;this.discover(true);});
  }
}
if (!customElements.get('nibe-f750-card')) customElements.define('nibe-f750-card', NibeF750Card);
window.customCards = window.customCards || [];
window.customCards.push({type:'nibe-f750-card',name:'NIBE F750 Dashboard',description:'F750 system diagram using built-in myUplink entities.',preview:false});
