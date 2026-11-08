/* NIBE Smart Control — planning card with optional HA backend. MIT. */
const finite=v=>typeof v==='number'?Number.isFinite(v):typeof v==='string'&&v.trim()!==''&&Number.isFinite(Number(v));
const stamp=v=>typeof v==='string'&&/(Z|[+-]\d{2}:\d{2})$/.test(v)?Date.parse(v):NaN;
const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function normalizePrices(rows,{unit,currency='SEK',vat_percent=0,extra_per_kwh=0}={}) {
  if(!Array.isArray(rows)) throw Error('Timestamped Nord Pool prices are missing.');
  const u=String(unit||'').replace(/\s/g,'').toLowerCase(),curr=currency.toLowerCase();
  let scale=u===`${curr}/mwh`?.001:u===`${curr}/kwh`?1:currency==='SEK'&&['öre/kwh','ore/kwh'].includes(u)?.01:null;
  if(scale===null) throw Error('Set the price unit explicitly, for example SEK/kWh.');
  if(!finite(vat_percent)||!finite(extra_per_kwh)||Number(vat_percent)<0||Number(vat_percent)>100) throw Error('Invalid tariff settings.');
  const prices=rows.map(r=>{
    const start=stamp(r.start),end=stamp(r.end),value=r.price??r.value;
    if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||!finite(value)) throw Error('Invalid price interval or value.');
    const price=(Number(value)*scale+Number(extra_per_kwh))*(1+Number(vat_percent)/100);
    if(!Number.isFinite(price)) throw Error('Invalid converted price.');
    return {start,end,price};
  }).sort((a,b)=>a.start-b.start);
  for(let i=1;i<prices.length;i++) if(prices[i].start<prices[i-1].end) throw Error('Overlapping price intervals.');
  return prices;
}
export function normalizeForecast(rows,unit) {
  if(!['°C','°F'].includes(unit)||!Array.isArray(rows)) throw Error('An hourly weather forecast with temperature units is required.');
  const forecast=rows.map(r=>{
    const time=stamp(r.datetime),temp=r.temperature;
    if(!Number.isFinite(time)||!finite(temp)) throw Error('Invalid weather forecast point.');
    return {time,temp:unit==='°F'?(Number(temp)-32)*5/9:Number(temp)};
  }).sort((a,b)=>a.time-b.time);
  for(let i=1;i<forecast.length;i++) if(forecast[i].time===forecast[i-1].time) throw Error('Duplicate forecast timestamps.');
  return forecast;
}
export function buildTimeline(prices,weather,now=Date.now(),hours=24) {
  if(!prices.length||weather.length<2) throw Error('Prices and hourly weather are required.');
  const rows=[],limit=Math.min(now+hours*3600000,prices.at(-1).end,weather.at(-1).time);
  let cursor=now;
  while(cursor<limit-1) {
    const p=prices.find(p=>p.start<=cursor&&p.end>cursor);
    if(!p) break;
    const end=Math.min(limit,p.end,(Math.floor(cursor/900000)+1)*900000);
    const t=(cursor+end)/2;
    const next=weather.findIndex(w=>w.time>t),before=weather[next-1],after=weather[next];
    if(!before||!after||after.time-before.time>10800000) break;
    const outdoor=before.temp+(after.temp-before.temp)*(t-before.time)/(after.time-before.time);
    rows.push({start:cursor,end,dt:(end-cursor)/3600000,price:p.price,outdoor});cursor=end;
  }
  return rows;
}
// Reproduce the owner's target dependency, not a hydraulic heat allocation.
export function linkedCircuitTargets(c1Target,c2Room) {
  return {c1:finite(c1Target)?Number(c1Target):null,c2:finite(c1Target)&&finite(c2Room)?Math.min(Math.ceil(Number(c2Room)),Number(c1Target)):null};
}
export function validateModel(m) {
  if(!m||!Array.isArray(m.zones)||m.zones.length<1||m.zones.length>2) throw Error('Add a calibrated one- or two-zone model to preview a plan.');
  for(const z of m.zones) {
    for(const key of ['loss_kw_per_k','capacity_kwh_per_k','min_c','max_c','target_c','heat_share']) if(!Number.isFinite(z[key])) throw Error(`Missing zone model value: ${key}`);
    if(z.loss_kw_per_k<=0||z.capacity_kwh_per_k<=0||z.heat_share<=0||z.min_c>=z.max_c||z.target_c<z.min_c||z.target_c>z.max_c) throw Error('Invalid zone model bounds.');
  }
  for(const key of ['capacity_kwh_per_k','loss_kw_per_k','ambient_c','min_c','max_c','target_c']) if(!Number.isFinite(m.dhw?.[key])) throw Error(`Missing DHW model value: ${key}`);
  const w=m.dhw;
  if(w.capacity_kwh_per_k<=0||w.loss_kw_per_k<0||w.min_c>=w.max_c||w.target_c<w.min_c||w.target_c>w.max_c) throw Error('Invalid hot-water model bounds.');
  for(const key of ['heat_low_kw','heat_high_kw','dhw_high_kw','low_hz','high_hz','supply_c','dhw_supply_c','inline_step_kw','min_on_minutes','min_off_minutes','min_mode_minutes']) if(!Number.isFinite(m[key])||m[key]<0) throw Error(`Missing or invalid plant model value: ${key}`);
  if(m.heat_low_kw<=0||m.heat_high_kw<m.heat_low_kw||m.dhw_high_kw<=0||m.high_hz<m.low_hz||m.low_hz<=0||m.inline_step_kw<=0||m.inline_step_kw>6.5) throw Error('Invalid compressor/inline capacity model.');
  if(m.low_hz*(.0161+.000208*(m.supply_c-45))<=0||m.high_hz*(.0161+.000208*(m.dhw_supply_c-45))<=0) throw Error('Invalid power-model temperature.');
  for(const draw of m.dhw.draws||[]) if(!Number.isFinite(stamp(draw.at))||!Number.isFinite(draw.kwh)||draw.kwh<0) throw Error('Invalid hot-water demand event.');
  for(const z of m.zones) if(z.internal_gain_kw!==undefined&&!Number.isFinite(z.internal_gain_kw)) throw Error('Invalid internal heat gain.');
  return m;
}
const compressorPower=(hz,bt12)=>hz*(.0161+.000208*(bt12-45));
const within=(v,lo,hi)=>v>=lo-1e-7&&v<=hi+1e-7;
export function planHeat(slots,model,initial,{beam=600}={}) {
  validateModel(model);
  if(!slots.length||slots.reduce((a,s)=>a+s.dt,0)<(model.min_horizon_hours??6)) return {status:'insufficient',message:'Not enough continuous prices and weather for a plan.',steps:[]};
  if(!initial||initial.temps?.length!==model.zones.length||!initial.temps.every(finite)||!finite(initial.water)) return {status:'missing',message:'Current room and tank temperatures are required.',steps:[]};
  const draws=slots.map(s=>(model.dhw.draws||[]).filter(d=>stamp(d.at)>=s.start&&stamp(d.at)<s.end).reduce((sum,d)=>{
    if(!finite(d.kwh)||Number(d.kwh)<0) throw Error('Invalid hot-water demand event.');return sum+Number(d.kwh);
  },0));
  const share=model.zones.reduce((sum,z)=>sum+z.heat_share,0);
  const base=[{mode:'off',q:0,p:0,hz:0},{mode:'heat',q:model.heat_low_kw,p:compressorPower(model.low_hz,model.supply_c),hz:model.low_hz},{mode:'heat',q:model.heat_high_kw,p:compressorPower(model.high_hz,model.supply_c),hz:model.high_hz},{mode:'dhw',q:model.dhw_high_kw,p:compressorPower(model.high_hz,model.dhw_supply_c),hz:model.high_hz}];
  const solve=(allowInline,width=beam)=>{
    const actions=allowInline?[...base.map(a=>({...a,inline:0})),...base.filter(a=>a.mode!=='off').map(a=>({...a,inline:model.inline_step_kw})),{mode:'heat',q:0,p:0,hz:0,inline:model.inline_step_kw},{mode:'dhw',q:0,p:0,hz:0,inline:model.inline_step_kw}]:base.map(a=>({...a,inline:0}));
    let states=[{temps:initial.temps.map(Number),water:Number(initial.water),on:!!initial.running,mode:initial.running?(initial.mode==='dhw'?'dhw':'heat'):'off',run:initial.running?0:model.min_on_minutes,off:initial.running?0:model.min_off_minutes,modeTime:model.min_mode_minutes,cost:0,aux:0,starts:0,parent:null}];
    for(let i=0;i<slots.length;i++) {
      const s=slots[i],next=new Map();
      for(const prev of states) for(const action of actions) {
        const on=action.hz>0;
        if(on&&!prev.on&&prev.off<model.min_off_minutes-1e-8) continue;
        if(!on&&prev.on&&prev.run<model.min_on_minutes-1e-8) continue;
        if(prev.mode!=='off'&&action.mode!=='off'&&prev.mode!==action.mode&&prev.modeTime<model.min_mode_minutes-1e-8) continue;
        const temps=model.zones.map((z,j)=>{
          const decay=Math.exp(-z.loss_kw_per_k/z.capacity_kwh_per_k*s.dt);
          const q=(action.mode==='heat'?(action.q+action.inline)*z.heat_share/share:0)+(Number(z.internal_gain_kw)||0);
          return s.outdoor+(prev.temps[j]-s.outdoor)*decay+q/z.loss_kw_per_k*(1-decay);
        });
        const beforeDraw=prev.water-draws[i]/model.dhw.capacity_kwh_per_k;
        const water=beforeDraw+((action.mode==='dhw'?action.q+action.inline:0)-model.dhw.loss_kw_per_k*(prev.water-model.dhw.ambient_c))*s.dt/model.dhw.capacity_kwh_per_k;
        if(!temps.every((v,j)=>within(v,model.zones[j].min_c,model.zones[j].max_c))||!within(beforeDraw,model.dhw.min_c,model.dhw.max_c)||!within(water,model.dhw.min_c,model.dhw.max_c)) continue;
        const node={temps,water,on,mode:action.mode,run:on?Math.min(model.min_on_minutes,prev.on?prev.run+s.dt*60:s.dt*60):0,off:on?0:Math.min(model.min_off_minutes,prev.off+s.dt*60),modeTime:action.mode===prev.mode?Math.min(model.min_mode_minutes,prev.modeTime+s.dt*60):s.dt*60,cost:prev.cost+(action.p+action.inline)*s.dt*s.price,aux:prev.aux+action.inline*s.dt,starts:prev.starts+Number(on&&!prev.on),parent:prev,step:{...s,action:action.mode,hz:action.hz,compressor_kw:action.p,heat_kw:action.q,inline_kw:action.inline,temps,water}};
        const key=[...temps.map(v=>Math.round(v*20)),Math.round(water*4),action.mode,on,Math.round(node.run),Math.round(node.off),Math.round(node.modeTime)].join('/');
        const old=next.get(key);
        if(!old||node.aux<old.aux-1e-8||(Math.abs(node.aux-old.aux)<1e-8&&(node.cost<old.cost-1e-8||Math.abs(node.cost-old.cost)<1e-8&&node.starts<old.starts))) next.set(key,node);
      }
      const progress=(i+1)/slots.length;
      const rank=n=>n.cost+progress**4*(model.zones.reduce((sum,z,j)=>sum+Math.max(0,z.target_c-n.temps[j])**2*50,0)+Math.max(0,model.dhw.target_c-n.water)**2*2);
      const ordered=[...next.values()].sort((a,b)=>allowInline&&Math.abs(a.aux-b.aux)>1e-8?a.aux-b.aux:rank(a)-rank(b));
      // Retain different storage levels: a cheap, depleted tank must not crowd
      // every preheated candidate out of the beam before a known shower draw.
      const diverse=new Map();
      for(const n of ordered) {
        const stored=model.zones.reduce((sum,z,j)=>sum+(n.temps[j]-z.min_c)*z.capacity_kwh_per_k,0);
        const bucket=`${n.mode}/${Math.floor(n.water/2)}/${Math.floor(stored/2)}`;
        if(!diverse.has(bucket))diverse.set(bucket,n);
      }
      states=[...diverse.values()].slice(0,width);const retained=new Set(states);
      for(const n of ordered)if(states.length<width&&!retained.has(n))states.push(n);
      if(!states.length) return null;
    }
    const final=states.filter(n=>n.temps.every((v,j)=>v>=model.zones[j].target_c-1e-7)&&n.water>=model.dhw.target_c-1e-7).sort((a,b)=>a.aux-b.aux||a.cost-b.cost||a.starts-b.starts)[0];
    if(!final) return null;
    const steps=[];for(let n=final;n.parent;n=n.parent) steps.push(n.step);steps.reverse();
    return {steps,cost:final.cost,auxiliary_kwh:final.aux,starts:final.starts};
  };
  const compressorOnly=solve(false)||solve(false,beam*3);
  const chosen=compressorOnly||solve(true);
  if(!chosen) return {status:'infeasible',message:'No feasible plan found within the configured comfort, reserve and capacity limits.',steps:[]};
  const electrical=chosen.steps.reduce((sum,s)=>sum+(s.compressor_kw+s.inline_kw)*s.dt,0);
  return {status:'preview',...chosen,electrical_kwh:electrical,compressorOnly:!!compressorOnly,message:compressorOnly?'A compressor-only plan was found.':'No compressor-only plan found by the bounded search; this candidate uses inline heat.'};
}

