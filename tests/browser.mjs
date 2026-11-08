import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const { chromium } = createRequire(import.meta.url)('playwright');
const browser = await chromium.launch({headless:true,args:['--no-sandbox'],...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
try {
  const page = await browser.newPage({viewport:{width:1400,height:1200}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${process.env.PREVIEW_URL || 'http://127.0.0.1:8080'}/demo/`);
  const card=page.locator('nibe-f750-card');
  await card.getByText('Demo data',{exact:true}).waitFor();
  assert.equal(await card.getByRole('img',{name:'Combined F750 refrigerant and hydraulic circuits'}).count(),1);
  assert.equal(await card.getByText('Smart control · planned').count(),0);
  const heatCases=await page.evaluate(async()=>{
    const {calculateHeat}=await import('/dist/nibe-f750-card.js');
    const state=(state,unit)=>({state:String(state),attributes:{unit_of_measurement:unit}});
    const entities={compressor_power:'p',water_flow:'flow',condenser_water_out:'out',return:'back',air_flow:'air',exhaust_air:'extract',leaving_air:'discharge'};
    const base={p:state(950,'W'),flow:state(10,'l/min'),out:state(35,'°C'),back:state(30,'°C'),air:state(180,'m³/h'),extract:state(21,'°C'),discharge:state(-3,'°C')};
    const run=changes=>calculateHeat({...base,...changes},entities);
    return {normal:run({}),equivalent:run({p:state(.95,'kW'),flow:state(.6,'m³/h'),out:state(95,'°F'),back:state(86,'°F')}),airOnly:run({flow:state('unavailable','l/min')}),unknownAirUnit:run({flow:state('unavailable','l/min'),air:state(180,'')}),negativeDelta:run({out:state(20,'°C')}),missing:calculateHeat({},entities),off:run({p:state(0,'W'),air:state('unavailable','m³/h')}),energyInsteadOfPower:run({p:state(50,'kWh')}),blank:run({p:state(' ','W')})};
  });
  assert.ok(Math.abs(heatCases.normal.qCondenser-3.472883333333333)<1e-8);
  assert.ok(Math.abs(heatCases.normal.qEvaporator-2.522883333333333)<1e-8);
  assert.equal(heatCases.normal.compressor,.95);
  assert.deepEqual(heatCases.equivalent,heatCases.normal);
  assert.ok(Math.abs(heatCases.airOnly.qEvaporator-1.44864)<1e-8);
  assert.equal(heatCases.airOnly.evaporatorMethod,'sensible');
  assert.equal(heatCases.unknownAirUnit.qEvaporator,null);
  assert.equal(heatCases.negativeDelta.qCondenser,null);
  assert.equal(heatCases.missing.compressor,null);
  assert.equal(heatCases.missing.qCondenser,null);
  assert.equal(heatCases.off.qEvaporator,null);
  assert.equal(heatCases.energyInsteadOfPower.compressor,null);
  assert.equal(heatCases.blank.compressor,null);
  const energyCases=await page.evaluate(async()=>{
    const {powerFromEnergy,calculateHeat,discoverEntities}=await import('/dist/nibe-f750-card.js');
    const now=Date.now(),row=(seconds,value,unit='kWh')=>({s:String(value),a:{unit_of_measurement:unit},lu:(now-seconds*1000)/1000});
    const run=rows=>powerFromEnergy(rows,now);
    return {valid:run([row(601,10),row(1,10.2)]),wh:run([row(601,10000,'Wh'),row(1,10200,'Wh')]),reset:run([row(601,10),row(300,0),row(1,1)]),unitless:run([row(601,10,''),row(1,11,'')]),hours:run([row(601,10,'h'),row(1,11,'h')]),stale:run([row(900,10),row(300,11)]),short:run([row(120,10),row(1,11)]),gap:run([row(601,10),row(300,'unavailable'),row(1,11)]),flat:run([row(601,10),row(1,10)]),averageHeat:calculateHeat({}, {}, {power:1.2,minutes:10}),found:discoverEntities([{platform:'myuplink',device_id:'pump',entity_id:'sensor.energy',unique_id:'renamed-device-43144'}],'pump').entities};
  });
  assert.ok(Math.abs(energyCases.valid.power-1.2)<1e-10);
  assert.equal(energyCases.valid.minutes,10);
  assert.ok(Math.abs(energyCases.wh.power-energyCases.valid.power)<1e-10);
  assert.equal(energyCases.wh.minutes,energyCases.valid.minutes);
  for(const key of ['reset','unitless','hours','stale','short','gap']) assert.equal(energyCases[key],null,key);
  assert.equal(energyCases.flat.power,0);
  assert.equal(energyCases.averageHeat.compressorMethod,'energy-average');
  assert.equal(energyCases.averageHeat.evaporatorMethod,null);
  assert.equal(energyCases.found.compressor_energy,'sensor.energy');
  // Keep the requested light palette even when the surrounding HA theme is dark.
  await page.evaluate(()=>document.body.style.setProperty('--primary-text-color','#fff'));
  assert.equal(await card.locator('ha-card').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');
  await page.evaluate(()=>{window.calls=[];const original=window.demoHass.callService;window.demoHass.callService=async(...args)=>{window.calls.push(args);await original(...args);};});
  const heating=card.getByRole('spinbutton');
  await heating.fill('3');
  page.once('dialog',d=>d.accept());
  await card.getByRole('button',{name:'Apply',exact:true}).first().click();
  await card.getByRole('status').filter({hasText:'Demo setting updated'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),['number','set_value',{entity_id:'number.demo_heating',value:3}]);
  await heating.fill('100');
  await card.getByRole('button',{name:'Apply',exact:true}).first().click();
  assert.match(await card.getByRole('status').textContent(),/valid value/);
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  await heating.fill('2');
  page.once('dialog',d=>d.dismiss());
  await card.getByRole('button',{name:'Apply',exact:true}).first().click();
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  await card.getByRole('combobox').selectOption('Economy');
  page.once('dialog',d=>d.accept());
  await card.getByRole('button',{name:'Apply',exact:true}).last().click();
  await page.waitForFunction(()=>window.calls.length===2);
  assert.deepEqual(await page.evaluate(()=>window.calls[1]),['select','select_option',{entity_id:'select.demo_hot_water',option:'Economy'}]);
  await page.evaluate(()=>{window.demoHass.callService=async()=>{throw new Error('denied');};});
  page.once('dialog',d=>d.accept());
  await card.getByRole('button',{name:'Apply',exact:true}).last().click();
  await card.getByRole('status').filter({hasText:'could not be sent'}).waitFor();
  await page.getByRole('button',{name:'Toggle unavailable readings'}).click();
  assert.match(await card.locator('.stats').textContent(),/—/);
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
  assert.equal(await card.locator('.portrait .flow').evaluate(e=>getComputedStyle(e).animationName),'none');
  await page.screenshot({path:'docs/mobile.png',fullPage:true});
  await page.evaluate(()=>{
    const c=document.querySelector('nibe-f750-card');
    c.setConfig({entities:{outdoor:'sensor.missing'},controls:{heating:'switch.unsupported'}});
    c.hass={states:{},callService:()=>{throw new Error('must not write');}};
  });
  assert.equal(await card.getByRole('button').count(),0);
  assert.match(await card.locator('.pill').first().textContent(),/0\/1/);
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
  await card.getByText(/2 readings discovered|1 readings discovered/).waitFor();
  assert.match(await card.locator('.stats').textContent(),/7/);
  assert.equal(await card.getByRole('spinbutton').count(),1);
  assert.deepEqual(await card.evaluate(c=>Object.keys(c.config.entities)),['outdoor','compressor_frequency']);
  assert.equal(await card.evaluate(c=>c.config.entities.compressor_frequency),'sensor.vp_current_compressor_frequency');
  assert.match(await card.locator('.stats').textContent(),/57/);
  // Ambiguous same-device names remain unmapped, rather than picking arbitrarily.
  await page.evaluate(()=>window.autoRegistry.push({entity_id:'sensor.duplicate',original_name:'Current compressor frequency',platform:'myuplink',device_id:'pump',unique_id:'other-unknown-frequency'}));
  await card.getByRole('button',{name:'Refresh discovery'}).click();
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
  await card.getByRole('spinbutton').waitFor();
  await card.locator('#device').selectOption('pump2');
  await page.waitForFunction(()=>document.querySelector('nibe-f750-card').config.entities.outdoor==='sensor.second');
  assert.equal(await card.getByRole('spinbutton').count(),0);
  await page.evaluate(()=>{window.autoHass.callWS=async()=>{throw new Error('disconnected');};});
  await card.getByRole('button',{name:'Refresh discovery'}).click();
  await card.getByText(/Discovery failed/).waitFor();
  await page.evaluate(()=>{
    const c=document.querySelector('nibe-f750-card'),now=Date.now();window.historyRequests=[];
    c.hass={states:{'sensor.energy':{state:'10.2',attributes:{unit_of_measurement:'kWh'}}},callWS:async request=>{
      window.historyRequests.push(request);
      return {'sensor.energy':[{s:'10',a:{unit_of_measurement:'kWh'},lu:(now-601000)/1000},{s:'10.2',a:{unit_of_measurement:'kWh'},lu:(now-1000)/1000}]};
    }};
    c.setConfig({entities:{compressor_energy:'sensor.energy'}});
  });
  await card.getByText('Compressor · 10 min energy average').waitFor();
  assert.match(await card.locator('.heat-summary').textContent(),/P avg ≈ 1.2 kW/);
  assert.equal(await page.evaluate(()=>window.historyRequests.at(-1).type),'history/history_during_period');
  const requestCount=await page.evaluate(()=>window.historyRequests.length);
  await card.evaluate(c=>c.hass=c._hass);
  assert.equal(await page.evaluate(()=>window.historyRequests.length),requestCount);
  assert.deepEqual(errors,[]);
  console.log('PASS: diagrams, services, bounds, cancellation, errors, mobile layout, renamed entity discovery, disabled/unrelated filtering, device selection and discovery errors.');
} finally { await browser.close(); }
