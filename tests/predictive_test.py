"""Forecast parsing, thermal model and background source integration checks."""
from datetime import datetime, timezone, timedelta
import unittest
import sys
from types import ModuleType
from unittest.mock import patch
from types import SimpleNamespace
from integration_test import load, Fixture, engine

p=load('predictive')
f=load('forecast')
BASE=1800000000.
def iso(t):
    return datetime.fromtimestamp(t,timezone.utc).isoformat()
def rows(hours=24):
    return [{'start':iso(BASE+i*3600),'end':iso(BASE+(i+1)*3600),'value':.3 if i<5 else 2.5 if i<10 else 1.} for i in range(hours)]
def weather(hours=26):
    return [{'datetime':iso(BASE-3600+i*3600),'temperature':0} for i in range(hours)]

class ModelTests(unittest.TestCase):
    def test_units_negative_prices_and_dst(self):
        r=[{'start':'2026-10-25T02:00:00+02:00','end':'2026-10-25T02:00:00+01:00','price':-200}]
        result=p.prices(r,'SEK/MWh')
        self.assertEqual(result[0]['price'],-.2)
        self.assertEqual(result[0]['end']-result[0]['start'],3600)
        self.assertRaises(ValueError,p.prices,r,'SEK')
        self.assertRaises(ValueError,p.prices,[{**r[0],'price':None}],'SEK/MWh')
        self.assertRaises(ValueError,p.timestamp,'2026-10-25T02:00:00')

    def test_gaps_truncate_continuous_horizon(self):
        market=p.prices(rows(),'SEK/kWh')
        self.assertEqual(len(p.timeline(market,weather(),BASE)),96)
        self.assertEqual(len(p.timeline(market[1:],weather(),BASE)),0)
        self.assertRaises(ValueError,p.prices,rows()+rows(),'SEK/kWh')
        self.assertEqual(p.plan(p.timeline(market[:3],weather(),BASE),20,49)['steps'],[])

    def test_model_finds_schedule_and_preserves_end_reserve(self):
        slots=p.timeline(p.prices(rows(),'SEK/kWh'),weather(),BASE)
        result=p.plan(slots,20.1,49)
        self.assertEqual(result['status'],'Recommendation available')
        self.assertTrue(result['compressor_only'])
        self.assertEqual(result['inline_kwh'],0)
        self.assertGreaterEqual(result['steps'][-1]['room'],20)
        self.assertGreaterEqual(result['steps'][-1]['water'],48)
        self.assertTrue(all(19<=s['room']<=20.5 and 42<=s['water']<=55 for s in result['steps']))
        self.assertTrue(all(s['hz'] in (0,42,84) for s in result['steps']))

    def test_warmer_weather_reduces_demand_and_price_shape_changes_plan(self):
        market=p.prices(rows(),'SEK/kWh')
        cold=p.plan(p.timeline(market,weather(),BASE),20.1,49)
        warm=p.plan(p.timeline(market,[{**w,'temperature':8} for w in weather()],BASE),20.1,49)
        energy=lambda r:sum((s['compressor_kw']+s['inline_kw'])*s['dt'] for s in r['steps'])
        self.assertLess(energy(warm),energy(cold))
        changed=p.plan(p.timeline([{**r,'price':3-r['price']} for r in market],weather(),BASE),20.1,49)
        self.assertNotEqual([s['action'] for s in cold['steps']],[s['action'] for s in changed['steps']])

    def test_infeasible_limits_are_explicit(self):
        slots=p.timeline(p.prices(rows(),'SEK/kWh'),[{**w,'temperature':-50} for w in weather()],BASE)
        result=p.plan(slots,19.1,43,model={'compressor_heat_kw':1,'dhw_heat_kw':1})
        self.assertEqual(result['status'],'Model cannot meet targets')
        self.assertEqual(result['steps'],[])

class SourceTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        fixture=Fixture()
        fixture.time=BASE
        states={s.entity_id:s for s in fixture.states.async_all()}
        def state(id,value,attrs):
            return SimpleNamespace(entity_id=id,state=str(value),attributes=attrs,last_reported=datetime.fromtimestamp(BASE,timezone.utc))
        states.update({engine.PRICE:state(engine.PRICE,.3,{'unit_of_measurement':'SEK/kWh','raw_today':rows(),'tomorrow_valid':False}),
            'weather.home':state('weather.home','cloudy',{'temperature_unit':'°C','temperature':0}),
            'sensor.vp_hot_water_top_bt7':state('sensor.vp_hot_water_top_bt7',49,{}),
            'sensor.vp_hot_water_charging_bt6':state('sensor.vp_hot_water_charging_bt6',49,{}),
            'sensor.vp_max_compressor_frequency':state('sensor.vp_max_compressor_frequency',84,{})})
        calls=[]
        async def call(domain,service,data,**kwargs):
            calls.append((domain,service))
            if domain!='weather':
                raise AssertionError('Unexpected service')
            return {'weather.home':{'forecast':weather()}}
        async def executor(callback):
            return callback()
        hass=SimpleNamespace(services=SimpleNamespace(async_call=call),async_add_executor_job=executor)
        return hass,states,calls

    async def test_custom_nordpool_and_weather_are_read_only_and_throttled(self):
        hass,states,calls=self.make()
        predictor=f.Predictor(hass,{'weather_entity':'weather.home'})
        result=await predictor.async_update(states,BASE)
        self.assertEqual(result['status'],'Recommendation available')
        self.assertTrue(result['tomorrow_unavailable'])
        self.assertEqual(calls,[('weather','get_forecasts')])
        await predictor.async_update(states,BASE+60)
        self.assertEqual(len(calls),1)
        async def fail(*args,**kwargs):
            raise RuntimeError('Weather connection lost')
        hass.services.async_call=fail
        result=await predictor.async_update(states,BASE+901)
        self.assertEqual(result['steps'],[])
        self.assertEqual(result['message'],'Weather connection lost')

    async def test_official_nordpool_converts_mwh_once_and_handles_unpublished_tomorrow(self):
        hass,states,calls=self.make()
        states[engine.PRICE].attributes={}
        registry=SimpleNamespace(async_get=lambda id:SimpleNamespace(config_entry_id='pool'))
        er=ModuleType('homeassistant.helpers.entity_registry')
        er.async_get=lambda hass:registry
        count=0
        async def call(domain,service,data,**kwargs):
            nonlocal count
            calls.append((domain,service))
            if domain=='weather':
                return {'weather.home':{'forecast':weather()}}
            count+=1
            if count>1:
                raise RuntimeError('Tomorrow unpublished')
            return {'SE3':[{'start':r['start'],'end':r['end'],'price':r['value']*1000} for r in rows()]}
        hass.services.async_call=call
        with patch.dict(sys.modules,{'homeassistant.helpers.entity_registry':er}), patch('homeassistant.util.dt.now',return_value=datetime.fromtimestamp(BASE,timezone.utc)):
            result=await f.Predictor(hass,{'weather_entity':'weather.home'}).async_update(states,BASE)
        self.assertEqual(result['status'],'Recommendation available')
        self.assertEqual(result['steps'][0]['price'],.3)
        self.assertTrue(result['tomorrow_unavailable'])
        self.assertEqual(count,2)

    async def test_missing_current_temperatures_stop_recommendations(self):
        hass,states,calls=self.make()
        states[engine.ROOM1].state='unavailable'
        result=await f.Predictor(hass,{'weather_entity':'weather.home'}).async_update(states,BASE)
        self.assertEqual(result['steps'],[])
        self.assertIn('Fresh room',result['message'])

if __name__=='__main__':
    unittest.main()
