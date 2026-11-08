import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {normalizePrices,normalizeForecast,buildTimeline,planHeat,fetchMarket,linkedCircuitTargets} from '../dist/nibe-f750-smart-card.js';
const model=JSON.parse(fs.readFileSync(new URL('../examples/smart-control/demo-model.json',import.meta.url)));
const base=Date.parse('2026-11-08T00:00:00Z'),iso=t=>new Date(t).toISOString();
const initial={temps:[20.1,20.1],water:49,running:false};
const slots=(count=96,out=-4)=>Array.from({length:count},(_,i)=>({start:base+i*900000,end:base+(i+1)*900000,dt:.25,outdoor:out,price:i<20?.35:i<40?2.4:i<65?.8:1.4}));
test('normalizes MWh once, accepts negative prices and applies explicit tariff',()=>{
  const row=[{start:iso(base),end:iso(base+900000),price:-200}];
  assert.equal(normalizePrices(row,{unit:'SEK/MWh'})[0].price,-.2);
  assert.ok(Math.abs(normalizePrices(row,{unit:'SEK/MWh',extra_per_kwh:.5,vat_percent:25})[0].price-.375)<1e-10);
  assert.equal(normalizePrices([{...row[0],value:50,price:undefined}],{unit:'öre/kWh'})[0].price,.5);
  assert.throws(()=>normalizePrices(row,{unit:'kr'}));
  assert.throws(()=>normalizePrices([{...row[0],price:null}],{unit:'SEK/MWh'}));
  assert.throws(()=>normalizePrices([{...row[0],start:'2026-10-25T02:00:00'}],{unit:'SEK/MWh'}));
});
test('handles explicit DST offsets, hourly to quarter-hour expansion and gaps',()=>{
  const rows=[{start:'2026-10-25T02:00:00+02:00',end:'2026-10-25T02:00:00+01:00',value:1},{start:'2026-10-25T02:00:00+01:00',end:'2026-10-25T03:00:00+01:00',value:2}];
  const p=normalizePrices(rows,{unit:'SEK/kWh'}),start=p[0].start;
  const w=normalizeForecast(Array.from({length:4},(_,i)=>({datetime:iso(start-3600000+i*3600000),temperature:32+i*9})),'°F');
  const timeline=buildTimeline(p,w,start,3);
  assert.equal(timeline.length,8);
  assert.equal(timeline[4].price,2);
  assert.equal(timeline.reduce((s,r)=>s+r.dt,0),2);
  const gap=[p[0],{...p[1],start:p[1].start+900000}];
  assert.equal(buildTimeline(gap,w,start,3).length,4);
  assert.throws(()=>normalizePrices([rows[0],rows[0]],{unit:'SEK/kWh'}));
});
test('shared compressor-only schedule preserves both zones, water bounds and terminal reserve',()=>{
  const r=slots().map((s,i)=>({...s,outdoor:-4+9*i/95}));
  const p=planHeat(r,model,initial);
  assert.equal(p.status,'preview');assert.equal(p.compressorOnly,true);assert.equal(p.auxiliary_kwh,0);assert.equal(p.steps.length,r.length);
  for(const s of p.steps){assert.ok(s.temps.every((t,i)=>t>=model.zones[i].min_c-1e-8&&t<=model.zones[i].max_c+1e-8));assert.ok(s.water>=model.dhw.min_c-1e-8&&s.water<=model.dhw.max_c+1e-8);assert.ok(['off','heat','dhw'].includes(s.action));}
  assert.ok(p.steps.at(-1).temps.every((t,i)=>t>=model.zones[i].target_c-1e-8));
  assert.ok(p.steps.at(-1).water>=model.dhw.target_c-1e-8);
  // Same forecast capacity must cover heat and tank; neither is delivered in parallel.
  assert.ok(p.steps.some(s=>s.action==='dhw'));
  assert.ok(p.steps.some(s=>s.action==='heat'));
});
test('warming forecast changes demand and reduces modeled consumption',()=>{
  const cold=planHeat(slots(96,-8),model,initial),warm=planHeat(slots(96,7),model,initial);
  assert.equal(cold.status,'preview');assert.equal(warm.status,'preview');
  assert.ok(warm.electrical_kwh<cold.electrical_kwh);
  assert.equal(warm.auxiliary_kwh,0);
});
test('limited capacity produces inline candidate or explicit infeasibility, never a silent violation',()=>{
  const weak={...model,heat_high_kw:1.7,heat_low_kw:1.1};
  const p=planHeat(slots(96,-8),weak,initial);
  assert.ok(p.status==='infeasible'||p.auxiliary_kwh>0);
  const impossible=planHeat(slots(96,-50),{...weak,inline_step_kw:.5},initial);
  assert.equal(impossible.status,'infeasible');assert.equal(impossible.steps.length,0);
});
test('finds bounded inline support when compressor capacity is below immediate heat loss',()=>{
  const m={...model,zones:[{...model.zones[0],loss_kw_per_k:.12,capacity_kwh_per_k:5,min_c:20,max_c:21,target_c:20,heat_share:1}],heat_high_kw:3,dhw:{...model.dhw,loss_kw_per_k:0,min_c:20,max_c:55,target_c:20}};
  const p=planHeat(slots(24,-10),m,{temps:[20],water:20,running:false});
  assert.equal(p.status,'preview');assert.equal(p.compressorOnly,false);assert.ok(p.auxiliary_kwh>0);
  assert.ok(p.steps.every(s=>s.temps[0]>=20-1e-8&&s.inline_kw<=m.inline_step_kw));
});
test('prepares tank reserve before a scheduled draw and retains comfort in a cold scenario',()=>{
  const m={...model,dhw:{...model.dhw,draws:[{at:iso(base+7*3600000),kwh:1.1}]}};
  const p=planHeat(slots(96,-15),m,initial);
  assert.equal(p.status,'preview');assert.equal(p.compressorOnly,true);
  const before=p.steps.find(s=>s.end===base+7*3600000);
  assert.ok(before.water-1.1/model.dhw.capacity_kwh_per_k>=model.dhw.min_c-1e-8);
});
test('negative prices remain finite and do not bypass the compressor-only policy',()=>{
  const p=planHeat(slots().map(s=>({...s,price:-1})),model,initial);
  assert.equal(p.status,'preview');assert.equal(p.auxiliary_kwh,0);assert.ok(p.cost<0);
});
test('rejects missing inputs, malformed DHW events and insufficient horizons',()=>{
  assert.equal(planHeat(slots(8),model,initial).status,'insufficient');
  assert.equal(planHeat(slots(),model,{temps:[null,20],water:49}).status,'missing');
  assert.throws(()=>planHeat(slots(),{...model,dhw:{...model.dhw,draws:[{at:'tomorrow morning',kwh:2}]}},initial));
  assert.throws(()=>planHeat(slots(),{...model,heat_high_kw:'4'},initial));
});
test('weather and official Nord Pool use HA read actions with MWh conversion',async()=>{
  const calls=[],hass={config:{time_zone:'Europe/Stockholm'},states:{'weather.smhi_home':{attributes:{temperature_unit:'°C'}}},callWS:async r=>{
    calls.push(r);assert.equal(r.type,'call_service');
    if(r.domain==='weather')return {response:{'weather.smhi_home':{forecast:[{datetime:iso(base),temperature:0},{datetime:iso(base+3600000),temperature:1}]}}};
    if(calls.filter(c=>c.domain==='nordpool').length>1)throw Error('tomorrow unpublished');
    return {response:{SE3:[{start:iso(base),end:iso(base+3600000),price:500}]}};
  }};
  const r=await fetchMarket(hass,{nordpool_entry:'entry',area:'SE3',currency:'SEK'},[],'weather.smhi_home',null);
  assert.equal(r.prices[0].price,.5);assert.equal(r.unpublished,true);
  assert.ok(calls.every(c=>['weather','nordpool'].includes(c.domain)));
});
test('existing custom Nord Pool raw prices need no direct API call',async()=>{
  const hass={config:{time_zone:'Europe/Stockholm'},states:{'weather.smhi_home':{attributes:{temperature_unit:'°C'}},'sensor.nordpool':{attributes:{unit_of_measurement:'SEK/kWh',raw_today:[{start:iso(base),end:iso(base+3600000),value:1.25}],raw_tomorrow:[],tomorrow_valid:false}}},callWS:async r=>{assert.equal(r.domain,'weather');return {response:{'weather.smhi_home':{forecast:[{datetime:iso(base),temperature:0},{datetime:iso(base+3600000),temperature:1}]}}};}};
  const r=await fetchMarket(hass,{},[],'weather.smhi_home','sensor.nordpool');assert.equal(r.prices[0].price,1.25);assert.equal(r.unpublished,true);
});

test('C2 follows the supplied ceiling rule without inventing hydraulic shares',()=>{
  assert.deepEqual(linkedCircuitTargets(20,18.2),{c1:20,c2:19});
  assert.deepEqual(linkedCircuitTargets(19,21.5),{c1:19,c2:19});
  assert.deepEqual(linkedCircuitTargets(20,19),{c1:20,c2:19});
  assert.deepEqual(linkedCircuitTargets(20,null),{c1:20,c2:null});
});
