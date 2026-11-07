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
  assert.equal(await card.locator('svg').count(),2);
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
      {entity_id:'sensor.raw',platform:'myuplink',device_id:'pump',unique_id:'cloud-device-49994-raw'},
    ];
    window.autoRegistry=registry;
    window.autoDevices=[{id:'pump',model:'F750',name:'My heat pump'}];
    window.autoHass={states:{'sensor.renamed_outside':{state:'7',attributes:{unit_of_measurement:'°C'}},'number.renamed_offset':{state:'0',attributes:{min:-10,max:10,step:1}}},callWS:async({type})=>type.includes('entity_registry')?window.autoRegistry:window.autoDevices};
    c.setConfig({type:'custom:nibe-f750-card'});c.hass=window.autoHass;
  });
  await card.getByText(/2 readings discovered|1 readings discovered/).waitFor();
  assert.match(await card.locator('.stats').textContent(),/7/);
  assert.equal(await card.getByRole('spinbutton').count(),1);
  assert.deepEqual(await card.evaluate(c=>Object.keys(c.config.entities)),['outdoor']);
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
  assert.deepEqual(errors,[]);
  console.log('PASS: diagrams, services, bounds, cancellation, errors, mobile layout, renamed entity discovery, disabled/unrelated filtering, device selection and discovery errors.');
} finally { await browser.close(); }
