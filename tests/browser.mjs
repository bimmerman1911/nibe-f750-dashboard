import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const { chromium } = createRequire(import.meta.url)('playwright');
const browser = await chromium.launch({headless:true,args:['--no-sandbox'],...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
try {
  const page = await browser.newPage({viewport:{width:1400,height:1200}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${process.env.PREVIEW_URL || 'http://127.0.0.1:8080'}/demo/`);
  const card=page.locator('nibe-f750-card');
  await card.locator('.landscape [data-shower]').waitFor();
  assert.equal(await card.getByRole('img',{name:'Combined F750 refrigerant and hydraulic circuits'}).count(),1);
  assert.equal(await card.getByText('Smart control · planned').count(),0);
  assert.equal(await card.locator('[data-component="buffer"]').count(),0);
  assert.equal(await card.locator('[data-component="circulation-pump"]').count(),2);
  assert.equal(await card.locator('[data-shower] path').count(),0);
  assert.match(await card.locator('.landscape [data-reading="degree_minutes"]').textContent(),/-284/);
  assert.match(await card.locator('.landscape [data-reading="system_status"]').textContent(),/Heating/);
  assert.match(await card.locator('.landscape [data-component="heater"]').textContent(),/0 kW \(3 kW\)/);
  assert.equal(await card.locator('.landscape [data-weather-condition="partlycloudy"]').count(),1);
  await page.evaluate(()=>{const c=document.querySelector('nibe-f750-card');window.demoHass.states['weather.demo']={state:'rainy',attributes:{}};c.hass=window.demoHass;});
  assert.equal(await card.locator('.landscape [data-weather-condition="rainy"]').count(),1);
  await page.evaluate(()=>{const c=document.querySelector('nibe-f750-card');window.demoHass.states['weather.demo']={state:'partlycloudy',attributes:{}};c.hass=window.demoHass;});
  const topology=await card.evaluate(c=>[...c.shadowRoot.querySelectorAll('svg')].map(svg=>{
    const previous=svg.style.display;svg.style.display='block';
    const onPath=(path,point)=>{let best=Infinity;for(let i=0;i<=1000;i++){const p=path.getPointAtLength(path.getTotalLength()*i/1000);best=Math.min(best,Math.hypot(p.x-point.x,p.y-point.y));}return best;};
    const dot=id=>{const d=svg.querySelector(`[data-sensor="${id}"] circle`);return {x:+d.getAttribute('cx'),y:+d.getAttribute('cy')};};
    const path=name=>svg.querySelector(`[data-flow="${name}"] > path`);
    const heater=svg.querySelector('[data-component="heater"] rect').getBBox();
    const insideHeater=path=>{for(let i=0;i<=1000;i++){const p=path.getPointAtLength(path.getTotalLength()*i/1000);if(p.x>heater.x&&p.x<heater.x+heater.width&&p.y>heater.y&&p.y<heater.y+heater.height)return true;}return false;};
    const port=svg.querySelector('[data-component="diverter"] circle');
    const samePort=name=>{const p=path(name).getPointAtLength(0);return p.x===+port.getAttribute('cx')&&p.y===+port.getAttribute('cy');};
    const outlet=svg.querySelector('[data-sensor="BT21"]').getBBox();
    const refLeft=path('refrigerant-suction').getPointAtLength(0).x;
    const result={sensors:[...svg.querySelectorAll('[data-sensor]')].map(e=>e.dataset.sensor),outletOutside:outlet.x+outlet.width<refLeft,bt21OnAir:onPath(path('air-outlet'),dot('BT21'))<3,bt15OnLiquid:onPath(path('refrigerant-liquid'),dot('BT15'))<3,bt63OnCommon:onPath(path('water-common-supply'),dot('BT63'))<3,commonHasHeater:insideHeater(path('water-common-supply')),branchesAfterHeater:['water-heating-supply','water-dhw-supply'].every(name=>samePort(name)&&!insideHeater(path(name)))};
    svg.style.display=previous;return result;
  }));
  for(const t of topology) {
    assert.deepEqual(t.sensors.slice().sort(),['BT1','C1','C2','BT3','BT6','BT7','BT12','BT14','BT15','BT16','BT17','BT20','BT21','BT61','BT62','BT63'].sort());
    for(const key of ['outletOutside','bt21OnAir','bt15OnLiquid','bt63OnCommon','commonHasHeater','branchesAfterHeater']) assert.equal(t[key],true,key);
  }
  const headerMappings=await page.evaluate(async()=>{
    const {discoverEntities}=await import('/dist/nibe-f750-card.js');
    return discoverEntities(['sensor.vp_degree_minutes_2','sensor.vp_status','select.vp_set_max_electrical_add'].map(entity_id=>({entity_id,platform:'myuplink',device_id:'pump',unique_id:entity_id})),'pump').entities;
  });
  assert.equal(headerMappings.degree_minutes,'sensor.vp_degree_minutes_2');
  assert.equal(headerMappings.system_status,'sensor.vp_status');
  assert.equal(headerMappings.heater_limit,'select.vp_set_max_electrical_add');
  const extraSensors=await page.evaluate(async()=>{
    const {discoverEntities}=await import('/dist/nibe-f750-card.js');
    const entries=[['charge','40014'],['gas','40018'],['suction','40022'],['heating_out','40047'],['heating_back','40048']].map(([name,id])=>({platform:'myuplink',device_id:'pump',entity_id:`sensor.${name}`,unique_id:`cloud-${id}`}));
    entries.push({platform:'myuplink',device_id:'pump',entity_id:'sensor.temp_after_heater_bt63',unique_id:'cloud-unknown'});
    return discoverEntities(entries,'pump').entities;
  });
  assert.equal(extraSensors.hot_water,undefined); // BT6 must not be relabeled BT7.
  assert.deepEqual(extraSensors,{hot_water_charge:'sensor.charge',hot_gas:'sensor.gas',suction:'sensor.suction',heating_supply:'sensor.heating_out',heating_return:'sensor.heating_back',heater_out:'sensor.temp_after_heater_bt63'});
  const active=name=>card.locator(`.portrait [data-flow="${name}"] .flow:not(.paused)`).count();
  assert.equal(await active('air-outlet'),1);
  assert.equal(await active('water-heating-supply'),1);
  assert.equal(await active('water-dhw-supply'),0);
  await card.evaluate(c=>{window.demoHass.states={...window.demoHass.states,'sensor.demo_operation':{state:'Hot water',attributes:{}}};c.hass=window.demoHass;});
  assert.equal(await active('water-heating-supply'),0);
  assert.equal(await active('water-dhw-supply'),1);
  await card.evaluate(c=>{window.demoHass.states={...window.demoHass.states,'sensor.demo_operation':{state:'Space heating',attributes:{}}};c.hass=window.demoHass;});
  const cases=await page.evaluate(async()=>{
    const {calculateHeat,discoverEntities}=await import('/dist/nibe-f750-card.js');
    const state=(value,unit)=>({state:String(value),attributes:{unit_of_measurement:unit}});
    const entities={compressor_frequency:'f',condenser_water_out:'bt12',reference_air_flow:'ref',air_flow:'air',exhaust_air:'extract',leaving_air:'discharge',water_flow:'bad_flow',return:'bad_return',compressor_power:'unused_power',heater_power:'heater'};
    const base={f:state(50,'Hz'),bt12:state(45,'°C'),ref:state(180,'M3/h'),air:state(150,'m³/h'),extract:state(21,'°C'),discharge:state(-3,'°C')};
    const run=changes=>calculateHeat({...base,...changes},entities);
    const registry=[{platform:'myuplink',device_id:'pump',entity_id:'sensor.vp_reference_air_speed_sensor',unique_id:'device-new-id'},{platform:'myuplink',device_id:'pump',entity_id:'sensor.vp_condenser_out_bt12',unique_id:'device-new-bt12-id'},{platform:'myuplink',device_id:'pump',entity_id:'sensor.vp_current_compressor_frequency',unique_id:'device-new-frequency-id'}];
    return {normal:run({}),warmer:run({bt12:state(55,'°C')}),cooler:run({bt12:state(35,'°C')}),fahrenheit:run({bt12:state(113,'°F')}),litres:run({ref:state(50,'l/s')}),off:run({f:state(0,'Hz')}),badFrequency:run({f:state(-1,'Hz')}),wrongFrequencyUnit:run({f:state(50,'rpm')}),blank:run({f:state('','Hz')}),missingBT12:run({bt12:state('unavailable','°C')}),badModel:run({bt12:state(-100,'°C')}),wrongFlowUnit:run({ref:state(60,'%'),air:state('unavailable','m³/h')}),measuredFallback:run({ref:state('unavailable','m³/h')}),reversedAir:run({discharge:state(30,'°C')}),missing:calculateHeat({},entities),corrupt:run({bad_flow:state(999999,'l/min'),bad_return:state(-999,'°C'),unused_power:state(9999,'kW'),heater:state(6,'kW')}),found:discoverEntities(registry,'pump').entities};
  });
  assert.ok(Math.abs(cases.normal.compressor-.805)<1e-10);
  assert.ok(Math.abs(cases.warmer.compressor-.909)<1e-10);
  assert.ok(Math.abs(cases.cooler.compressor-.701)<1e-10);
  assert.ok(Math.abs(cases.normal.qEvaporator-1.44864)<1e-10);
  assert.ok(Math.abs(cases.normal.qCondenser-2.25364)<1e-10);
  assert.equal(cases.normal.compressorMethod,'frequency-bt12');
  assert.equal(cases.normal.evaporatorMethod,'reference-sensible');
  assert.deepEqual(cases.fahrenheit,cases.normal);
  assert.ok(Math.abs(cases.litres.qEvaporator-cases.normal.qEvaporator)<1e-10);
  assert.equal(cases.off.compressor,0);
  for(const key of ['badFrequency','wrongFrequencyUnit','blank','missingBT12','badModel','missing']) {
    assert.equal(cases[key].compressor,null,key);
    assert.equal(cases[key].qCondenser,null,key);
  }
  assert.equal(cases.wrongFlowUnit.qEvaporator,null);
  assert.equal(cases.wrongFlowUnit.qCondenser,null);
  assert.equal(cases.reversedAir.qEvaporator,null);
  assert.equal(cases.reversedAir.qCondenser,null);
  assert.equal(cases.measuredFallback.evaporatorMethod,'sensible');
  assert.deepEqual(cases.corrupt,cases.normal);
  assert.equal(cases.found.reference_air_flow,'sensor.vp_reference_air_speed_sensor');
  assert.equal(cases.found.condenser_water_out,'sensor.vp_condenser_out_bt12');
  assert.equal(cases.found.compressor_frequency,'sensor.vp_current_compressor_frequency');
  // Keep the requested light palette even when the surrounding HA theme is dark.
  await page.evaluate(()=>document.body.style.setProperty('--primary-text-color','#fff'));
  assert.equal(await card.locator('ha-card').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');
  assert.equal(await card.locator('header,.stats,.controls,details').count(),0);
  assert.equal(await card.getByRole('button').count(),0);
  assert.equal(await card.locator('.portrait .energy').evaluateAll(es=>es.length===3&&es.every(e=>getComputedStyle(e).fontWeight==='700'&&parseFloat(getComputedStyle(e).fontSize)>=15)),true);
  const airColors=await card.evaluate(c=>{
    const svg=c.shadowRoot.querySelector('.landscape');
    return [getComputedStyle(svg.querySelector('[data-flow="air-inlet"] .flow')).stroke,getComputedStyle(svg.querySelector('[data-flow="air-outlet"] .flow')).stroke];
  });
  assert.deepEqual(airColors,['rgb(197, 77, 67)','rgb(57, 136, 194)']);
  for(const state of ['0','off','unavailable','unknown','-1','']) {
    await card.evaluate((c,state)=>{window.demoHass.states={...window.demoHass.states,'sensor.demo_compressor_frequency':{state,attributes:{unit_of_measurement:'Hz'}}};c.hass=window.demoHass;},state);
    assert.equal(await card.locator('[data-flow^="refrigerant"] .flow:not(.paused)').count(),0,state);
    assert.equal(await active('air-outlet'),1);
  }
  await card.evaluate(c=>{
    c.config.entities.compressor_status='sensor.demo_status';
    window.demoHass.states={...window.demoHass.states,'sensor.demo_compressor_frequency':{state:'52',attributes:{unit_of_measurement:'Hz'}},'sensor.demo_status':{state:'Stopped',attributes:{}}};c.hass=window.demoHass;
  });
  assert.equal(await card.locator('[data-flow^="refrigerant"] .flow:not(.paused)').count(),0);
  await card.evaluate(c=>{delete c.config.entities.compressor_status;window.demoHass.states={...window.demoHass.states,'sensor.demo_compressor_frequency':{state:'52',attributes:{unit_of_measurement:'Hz'}}};c.hass=window.demoHass;});
  assert.equal(await active('refrigerant-suction'),1);
  const showers=await page.evaluate(async()=>{
    const {calculateShowerTime}=await import('/dist/nibe-f750-card.js');
    const state=(value,unit)=>({state:String(value),attributes:{unit_of_measurement:unit}});
    const map={hot_water:'top',hot_water_charge:'bottom',shower_minutes:'reported'};
    const run=(states,config)=>calculateShowerTime(states,map,config);
    return {estimate:run({top:state(50,'°C'),bottom:state(45,'°C')}),reported:run({reported:state(16,'min')}),seconds:run({reported:state(960,'s')}),cold:run({top:state(35,'°C'),bottom:state(30,'°C')}),missing:run({top:state(50,'°C')}),badFlow:run({top:state(50,'°C'),bottom:state(45,'°C')},{flow_l_min:0}),percent:run({reported:state(16,'%')})};
  });
  assert.ok(Math.abs(showers.estimate.minutes-22.5)<1e-10);
  assert.equal(showers.estimate.estimated,true);
  assert.equal(showers.reported.minutes,16);
  assert.equal(showers.reported.estimated,false);
  assert.equal(showers.seconds.minutes,16);
  assert.equal(showers.cold.minutes,0);
  for(const key of ['missing','badFlow','percent']) assert.equal(showers[key],null,key);
  await page.getByRole('button',{name:'Toggle unavailable readings'}).click();
  assert.match(await card.locator('.portrait').textContent(),/—/);
  assert.equal(await card.locator('.flow:not(.paused)').count(),0);
  await page.getByRole('button',{name:'Toggle unavailable readings'}).click();
  await page.screenshot({path:'docs/dashboard.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.equal(await card.evaluate(e=>e.shadowRoot.querySelector('ha-card').scrollWidth>e.clientWidth),false);
  const scheme=card.getByRole('region',{name:'Combined circuit diagram',exact:true});
  for(const width of [375,390,430]) {
    await page.setViewportSize({width,height:844});
    assert.equal(await scheme.evaluate(e=>e.scrollWidth>e.clientWidth),false);
    assert.equal(await card.locator('.portrait').isVisible(),true);
    assert.equal(await card.locator('.landscape').isVisible(),false);
  }
  await page.setViewportSize({width:390,height:844});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await card.locator('.portrait .flow').evaluateAll(es=>es.every(e=>getComputedStyle(e).animationName==='none')),true);
  await page.screenshot({path:'docs/mobile.png',fullPage:true});
  await page.evaluate(()=>{
    const c=document.querySelector('nibe-f750-card');
    c.setConfig({entities:{outdoor:'sensor.missing'},controls:{heating:'switch.unsupported'}});
    c.hass={states:{},callService:()=>{throw new Error('must not write');}};
  });
  assert.equal(await card.getByRole('button').count(),0);
  assert.match(await card.locator('.portrait [data-sensor="BT1"]').textContent(),/—/);
  await page.evaluate(()=>{
    const c=document.querySelector('nibe-f750-card');
    const registry=[
      {entity_id:'sensor.renamed_outside',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-40004'},
      {entity_id:'sensor.disabled_room',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-40033',disabled_by:'user'},
      {entity_id:'number.renamed_offset',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-47011'},
      {entity_id:'sensor.unrelated',platform:'other',device_id:'pump',unique_id:'cloud-device-40013'},
      {entity_id:'sensor.vp_current_compressor_frequency',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-new-frequency'},
      {entity_id:'sensor.vp_target_compressor_frequency',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-target'},
      {entity_id:'sensor.vp_current_max_compressor_frequency',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-max'},
      {entity_id:'sensor.other_current_compressor_frequency',platform:'myuplink',device_id:'other-pump',unique_id:'other-device-freq'},
      {entity_id:'sensor.raw',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-49994-raw'},
    ];
    window.autoRegistry=registry;
    window.autoDevices=[{id:'pump',model:'F750',name:'My heat pump'}];
    window.autoHass={states:{'sensor.vp_current_compressor_frequency':{state:'57',attributes:{unit_of_measurement:'Hz'}},'sensor.renamed_outside':{state:'7',attributes:{unit_of_measurement:'°C'}},'number.renamed_offset':{state:'0',attributes:{min:-10,max:10,step:1}}},callWS:async({type})=>type.includes('entity_registry')?window.autoRegistry:window.autoDevices};
    c.setConfig({type:'custom:nibe-f750-card'});c.hass=window.autoHass;
  });
  await page.waitForFunction(()=>document.querySelector('nibe-f750-card')._discovered);
  assert.match(await card.locator('.portrait').textContent(),/7/);
  assert.equal(await card.getByRole('spinbutton').count(),0);
  assert.deepEqual(await card.evaluate(c=>Object.keys(c.config.entities)),['outdoor','compressor_frequency']);
  assert.equal(await card.evaluate(c=>c.config.entities.compressor_frequency),'sensor.vp_current_compressor_frequency');
  assert.match(await card.locator('.portrait').textContent(),/57/);
  // Ambiguous same-device names remain unmapped, rather than picking arbitrarily.
  await page.evaluate(()=>window.autoRegistry.push({entity_id:'sensor.duplicate',original_name:'Current compressor frequency',platform:'myuplink',device_id:'pump',unique_id:'other-unknown-frequency'}));
  await card.evaluate(c=>c.discover(true));
  await page.waitForFunction(()=>!document.querySelector('nibe-f750-card').config.entities.compressor_frequency);
  await page.evaluate(()=>window.autoRegistry.pop());
  await page.evaluate(()=>{
    window.autoDevices=[{id:'pump',model:'F750',name:'First'},{id:'pump2',model:'F750',name:'Second'}];
    window.autoRegistry.push({entity_id:'sensor.second',platform:'myuplink',device_id:'pump2',unique_id:'second-40004'});
    const c=document.querySelector('nibe-f750-card');c.setConfig({type:'custom:nibe-f750-card'});
  });
  await card.getByText('Choose your heat pump below.').waitFor();
  assert.equal(await card.getByRole('spinbutton').count(),0);
  await card.locator('#device').selectOption('pump');
  await page.waitForFunction(()=>document.querySelector('nibe-f750-card')._selectedDevice==='pump');
  await card.evaluate(c=>c.setConfig({type:'custom:nibe-f750-card',device_id:'pump2'}));
  await page.waitForFunction(()=>document.querySelector('nibe-f750-card').config.entities.outdoor==='sensor.second');
  assert.equal(await card.getByRole('spinbutton').count(),0);
  await page.evaluate(()=>{window.autoHass.callWS=async()=>{throw new Error('disconnected');};});
  await card.evaluate(c=>c.discover(true));
  await card.getByText(/Discovery failed/).waitFor();
  await page.evaluate(()=>{
    const c=document.querySelector('nibe-f750-card');
    const state=(value,unit)=>({state:String(value),attributes:{unit_of_measurement:unit}});
    c.setConfig({entities:{compressor_frequency:'f',condenser_water_out:'bt12',reference_air_flow:'ref',exhaust_air:'extract',leaving_air:'discharge'}});
    c.hass={states:{f:state(50,'Hz'),bt12:state(45,'°C'),ref:state(180,'M3/h'),extract:state(21,'°C'),discharge:state(-3,'°C')},callWS:async()=>{throw new Error('No history calls are needed');}};
  });
  assert.match(await card.locator('.portrait').textContent(),/P = 0.8 kW/);
  assert.match(await card.locator('.portrait').textContent(),/Q = 2.25 kW/);
  await card.evaluate(c=>{c.hass={...c._hass,states:{...c._hass.states,f:{state:'100',attributes:{unit_of_measurement:'Hz'}}}};});
  assert.match(await card.locator('.portrait').textContent(),/P = 1.61 kW/);
  // Simulate a Sections grid followed by another card, including a resize.
  for(const width of [390,1100,500]) {
    await page.setViewportSize({width,height:1500});
    await page.evaluate(()=>{
      const card=document.querySelector('nibe-f750-card');
      let grid=document.querySelector('#layout-check');
      if(!grid){
        grid=document.createElement('div');grid.id='layout-check';
        grid.style.cssText='display:grid;grid-template-columns:minmax(0,1fr);grid-auto-rows:minmax(56px,auto);gap:8px;';
        card.parentNode.insertBefore(grid,card);grid.append(card);
        const next=document.createElement('div');next.id='next-card';next.style.height='80px';grid.append(next);
      }
      const rows=card.getGridOptions().rows;
      card.style.gridRow=rows==='auto'?'auto':`span ${rows}`;
    });
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const layout=await card.evaluate(c=>({rows:c.getGridOptions().rows,
      bottom:c.shadowRoot.querySelector('ha-card').getBoundingClientRect().bottom,
      height:c.shadowRoot.querySelector('ha-card').getBoundingClientRect().height,
      next:document.querySelector('#next-card').getBoundingClientRect().top,size:c.getCardSize()}));
    assert.equal(layout.rows,'auto');
    assert.ok(layout.next>=layout.bottom,`Following card overlaps at width ${width}`);
    assert.ok(layout.size*50>=layout.height);
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: diagram-only layout, formulas, topology, compressor stop states, air colors, shower time, mobile layout and device discovery.');
} finally { await browser.close(); }
