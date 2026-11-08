"""Scheduled DHW permission, morning reserve and native charging prediction."""
import unittest
from datetime import datetime
from integration_test import load, Store, Fixture, runtime, engine
m=load('dhw');p=load('predictive')

def at(text):return datetime.fromisoformat(text).timestamp()
MODEL={**p.DEFAULTS,'timezone':'Europe/Stockholm','dhw_fraction':.6,'dhw_start_c':48}

class Tests(unittest.TestCase):
    def test_normal_only_current_period_or_reserve(self):
        now=at('2026-11-04T12:00:00+01:00')
        self.assertEqual(m.policy(49,False,False,now,MODEL)['dhw'],'Economy')
        self.assertEqual(m.policy(49,False,True,now,MODEL)['dhw'],'Normal')
        self.assertEqual(m.policy(42,False,False,now,MODEL)['dhw'],'Normal')
        self.assertEqual(m.policy(47,True,False,now,MODEL)['dhw'],'Normal')
        self.assertEqual(m.policy(49,True,False,now,MODEL)['dhw'],'Economy')

    def test_morning_deadline_and_recovery(self):
        now=at('2026-11-04T05:00:00+01:00')
        result=m.policy(44,False,False,now,MODEL)
        self.assertTrue(result['dhw_morning_override'])
        self.assertEqual(result['dhw'],'Normal')
        self.assertEqual(result['dhw_deadline'],at('2026-11-04T06:00:00+01:00'))
        self.assertEqual(m.policy(52,False,False,now,MODEL)['dhw'],'Economy')
        self.assertEqual(m.policy(49,False,False,now+3600,MODEL)['dhw'],'Normal')
        self.assertEqual(m.policy(49,False,False,now+6*3600,{**MODEL,'dhw_morning_pending':True})['dhw'],'Normal')
        self.assertEqual(m.policy(52,False,False,now+6*3600,{**MODEL,'dhw_morning_pending':True})['dhw'],'Economy')
        self.assertEqual(m.next_deadline(now+3600,'Europe/Stockholm'),at('2026-11-05T06:00:00+01:00'))
        self.assertEqual(m.next_deadline(at('2026-03-28T23:00:00+01:00'),'Europe/Stockholm'),at('2026-03-29T06:00:00+02:00'))

    def test_normal_is_permission_not_forced_full_power(self):
        self.assertEqual(m.charge(49,True,False,.25,MODEL),(0,0,0,False))
        q,f,aux,on=m.charge(47,True,False,.25,MODEL)
        self.assertTrue(on);self.assertAlmostEqual(f,.6);self.assertAlmostEqual(q,3.6*.6)
        self.assertEqual(m.charge(47,False,True,.25,MODEL),(0,0,0,False))
        self.assertEqual(m.charge(52,True,True,.25,MODEL),(0,0,0,False))

    def test_schedule_has_morning_target_and_reports_shortfall(self):
        now=at('2026-11-04T00:00:00+01:00')
        slots=[{'start':now+i*900,'end':now+(i+1)*900,'dt':.25,'price':.2 if i<16 else 2,'outdoor':10,'local_hour':i//4,'dhw_deadline':i==23} for i in range(32)]
        result=p.plan(slots,20,44,model={**MODEL,'heat_loss_kw_per_k':.03,'thermal_capacity_kwh_per_k':20})
        self.assertTrue(result['steps'])
        self.assertLess(result['dhw_deadline_shortfall_c'],.5)
        self.assertGreaterEqual(result['steps'][23]['water'],51.)
        self.assertTrue(any(s['dhw_mode']=='Normal' and s['hz']<84 for s in result['steps']))

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_morning_recovery_persists_until_full(self):
        Store.saved=None;Store.other={}
        hass=Fixture();hass.time=at('2026-11-04T05:00:00+01:00')
        hass.states.values.update({engine.ROOM1:'20',engine.ROOM2:'20','sensor.vp_degree_minutes_2':'-120',
            'sensor.vp_hot_water_top_bt7':'44','sensor.vp_hot_water_charging_bt6':'44'})
        class Predictor:
            options={}
            async def async_update(self,states,now):
                return {'generated_at':now,'model':MODEL,'steps':[{'start':now,'end':now+900,
                    'room':20,'water':44,'action':'off','offset':0,'hz':0,'inline_kw':0}]}
        c=runtime.Controller(hass,clock=lambda:hass.time,predictor=Predictor())
        await c.async_start()
        self.assertEqual(c.control['dhw'],'Normal')
        self.assertTrue(Store.saved['dhw_morning_pending'])
        await c.async_stop()
        hass.time+=6*3600
        c=runtime.Controller(hass,clock=lambda:hass.time,predictor=Predictor())
        await c.async_start()
        self.assertTrue(c.data['dhw_morning_pending'])
        self.assertEqual(c.control['dhw'],'Normal')
        for e in ('sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6'):
            hass.states.values[e]='52'
        hass.time+=60
        await c.async_tick()
        self.assertFalse(c.data['dhw_morning_pending'])
        self.assertFalse(Store.saved['dhw_morning_pending'])
        await c.async_stop()

if __name__=='__main__':unittest.main()