const round=(v,n=1)=>finite(v)?new Intl.NumberFormat(undefined,{maximumFractionDigits:n}).format(v):'—';
const clock=(t,tz)=>new Intl.DateTimeFormat(undefined,{timeZone:tz,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(t);
const when=(t,tz)=>new Intl.DateTimeFormat(undefined,{timeZone:tz,day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(t);
const temperature=s=>!s||!finite(s.state)?null:s.attributes?.unit_of_measurement==='°C'?Number(s.state):s.attributes?.unit_of_measurement==='°F'?(Number(s.state)-32)*5/9:null;
const dateAt=(t,tz)=>new Intl.DateTimeFormat('sv-SE',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}).format(t);
const tomorrow=date=>{const [y,m,d]=date.split('-').map(Number);return new Date(Date.UTC(y,m-1,d+1)).toISOString().slice(0,10);};
export async function fetchMarket(hass,config,registry,weatherId,priceId) {
  const tz=hass.config?.time_zone||'Europe/Stockholm',currency=config.currency||'SEK',tariff=config.tariff||{};
  const weatherResult=await hass.callWS({type:'call_service',domain:'weather',service:'get_forecasts',service_data:{entity_id:weatherId,type:'hourly'},return_response:true});
  const response=weatherResult.response||weatherResult;
  const weatherAttrs=hass.states[weatherId]?.attributes||{};
  const weather=normalizeForecast(response[weatherId]?.forecast,weatherAttrs.temperature_unit);
  if(weather[0]?.time>Date.now()&&weather[0].time-Date.now()<=5400000&&finite(weatherAttrs.temperature)) {
    weather.unshift({time:Date.now(),temp:weatherAttrs.temperature_unit==='°F'?(Number(weatherAttrs.temperature)-32)*5/9:Number(weatherAttrs.temperature)});
  }
  const attrs=hass.states[priceId]?.attributes||{};
  let prices,unpublished=false;
  if(Array.isArray(attrs.raw_today)&&attrs.raw_today.length) {
    const rows=[...attrs.raw_today,...(attrs.tomorrow_valid===false?[]:attrs.raw_tomorrow||[])];
    prices=normalizePrices(rows,{currency,unit:config.price_unit||attrs.unit_of_measurement,...tariff});
    unpublished=!(attrs.tomorrow_valid!==false&&attrs.raw_tomorrow?.length);
  } else {
    const entry=config.nordpool_entry||registry.find(e=>e.entity_id===priceId)?.config_entry_id;
    if(!entry) throw Error('Choose a Nord Pool sensor or set nordpool_entry.');
    const date=dateAt(Date.now(),tz),area=config.area||'SE3';
    const get=async day=>{
      const result=await hass.callWS({type:'call_service',domain:'nordpool',service:'get_prices_for_date',service_data:{config_entry:entry,date:day,areas:[area],currency},return_response:true});
      const payload=result.response||result;
      if(!Array.isArray(payload[area])) throw Error('Nord Pool returned no prices for the chosen area.');
      return payload[area];
    };
    const today=await get(date);let next=[];
    try{next=await get(tomorrow(date));}catch{unpublished=true;}
    prices=normalizePrices([...today,...next],{currency,unit:`${currency}/MWh`,...tariff});
  }
  return {weather,prices,unpublished,currency,tz,fetchedAt:Date.now()};
}

function backendControl(states={}) {
  const entry=Object.entries(states).find(([id,s])=>id.startsWith('switch.')&&s.attributes?.controller_domain==='nibe_f750');
  const id=entry?.[0]||(states['switch.nibe_smart_control']?'switch.nibe_smart_control':'input_boolean.nibe_smart_control_enabled');
  const state=states[id];return {id,state,status:id.startsWith('switch.')?state?.attributes?.status:states['sensor.nibe_smart_control_status']?.state};
}
const style=`:host{display:block;font-family:Inter,system-ui,sans-serif;color:#233747;container-type:inline-size;color-scheme:light}*{box-sizing:border-box}ha-card{display:block;background:#fff;border:1px solid #dbe6e9;border-radius:22px;overflow:hidden}header{padding:22px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e7edef;gap:14px}h1{font-size:22px;letter-spacing:-.03em;margin:4px 0;font-weight:600}h2{font-size:14px;margin:0 0 12px}p{font-size:12px;color:#617584;line-height:1.6;margin:8px 0}.eyebrow{color:#497c6b;font-size:10px;letter-spacing:.15em;font-weight:700}.badge{font-size:11px;white-space:nowrap;color:#876320;background:#fff8e9;border:1px solid #eadab8;border-radius:20px;padding:7px 10px}.body{padding:22px 24px}.decision{padding:18px 20px;border-radius:15px;background:#f0f8f4;border:1px solid #d8eae1;margin-bottom:18px}.decision strong{font-size:18px;font-weight:600}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}.fact{padding:14px;background:#f7f9fa;border-radius:12px}.label{font-size:11px;color:#647b89}.value{font-size:22px;letter-spacing:-.04em;margin-top:7px}.value small{font-size:11px;letter-spacing:0}.plots{display:grid;grid-template-columns:1fr;gap:18px}.plot{border:1px solid #e1e9ed;border-radius:15px;padding:16px;min-width:0}svg{width:100%;height:auto;display:block}svg text{font-family:inherit;font-size:10px;fill:#647b89}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:#647b89}.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px}.zones{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:18px}.zone{border:1px solid #e1e9ed;border-radius:13px;padding:14px}.zone strong{font-size:17px}.zone .label{margin-top:7px}.schedule{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}.schedule td,.schedule th{text-align:left;padding:10px 6px;border-bottom:1px solid #edf1f3}.schedule th{font-size:10px;color:#647b89;font-weight:500}details{margin-top:18px;font-size:12px;color:#617584}summary{cursor:pointer;padding:6px 0}button,select{font:inherit;color:#286e59;background:#f0f8f4;border:1px solid #c6ded3;border-radius:10px;padding:9px 12px;cursor:pointer;max-width:100%;min-height:42px}select{background:#fff;width:100%;color:#233747}label{display:block;font-size:12px;margin:12px 0 6px}.error{background:#fff8eb;border:1px solid #efdfbf;padding:14px;border-radius:12px;margin-bottom:16px}.controls{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px}.source{font-size:11px;color:#617584}.empty{padding:18px;border:1px dashed #ccdce2;border-radius:12px}@container(max-width:600px){header,.body{padding:16px}.facts{gap:8px}.fact{padding:12px}.value{font-size:19px}.zones{grid-template-columns:1fr}h1{font-size:20px}.badge{font-size:10px;padding:6px}.decision{padding:16px}.schedule td{font-size:11px}}`;
if(globalThis.customElements&&!customElements.get('nibe-f750-smart-card')) {
  class F750SmartCard extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});this._busy=false;}
    setConfig(c){this.config={area:'SE3',currency:'SEK',horizon_hours:24,...c};this._registry=null;this._lastFetch=0;this._market=null;this._plan=null;this._initial=null;this._slots=[];this._telemetry=null;this._error='';this.render();this.refresh();}
    set hass(h){this._hass=h;this.refresh();const b=backendControl(h.states),signature=[b.id,b.state?.state,b.status].join('/');if(signature!==this._controlSignature){this._controlSignature=signature;this.render();}}
    connectedCallback(){this._timer=setInterval(()=>this.refresh(),60000);this._resize=new ResizeObserver(entries=>{const width=Math.round(entries[0].contentRect.width);if(width!==this._width){this._width=width;this.render();}});this._resize.observe(this);}
    disconnectedCallback(){clearInterval(this._timer);this._resize?.disconnect();}
    getCardSize(){return 12;}
    getGridOptions(){return {columns:24,min_columns:6,rows:12};}
    static getStubConfig(){return {type:'custom:nibe-f750-smart-card'};}
    async refresh(force=false){
      if(!this.config||!this._hass||this._busy||(!force&&Date.now()-this._lastFetch<900000))return;
      this._busy=true;this._error='';
      try {
        if(this.config.demo) {
          const d=this.config.demo_data;if(!d)throw Error('Demo data is missing.');
          this._market={prices:normalizePrices(d.prices,{unit:`${this.config.currency}/kWh`,currency:this.config.currency}),weather:normalizeForecast(d.weather,'°C'),currency:this.config.currency,tz:'Europe/Stockholm',unpublished:false,fetchedAt:Date.now()};
          this._initial=d.initial;
        } else {
          this._registry=this._registry||await this._hass.callWS({type:'config/entity_registry/list'});
          const devices=await this._hass.callWS({type:'config/device_registry/list'});
          const pumps=devices.filter(d=>this._registry.some(e=>e.platform==='myuplink'&&e.device_id===d.id));
          const match=pumps.filter(d=>/f\s*750/i.test(`${d.model||''} ${d.name||''}`));
          const device=this.config.device_id||this._device||(match.length===1?match[0].id:pumps.length===1?pumps[0].id:null);
          this._pumps=pumps;this._device=device;
          this._weathers=this._registry.filter(e=>e.entity_id.startsWith('weather.')&&!e.disabled_by);
          const smhi=this._weathers.filter(e=>e.platform==='smhi');
          const weatherId=this.config.weather_entity||this._weather||(smhi.length===1?smhi[0].entity_id:this._weathers.length===1?this._weathers[0].entity_id:null);
          this._weather=weatherId;
          const defaultPrice='sensor.nordpool_kwh_se3_sek_3_10_025';
          this._priceEntities=this._registry.filter(e=>e.platform==='nordpool'&&e.entity_id.startsWith('sensor.')&&!e.disabled_by&&(/\/kwh/i.test(this._hass.states[e.entity_id]?.attributes?.unit_of_measurement||'')||this._hass.states[e.entity_id]?.attributes?.raw_today));
          const priceId=this.config.price_entity||this._price||(this._hass.states[defaultPrice]?defaultPrice:this._priceEntities.length===1?this._priceEntities[0].entity_id:null);this._price=priceId;
          if(!weatherId)throw Error('Choose an hourly weather entity. Add the built-in SMHI integration if needed.');
          if(!priceId&&!this.config.nordpool_entry)throw Error('Choose the Nord Pool price sensor.');
          this._market=await fetchMarket(this._hass,this.config,this._registry,weatherId,priceId);
          const rows=this._registry.filter(e=>e.platform==='myuplink'&&e.device_id===device&&!e.disabled_by);
          const point=id=>rows.find(e=>String(e.unique_id).endsWith(`-${id}`))?.entity_id;
          const temp=id=>temperature(this._hass.states[id]);
          const m=this.config.model;
          this._initial={temps:(m?.zones||[{},{}]).map((z,i)=>temp(z.temperature_entity||(i===0?'sensor.ovanvaning_temperature':'sensor.nedervaning_temperature'))),water:(temp(point('40013'))!==null&&temp(point('40014'))!==null)?(temp(point('40013'))+temp(point('40014')))/2:null,running:Number(this._hass.states[point('43136')]?.state)>0,mode:/hot water/i.test(this._hass.states[point('49994')]?.state||'')?'dhw':'heat'};
          this._linkedTargets=linkedCircuitTargets(this._hass.states['input_number.set_temp_c1']?.state,temp('sensor.nedervaning_temperature'));
          this._telemetry={targets:['input_number.set_temp_c1','input_number.set_temp_c2'].map(id=>this._hass.states[id]?.state),offsets:['number.vp_heating_offset_climate_system_1','number.vp_heating_offset_climate_system_2'].map(id=>this._hass.states[id]?.state),legacy:['sensor.thermostat_comp_c1','sensor.thermostat_comp_c2'].map(id=>this._hass.states[id]?.state)};
          if(!device)throw Error('Choose the myUplink heat pump.');
        }
        const slots=buildTimeline(this._market.prices,this._market.weather,Date.now(),this.config.horizon_hours);
        this._slots=slots;
        this._plan=!this.config.demo&&this.config.model?.zones?.length===2?{status:'coupled',steps:[],message:'C2 demand is limited by C1. The demo’s fixed heat split does not model this hydraulic coupling; live scheduling needs a coupled circuit model.'}:this.config.model?planHeat(slots,this.config.model,this._initial):null;
        this._lastFetch=Date.now();
      } catch(e){this._plan=null;this._slots=[];this._market=null;this._initial=null;this._error=e.message;this._lastFetch=Date.now();}
      finally{this._busy=false;this.render();}
    }
    chart(kind){
      const rows=this._slots||[];if(!rows.length)return '<p>No continuous forecast interval is available.</p>';
      const plan=this._plan?.steps||[],width=Math.max(320,Math.min(760,(this._width||this.clientWidth)-80)),height=150,left=36,right=12,top=16,bottom=24;
      const values=rows.map(s=>kind==='price'?s.price:s.outdoor),lo=Math.min(...values,0),hi=Math.max(...values,lo+1),x=i=>left+i*(width-left-right)/rows.length,y=v=>height-bottom-(v-lo)/(hi-lo)*(height-top-bottom);
      const bars=kind==='price'?rows.map((s,i)=>`<rect x="${x(i)}" y="${Math.min(y(s.price),y(0))}" width="${Math.max(1,(width-left-right)/rows.length-1)}" height="${Math.max(1,Math.abs(y(s.price)-y(0)))}" rx="1" fill="${!plan[i]?'#dbe6e9':plan[i]?.inline_kw>0?'#d59a58':plan[i]?.action==='off'?'#dbe6e9':plan[i]?.action==='dhw'?'#86a9cf':'#6ba68e'}"><title>${clock(s.start,this._market.tz)} · ${round(s.price,3)} ${escapeHTML(this._market.currency)}/kWh</title></rect>`).join(''):`<path d="${rows.map((s,i)=>`${i?'L':'M'}${x(i)} ${y(s.outdoor)}`).join(' ')}" fill="none" stroke="#759eba" stroke-width="2.5"/>`;
      const ticks=[0,Math.floor(rows.length/3),Math.floor(rows.length*2/3),rows.length-1];
      return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${kind==='price'?'Electricity prices and planned operation':'Outdoor temperature forecast'}"><line x1="${left}" x2="${width-right}" y1="${y(0)}" y2="${y(0)}" stroke="#dce7eb"/>${bars}<text x="0" y="24">${round(hi,2)}</text><text x="0" y="${height-bottom}">${round(lo,2)}</text>${ticks.map(i=>`<text x="${x(i)}" y="${height-5}" text-anchor="${i===rows.length-1?'end':'start'}">${clock(rows[i].start,this._market.tz)}</text>`).join('')}</svg>`;
    }
    render(){
      if(!this.config)return;
      const backend=backendControl(this._hass?.states),controller=!this.config.demo&&backend.state,active=controller?.state==='on';
      const market=this._market,plan=this._plan,steps=plan?.steps||[],first=steps[0],current=this._slots?.[0],last=this._slots?.at(-1),model=this.config.model;
      const forecastTitle=this._error?'Waiting for usable data':active?'Smart Control enabled':first?first.inline_kw>0?'Inline heat candidate':first.action==='off'?'Coast through this interval':first.action==='dhw'?'Build hot-water reserve':'Use compressor heating':plan?.status==='coupled'?'Coupled circuit model needed':plan?.status==='infeasible'?'Model limits cannot be met':plan?.status==='insufficient'?'Waiting for a longer known horizon':plan?.status==='missing'?'Waiting for room or tank readings':'Waiting for a validated model';
      const forecastReason=this._error?'The previous plan is cleared until usable data returns.':active?'C1 leads; C2 demand is limited. The backend checks room readings before adjusting offsets, at most one step per cycle.':first?(first.inline_kw>0?'The bounded search found no compressor-only schedule within the model limits.':first.action==='off'?'The model can stay within its comfort and water limits without heating now.':first.action==='dhw'?'Heat the tank now while preserving capacity for the coming heating demand.':'Use available compressor capacity while respecting both zone limits.'):plan?.message||'Live prices and weather can be shown now. A plan needs explicit building, capacity and reserve assumptions.';
      const backendState=backend.status;
      const status=!controller?'Not running':!['on','off'].includes(controller.state)?'Controller unavailable':!active?'Paused':backendState&&!['unknown','unavailable'].includes(backendState)?backendState:'Backend update required';
      const messages={'Legacy backend detected':'Remove the old nibe_f750_trial.yaml package and restart Home Assistant. The integration is waiting to avoid duplicate controllers.', 'Write failed':'A setting request failed. Its write budget is reserved; control waits before another attempt.', 'Controller error':'The controller encountered an error. Check its Home Assistant logs.', 'Running':'C1 leads; C2 demand is limited. Control cycles run at least 15 minutes apart.', 'Starting':'Startup waiting period: 15 minutes before control can write.', 'Paused':'Control is paused. The last heat-pump settings remain applied.', 'Waiting for readings':'Control is waiting for valid, recent room and heat-pump readings.', 'Waiting for first cycle':'Enabled. Waiting for the first scheduled control cycle.', 'Controller not responding':'The backend has not completed a control cycle recently. Check its Home Assistant automation.', 'Not running':'Add NIBE F750 Smart Control under Settings → Devices & services after installing the HACS integration.', 'Backend update required':'Update the NIBE F750 integration and restart Home Assistant.', 'Controller unavailable':'Home Assistant cannot currently read the controller state.'};
      const title=this.config.demo?forecastTitle:status,reason=this.config.demo?forecastReason:messages[status]||'Check the controller in Home Assistant.';
      const groups=[];for(const s of steps){const p=groups.at(-1);if(p&&p.action===s.action&&p.hz===s.hz&&p.inline_kw===s.inline_kw)p.end=s.end;else groups.push({...s});}
      const sources=!this.config.demo?`<details ${this._error?'open':''}><summary>Sources & assumptions</summary>${this._pumps?.length>1?`<label>Heat pump</label><select data-source="device"><option value="">Choose</option>${this._pumps.map(d=>`<option value="${escapeHTML(d.id)}" ${d.id===this._device?'selected':''}>${escapeHTML(d.name_by_user||d.name||d.id)}</option>`).join('')}</select>`:''}<label>Hourly weather</label><select data-source="weather"><option value="">Choose SMHI/weather</option>${(this._weathers||[]).map(e=>`<option ${e.entity_id===this._weather?'selected':''}>${escapeHTML(e.entity_id)}</option>`).join('')}</select><label>Nord Pool prices</label><select data-source="price"><option value="">Choose</option>${(this._priceEntities||[]).map(e=>`<option ${e.entity_id===this._price?'selected':''}>${escapeHTML(e.entity_id)}</option>`).join('')}</select><p>Model capacities, heat loss and thermal storage are supplied assumptions, not learned measurements. Configure model and tariff settings in YAML. Control runs in the Home Assistant backend.</p></details>`:'';
      this.shadowRoot.innerHTML=`<style>${style}</style><ha-card><header><div><div class="eyebrow">NIBE / SMART CONTROL</div><h1>Heat ahead</h1></div><span class="badge">${this.config.demo?'Demo · planning preview':escapeHTML(status)}</span></header><div class="body">${this._error?`<div class="error">${escapeHTML(this._error)}</div>`:''}<section class="decision"><strong>${escapeHTML(title)}</strong><p>${escapeHTML(reason)}</p></section><div class="facts"><div class="fact"><div class="label">Price now</div><div class="value">${round(current?.price,2)} <small>${escapeHTML(market?.currency||this.config.currency)}/kWh</small></div></div><div class="fact"><div class="label">Forecast change</div><div class="value">${current&&last?`${last.outdoor-current.outdoor>=0?'+':''}${round(last.outdoor-current.outdoor)}`:'—'} <small>°C</small></div></div><div class="fact"><div class="label">${this.config.demo?'Planned inline heat':'Inline heat now'}</div><div class="value">${round(this.config.demo?plan?.auxiliary_kwh:this._hass?.states?.['sensor.vp_power_internal_add_heat']?.state)} <small>${this.config.demo?'kWh':'kW'}</small></div></div></div><div class="plots"><section class="plot"><h2>${steps.length?'Prices & operation':'Electricity prices'}</h2>${this.chart('price')}<div class="legend"><span><i style="background:#6ba68e"></i>Heating</span><span><i style="background:#86a9cf"></i>DHW</span><span><i style="background:#dbe6e9"></i>Coast</span><span><i style="background:#d59a58"></i>Inline candidate</span></div></section><section class="plot"><h2>Outdoor forecast</h2>${this.chart('weather')}</section></div><div class="zones">${(model?.zones||[{name:'Climate 1'},{name:'Climate 2'}]).map((z,i)=>`<div class="zone"><div class="label">${escapeHTML(z.name||`Climate ${i+1}`)}</div><strong>${round(this._initial?.temps?.[i])} °C</strong><div class="label">${z.min_c!==undefined?`${round(z.min_c)}–${round(z.max_c)} °C model bounds`:`Current target ${escapeHTML(this._telemetry?.targets?.[i]??'—')} °C`}</div>${steps.length?`<div class="label">Predicted ${round(Math.min(...steps.map(s=>s.temps[i])))}–${round(Math.max(...steps.map(s=>s.temps[i])))} °C</div>`:''}${!this.config.demo&&i===1?`<div class="label">Demand limited by C1 · target ceiling ${round(this._linkedTargets?.c2)} °C</div>`:''}${this._telemetry?`<div class="label">Offset ${escapeHTML(this._telemetry.offsets?.[i]??'—')}</div>`:''}</div>`).join('')}</div>${steps.length?`<p class="water-reserve">Hot water ${round(this._initial?.water)} °C · lowest modeled ${round(Math.min(...steps.map(s=>s.water)))} °C · model minimum ${round(model.dhw.min_c)} °C</p>`:''}${steps.length?`<details><summary>Schedule · ${groups.length} blocks</summary><table class="schedule"><thead><tr><th>From</th><th>Until</th><th>Action</th><th>Inline</th></tr></thead><tbody>${groups.map(g=>`<tr><td>${clock(g.start,market.tz)}</td><td>${clock(g.end,market.tz)}</td><td>${g.action==='off'?'Coast':g.action==='dhw'?'DHW':'Heat'}${g.hz?` · ${g.hz} Hz`:''}</td><td>${g.inline_kw?`${g.inline_kw} kW`:'—'}</td></tr>`).join('')}</tbody></table></details>`:''}<details><summary>Plan limits</summary><p>${escapeHTML(plan?.message||'No model-based schedule yet.')}</p><p>Bounded beam search; a candidate is not proof of a global optimum or that auxiliary heat is unavoidable. The F750 is an exhaust-air heat pump: outdoor weather drives building demand, not a direct outdoor-source COP multiplier. Live control, when enabled, runs through the Home Assistant backend.</p><p>${steps.length?`Modeled electricity ${round(plan.electrical_kwh)} kWh · modeled cost ${round(plan.cost,2)} ${escapeHTML(market.currency)}. `:''}Prices use the configured tariff basis; no savings or bill accuracy is claimed. ${market?.unpublished?'Tomorrow prices are unavailable; only known intervals are planned.':''}</p></details>${sources}${!this.config.demo&&!controller?'<p>Install the NIBE F750 integration through HACS, then add it under Devices & services.</p>':''}<div class="controls"><span class="source">${last?`Known horizon to ${when(last.end,market.tz)}`:'Waiting for forecast data'}</span>${controller?`<button id="control">${active?'Pause control':'Resume control'}</button>`:''}<button id="refresh" ${this._busy?'disabled':''}>Refresh</button></div></div></ha-card>`;
      this.shadowRoot.getElementById('control')?.addEventListener('click',async()=>{try{await this._hass.callService(backend.id.split('.')[0],active?'turn_off':'turn_on',{entity_id:backend.id});}catch(e){this._error=e.message;this.render();}});
      this.shadowRoot.getElementById('refresh')?.addEventListener('click',()=>this.refresh(true));
      this.shadowRoot.querySelectorAll('[data-source]').forEach(e=>e.addEventListener('change',()=>{this[`_${e.dataset.source}`]=e.value;this.refresh(true);}));
    }
  }
  customElements.define('nibe-f750-smart-card',F750SmartCard);
  window.customCards=window.customCards||[];window.customCards.push({type:'nibe-f750-smart-card',name:'NIBE Smart Control',description:'Price/weather planning and optional HA control for F750 heating.'});
}
