"""Coast release, secondary saturation and persistent primary commitment."""
import unittest
from datetime import datetime,timezone
from integration_test import load,engine,Fixture,Store,runtime
from runtime_quality_test import Predictor
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL
c=load('coordination')

# Rounded readings from the cold-downstairs incident. The running compressor
# sample represents the restart at 73 Hz, after the earlier stopped sample.
CAPACITY_RESPONSE = {'windows': 417, 'theta': [.444, .342, .077, 1.377], 'offset_gain': 1.467}


def cold_secondary_states():
    s = readings(room=19.1, tank=49)
    values = {
        engine.ROOM1: 19.38, engine.ROOM2: 18.87, engine.C1: 10, engine.C2: 0,
        engine.SUPPLY: 27.2, engine.REQUIRED: 50.1,
        engine.C2_SUPPLY: 27.4, engine.C2_REQUIRED: 33.6,
        'sensor.vp_degree_minutes_2': -759,
        'sensor.vp_current_compressor_frequency': 73,
        'sensor.vp_max_compressor_frequency': 75,
    }
    from types import SimpleNamespace
    for entity, value in values.items():
        if entity in s:
            s[entity].state = str(value)
        else:
            s[entity] = SimpleNamespace(state=str(value), attributes={}, last_reported=s[engine.C1].last_reported)
    s[engine.C2].attributes.update(min=-10, max=10, step=1)
    return s


class CoordinationTests(unittest.TestCase):
    def test_cold_secondary_uses_sustainable_primary_target_in_plan_and_dispatch(self):
        s = cold_secondary_states()
        options = {**MODEL, 'room_min_c': 19.}
        model = {**options, 'frequency_reference_hz': 75., 'dhw_morning_completed': True}
        slots = timeline(count=4, outdoor=0.)
        plan = joint._search(slots, s, NOW, model, CAPACITY_RESPONSE, max_hz=75.,
                             command_not_before=NOW+120, strategy='flex')
        balance = plan['planning']['capacity_balance']
        plateau_supply = float(s[engine.C2_SUPPLY].state) + 1.
        self.assertTrue(plateau_supply < balance['target_c'] < 33.)
        self.assertEqual(plan['commands'][0]['offset'], 10.)
        self.assertTrue(plan['commands'][0]['locked'])
        self.assertEqual(plan['commands'][1]['offset'], balance['offset'])
        self.assertTrue(plan['commands'][1]['capacity_balance'])
        # Check the actual native model, including the margin for rising supply.
        native = load('native')
        dm_after = native.primary_degree_minutes_step(-759, plateau_supply, balance['target_c'], 16/60)
        self.assertLess(dm_after, -759)
        self.assertEqual(native.response_step(4.2, balance['target_c']-plateau_supply, -759,
                                              16/60, CAPACITY_RESPONSE['theta'], 4.2), 4.2)
        for control in (None, {'target_c': 20., 'offset_c1': -10., 'dhw': 'Economy'}):
            result = engine.calculate(s, NOW, 12, control=control, options=options, response=CAPACITY_RESPONSE)
            self.assertEqual(dict(result['writes'])[engine.C1], balance['offset'])
            self.assertNotIn(engine.C2, dict(result['writes']))

    def test_primary_easing_requires_real_saturation_and_primary_comfort_headroom(self):
        for entity, value in ((engine.ROOM1, '19.10'), (engine.ROOM2, '19.15'),
                              ('sensor.vp_current_compressor_frequency', '0'),
                              ('sensor.vp_current_compressor_frequency', '30'),
                              ('sensor.vp_degree_minutes_2', '-100'),
                              ('sensor.vp_power_internal_add_heat', '1'),
                              (engine.C2_SUPPLY, 'unknown'),
                              (engine.C2_SUPPLY, '23'),
                              (engine.C2_REQUIRED, '26'),
                              (engine.PRIORITY, 'Hot water')):
            with self.subTest(entity=entity, value=value):
                s = cold_secondary_states()
                s[entity].state = value
                self.assertIsNone(engine.capacity_balance(s, NOW, 19., 20.5, CAPACITY_RESPONSE, 4.2))

    def test_dispatch_rechecks_saturation_for_a_planned_trim(self):
        s = cold_secondary_states()
        s[engine.ROOM2].state = '19.01'
        control = {'target_c': 20., 'offset_c1': -3., 'dhw': 'Economy', 'confirm_capacity_balance': True}
        result = engine.calculate(s, NOW, 12, control=control, options={'room_min_c': 19.},
                                  response=CAPACITY_RESPONSE)
        self.assertNotIn(engine.C1, dict(result['writes']))
        self.assertEqual(result['offset_c1'], 10.)

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
    async def test_fallback_balances_at_the_next_permitted_write(self):
        h = Fixture()
        h.time = NOW
        h.states.values.update({e: state.state for e, state in cold_secondary_states().items()})
        Store.saved = {'last_cycle': NOW-100, 'last_attempt': NOW-100}
        Store.other = {}
        controller = runtime.Controller(h, clock=lambda: h.time)
        fit = controller.offset_learner
        fit.gain = CAPACITY_RESPONSE['offset_gain']
        fit.bank['theta'] = CAPACITY_RESPONSE['theta'][:]
        fit.count = CAPACITY_RESPONSE['windows']
        await controller.async_start()
        self.assertEqual(h.calls, [])
        h.time += 903
        await controller.async_tick()
        self.assertEqual([row[3]['entity_id'] for row in h.calls if row[1] == 'number'], [engine.C1])
        self.assertEqual(h.calls[0][3]['value'], controller.control['capacity_balance']['offset'])
        self.assertLess(controller.control['capacity_balance']['target_c'], 33.)
        await controller.async_stop()

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
