"""Configured fallback targets and native command-window integration."""
import unittest
from integration_test import Fixture, Store, runtime, engine


class Predictor:
    def __init__(self, options=None):
        self.options=options or {}
        self.seen=[]
    async def async_update(self,states,now):
        self.seen.append((now,self.command_not_before))
        return {'status':'Waiting for forecast','message':'Weather forecast missing','steps':[],'generated_at':now}


class RuntimeQualityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Store.saved=None;Store.other={}
        self.hass=Fixture()

    async def test_fallback_uses_configured_preference_and_reports_its_bounds(self):
        predictor=Predictor({'room_min_c':18.,'room_target_c':21.,'room_max_c':22.})
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=predictor)
        await controller.async_start()
        self.assertEqual(controller.targets,[21,21])
        self.assertEqual(controller.control['room_min_c'],18)
        self.assertEqual(controller.control['room_target_c'],21)
        self.assertEqual(controller.control['room_max_c'],22)
        self.assertEqual(controller.control['reason'],'Weather forecast missing')
        self.assertEqual(controller.control['mode'],'Thermostat fallback')
        # A configured minimum is not misrepresented as the fallback thermostat target.
        c1=next(data for _,_,_,data in self.hass.calls if data['entity_id']==engine.C1)
        self.assertEqual(c1['value'],1)
        await controller.async_stop()

    async def test_no_op_cycle_does_not_block_a_new_necessary_command(self):
        self.hass.states.values.update({engine.ROOM1:'20',engine.ROOM2:'20',engine.DHW:'Normal'})
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=Predictor())
        await controller.async_start()
        self.assertEqual(self.hass.calls,[])
        self.assertEqual(controller.data['last_cycle'],0)
        self.hass.time+=60
        self.hass.states.values[engine.ROOM1]='19'
        await controller.async_tick()
        self.assertTrue(any(data['entity_id']==engine.C1 for _,_,_,data in self.hass.calls))
        await controller.async_stop()

    async def test_existing_persisted_gate_is_supplied_to_planner_and_honoured(self):
        old=self.hass.time-100
        Store.saved={'enabled':True,'last_cycle':old,'last_attempt':old+2,'release_dhw':False,'dhw_morning_pending':False}
        predictor=Predictor()
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=predictor)
        await controller.async_start()
        self.assertEqual(predictor.seen[-1][1],old+904)
        self.assertEqual(controller.control['command_not_before'],old+904)
        self.assertEqual(self.hass.calls,[])
        self.assertTrue(controller.control['pending_writes'])
        self.hass.time=old+904
        await controller.async_tick()
        self.assertTrue(self.hass.calls)
        self.assertGreaterEqual(min(t for t,*_ in self.hass.calls),old+904)
        for t,*_ in self.hass.calls:
            self.assertLessEqual(sum(t<=c[0]<t+900 for c in self.hass.calls),3)
        await controller.async_stop()

    async def test_joint_hold_prevents_c2_only_write_stealing_next_action(self):
        base=self.hass.time
        self.hass.time=base+960
        self.hass.states.values.update({engine.ROOM1:'20',engine.ROOM2:'19.1',
            'sensor.vp_degree_minutes_2':'-120','sensor.vp_hot_water_top_bt7':'49',
            'sensor.vp_hot_water_charging_bt6':'49'})
        Store.saved={'enabled':True,'last_cycle':base,'last_attempt':base,
                     'release_dhw':False,'dhw_morning_pending':False}
        class Held(Predictor):
            async def async_update(self,states,now):
                from _nibe_test.predictive import DEFAULTS
                return {'generated_at':base+900,'model':DEFAULTS,'planner':'joint',
                    'steps':[{'start':base+900,'end':base+1800,'offset':6,'dhw_mode':'Normal',
                              'action':'dhw','room':20,'water':49,'hz':42,'inline_kw':0}],
                    'commands':[{'start':base+900,'end':base+964,'offset':0,'dhw_mode':'Economy',
                                 'action':'heat','locked':True},
                                {'start':base+964,'end':base+1924,'offset':6,'dhw_mode':'Normal',
                                 'action':'dhw','locked':False}]}
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=Held())
        await controller.async_start()
        self.assertEqual(self.hass.calls,[])
        self.assertEqual(controller.data['last_cycle'],base)
        self.assertEqual(controller.control['command_not_before'],base+964)
        self.hass.time=base+1020
        await controller.async_tick()
        requested={data['entity_id']:data for _,_,_,data in self.hass.calls}
        self.assertEqual(requested[engine.C1]['value'],6)
        self.assertEqual(requested[engine.DHW]['option'],'Normal')
        self.assertLessEqual(len(self.hass.calls),3)
        await controller.async_stop()

    async def test_morning_completion_survives_draw_off_and_reload(self):
        from datetime import datetime
        from _nibe_test.predictive import DEFAULTS
        def at(text):return datetime.fromisoformat(text).timestamp()
        self.hass.time=at('2026-11-04T06:00:00+01:00')
        self.hass.states.values.update({engine.ROOM1:'20',engine.ROOM2:'20',
            'sensor.vp_degree_minutes_2':'-120','sensor.vp_hot_water_top_bt7':'52',
            'sensor.vp_hot_water_charging_bt6':'52'})
        class Morning(Predictor):
            async def async_update(self,states,now):
                self.completed=self.adaptive_model['dhw_morning_completed']
                return {'generated_at':now,'model':{**DEFAULTS,'timezone':'Europe/Stockholm'},
                    'steps':[{'start':now,'end':now+900,'offset':0,'dhw_mode':'Economy',
                              'action':'off','room':20,'water':49,'hz':0,'inline_kw':0}]}
        predictor=Morning()
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=predictor)
        await controller.async_start()
        self.assertEqual(controller.data['dhw_morning_completed_date'],'2026-11-04')
        self.assertTrue(predictor.completed)
        await controller.async_stop()
        self.hass.time=at('2026-11-04T07:00:00+01:00')
        for e in ('sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6'):
            self.hass.states.values[e]='49'
        predictor=Morning()
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=predictor)
        await controller.async_start()
        self.assertTrue(predictor.completed)
        self.assertEqual(controller.control['dhw'],'Economy')
        # A completed morning goal never disables ordinary low-reserve protection.
        for e in ('sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6'):
            self.hass.states.values[e]='42'
        self.hass.time+=60
        await controller.async_tick()
        self.assertEqual(controller.control['dhw'],'Normal')
        await controller.async_stop()
        self.hass.time=at('2026-11-05T05:00:00+01:00')
        predictor=Morning()
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=predictor)
        await controller.async_start()
        self.assertFalse(predictor.completed)
        await controller.async_stop()

    async def test_paused_controller_does_not_complete_morning_ledger(self):
        from datetime import datetime
        self.hass.time=datetime.fromisoformat('2026-11-04T06:15:00+01:00').timestamp()
        self.hass.states.values.update({'sensor.vp_hot_water_top_bt7':'52',
                                       'sensor.vp_hot_water_charging_bt6':'52'})
        Store.saved={'enabled':False,'release_dhw':False,'last_cycle':0,'last_attempt':0}
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=Predictor())
        await controller.async_start()
        self.assertIsNone(controller.data['dhw_morning_completed_date'])
        await controller.async_stop()

    async def test_slow_source_uses_actual_time_for_write_gate(self):
        old=self.hass.time-880
        Store.saved={'enabled':True,'last_cycle':old,'last_attempt':old,'release_dhw':False,'dhw_morning_pending':False}
        parent=self
        class Slow(Predictor):
            async def async_update(self,states,now):
                self.seen.append((now,self.command_not_before))
                parent.hass.time+=25
                return {'steps':[],'message':'Weather forecast missing','generated_at':now}
        predictor=Slow()
        controller=runtime.Controller(self.hass,clock=lambda:self.hass.time,predictor=predictor)
        await controller.async_start()
        self.assertTrue(self.hass.calls)
        self.assertEqual(predictor.seen[-1][1],old+902)
        self.assertGreaterEqual(self.hass.calls[0][0],old+902)
        await controller.async_stop()


if __name__=='__main__':unittest.main()
