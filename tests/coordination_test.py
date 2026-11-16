"""Coast release, secondary saturation and persistent primary commitment."""
import unittest
from datetime import datetime,timezone
from integration_test import load,engine,Fixture,Store,runtime
from runtime_quality_test import Predictor
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL
c=load('coordination')

class CoordinationTests(unittest.TestCase):
    def test_large_initial_move_and_emergency_but_no_quarter_hour_reversal(self):
        self.assertEqual(c.committed_offset(10,-5,0,0,100),10)
        self.assertEqual(c.committed_offset(-5,10,1,100,1060),10)
        self.assertEqual(c.committed_offset(-5,10,1,100,2980),-5)
        self.assertEqual(c.committed_offset(-5,10,1,100,1060,True),-5)

    def test_minimum_power_does_not_receive_full_distribution_credit(self):
        response={'heating_rate':-.046,'coasting_rate':.025,'heating_kw':4.}
        self.assertAlmostEqual(c.differential_rate(response,0,4),.025)
        self.assertAlmostEqual(c.differential_rate(response,4,4),-.046)
        self.assertGreater(c.differential_rate(response,1,4),0.)

    def test_secondary_cannot_wind_up_against_insufficient_primary_supply(self):
        h=Fixture();h.states.values.update({engine.C1:'-9',engine.C2:'9',engine.SUPPLY:'25',engine.REQUIRED:'20',engine.ROOM1:'19.5',engine.ROOM2:'19.0','sensor.vp_calculated_supply_climate_system_2':'45'})
        s={v.entity_id:v for v in h.states.async_all()}
        r=engine.calculate(s,h.time,12,control={'target_c':20,'offset_c1':-9,'dhw':'Economy'})
        self.assertNotIn(engine.C2,dict(r['writes']))
        # Once heat is available, the same room error can request more mixing.
        s[engine.SUPPLY].state='48'
        self.assertEqual(dict(engine.calculate(s,h.time,12)['writes'])[engine.C2],10)

    def test_missing_room_releases_negative_coast_without_guessing_room_temperature(self):
        h=Fixture();h.states.values.update({engine.C1:'-10',engine.ROOM2:'unavailable'})
        s={v.entity_id:v for v in h.states.async_all()};r=engine.calculate(s,h.time,12)
        self.assertEqual(dict(r['writes'])[engine.C1],0)
        self.assertEqual(r['targets'],[])
        self.assertNotIn(engine.C2,dict(r['writes']))
        # Invalid/stale actuator state cannot authorise a guessed setting write.
        s[engine.C1].last_reported=datetime.fromtimestamp(h.time-1900,timezone.utc)
        self.assertNotIn(engine.C1,dict(engine.calculate(s,h.time,12)['writes']))

    def test_both_rooms_drive_primary_fallback_demand(self):
        h=Fixture();h.states.values.update({engine.C1:'-10',engine.ROOM1:'20',engine.ROOM2:'18.2'})
        r=engine.calculate({v.entity_id:v for v in h.states.async_all()},h.time,12)
        self.assertGreaterEqual(dict(r['writes'])[engine.C1],0)

    def test_fallback_does_not_heat_through_an_upper_comfort_breach(self):
        h=Fixture();h.states.values.update({engine.C1:'0',engine.ROOM1:'22',engine.ROOM2:'18.2'})
        r=engine.calculate({v.entity_id:v for v in h.states.async_all()},h.time,12,options={'room_max_c':21})
        self.assertEqual(dict(r['writes'])[engine.C1],-1)

    def test_planner_honours_persisted_direction_on_its_command_timeline(self):
        s=readings(room=20,tank=52);s[engine.C1].state='6'
        commands=[{'start':NOW,'end':NOW+3600,'offset':-6,'dhw_mode':'Economy'}]
        r=joint._search(timeline(count=4),s,NOW,{**MODEL,'c1_direction':1,'c1_changed':NOW-600},strategy='previous',incumbent={'commands':commands})
        self.assertTrue(all(v['offset']==6 for v in r['commands'] if v['start']<NOW+2280))

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_uses_existing_cloud_gate_and_survives_restart(self):
        Store.saved=None;Store.other={};h=Fixture()
        h.states.values.update({engine.C1:'-10',engine.ROOM2:'unavailable'})
        controller=runtime.Controller(h,clock=lambda:h.time,predictor=Predictor())
        await controller.async_start()
        self.assertEqual(next(d['value'] for _,_,_,d in h.calls if d['entity_id']==engine.C1),0)
        self.assertEqual(controller.data['c1_direction'],1)
        first=len(h.calls);await controller.async_stop()
        restored=runtime.Controller(h,clock=lambda:h.time,predictor=Predictor())
        await restored.async_start()
        self.assertEqual(restored.data['c1_direction'],1)
        self.assertEqual(len(h.calls),first)
        await restored.async_stop()

if __name__=='__main__':unittest.main()
