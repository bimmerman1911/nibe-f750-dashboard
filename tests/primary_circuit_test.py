"""C1 controls production; the secondary ECS target is a mixing-valve target."""
import copy,unittest
from types import SimpleNamespace
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL
from integration_test import load,engine

native=load('native')
SECONDARY_TARGET='sensor.vp_calculated_supply_climate_system_2'


def setup():
    states=readings(room=20.,tank=52.)
    for e,value in ((engine.C1,0),(engine.REQUIRED,20),(engine.SUPPLY,25.7),('sensor.vp_degree_minutes_2',-50)):
        states[e].state=str(value)
    commands=[{'start':NOW,'end':NOW+3600,'offset':0,'dhw_mode':'Economy'}]
    def simulate(states):
        return joint._search(timeline(count=4),states,NOW,MODEL,strategy='previous',incumbent={'commands':commands})
    return states,simulate


class PrimaryCircuitTests(unittest.TestCase):
    def test_primary_supply_above_c1_target_recovers_degree_minutes(self):
        # Same relationship seen in recorded operation: C2 at 45°C does not
        # turn a positive primary supply error into a negative degree-minute rate.
        self.assertAlmostEqual(native.primary_degree_minutes_step(-50,25.7,20,1/60),-44.3)
        self.assertAlmostEqual(native.primary_degree_minutes_step(-50,25.7,30,1/60),-54.3)

    def test_secondary_target_and_offset_do_not_directly_change_native_prediction(self):
        states,simulate=setup();baseline=simulate(states)
        for target,offset in ((45,-10),(10,10),('unavailable',0)):
            changed=copy.deepcopy(states)
            changed[engine.C2]=SimpleNamespace(state=str(offset),attributes={'min':-10,'max':10,'step':1},last_reported=states[engine.C1].last_reported)
            changed[SECONDARY_TARGET]=SimpleNamespace(state=str(target),attributes={'unit_of_measurement':'°C'},last_reported=states[engine.C1].last_reported)
            result=simulate(changed)
            self.assertEqual(result['steps'],baseline['steps'])
            self.assertEqual(result['commands'],baseline['commands'])
        basis=baseline['planning']['actuator_roles']
        self.assertEqual(basis['degree_minutes']['target'],engine.REQUIRED)
        self.assertEqual(basis['degree_minutes']['offset'],engine.C1)
        self.assertEqual(basis['secondary']['offset'],engine.C2)

    def test_c1_target_changes_degree_minutes_with_identical_secondary_target(self):
        states,simulate=setup()
        states[SECONDARY_TARGET]=SimpleNamespace(state='45',attributes={},last_reported=states[engine.C1].last_reported)
        low=simulate(states)
        states[engine.REQUIRED].state='40'
        high=simulate(states)
        self.assertGreater(low['steps'][0]['degree_minutes'],-50)
        self.assertLess(high['steps'][0]['degree_minutes'],-50)

    def test_degree_minutes_during_hot_water_determine_space_heating_restart(self):
        states = readings(room=19.2, tank=49., mode='Hot water')
        states[engine.DHW].state = 'Normal'
        states[engine.SUPPLY].state = '34'
        states['sensor.vp_degree_minutes_2'].state = '-90'
        slots = timeline(count=2, price=lambda _: 2.25)
        commands = [{'start': NOW, 'end': slots[-1]['end'], 'offset': 0., 'dhw_mode': 'Normal'}]

        def simulate(target):
            states[engine.REQUIRED].state = str(target)
            return joint._search(slots, states, NOW, MODEL, strategy='previous',
                                 incumbent={'commands': commands})['steps']

        low_target = simulate(20)
        high_target = simulate(44)
        for steps in (low_target, high_target):
            self.assertTrue(all(piece['action'] == 'dhw' for piece in steps[0]['activity']))
            self.assertGreater(steps[0]['water'], 49.)
        self.assertGreater(low_target[0]['degree_minutes'], 0.)
        self.assertLess(high_target[0]['degree_minutes'], -90.)
        self.assertEqual(low_target[1]['action'], 'off')
        self.assertEqual(high_target[1]['action'], 'heat')

    def test_native_supply_overshoot_stops_heating_even_with_large_degree_minute_deficit(self):
        states = readings(room=19.9, tank=52.)
        states[engine.C1].state = '10'
        states[engine.REQUIRED].state = '50.6'
        states[engine.SUPPLY].state = '51.6'
        states['sensor.vp_degree_minutes_2'].state = '-565'
        slots = timeline(count=1, price=lambda _: 2.45)

        def simulate(offset, model=MODEL):
            commands = [{'start': NOW, 'end': slots[-1]['end'], 'offset': offset, 'dhw_mode': 'Economy'}]
            return joint._search(slots, states, NOW, model, {'offset_gain': 1.5},
                                 strategy='previous', incumbent={'commands': commands})['steps'][0]

        cut = simulate(-10)
        self.assertEqual(cut['action'], 'off')
        self.assertEqual(cut['compressor_kw'], 0.)
        self.assertGreaterEqual(cut['degree_minutes'], 0.)
        trim = simulate(5)
        self.assertEqual(trim['action'], 'heat')
        self.assertLess(trim['degree_minutes'], 0.)
        stricter = simulate(5, {**MODEL, 'compressor_max_supply_diff_c': 7.})
        self.assertEqual(stricter['action'], 'off')

    def test_temporary_warmth_fades_only_in_the_affected_room(self):
        states = readings(room=20., mode='Off', q=0.)
        states[engine.ROOM2].state = '21'
        states[engine.SUPPLY].state = '25'
        slots = timeline(count=16)
        commands = [{'start': NOW, 'end': slots[-1]['end'], 'offset': -10., 'dhw_mode': 'Economy'}]
        result = joint._search(slots, states, NOW, {**MODEL, 'temporary_heat': ((0., 0.), (1., 2.))},
                               strategy='previous', incumbent={'commands': commands})
        first, last = result['steps'][0], result['steps'][-1]
        self.assertEqual(result['initial_room'], 20.5)
        self.assertGreater(first['room2'] - first['room1'], 1.)
        self.assertLess(last['room2'] - last['room1'], .20)
        self.assertAlmostEqual(first['room'], (first['room1'] + first['room2']) / 2)

    def test_fireplace_limits_a_c1_cut_while_the_other_room_is_cold(self):
        states = readings(room=20.)
        for entity, value in ((engine.ROOM1, 19.2), (engine.ROOM2, 21), (engine.C1, 4),
                              (engine.SUPPLY, 41), (engine.REQUIRED, 42), ('sensor.vp_degree_minutes_2', -565)):
            states[entity].state = str(value)
        profile = ((0., 0.), (1.8, 2.))
        model = {**MODEL, 'temporary_heat': profile, 'room_min_c': 19.}
        slots = timeline(count=1)
        commands = [{'start': NOW, 'end': slots[-1]['end'], 'offset': -10., 'dhw_mode': 'Economy'}]
        forecast = joint._search(slots, states, NOW, model, strategy='previous',
                                 incumbent={'commands': commands})
        self.assertEqual(forecast['steps'][0]['action'], 'heat')
        self.assertEqual(forecast['commands'][0]['offset'], 3.)

        control = {'target_c': 20., 'offset_c1': -10., 'dhw': 'Economy', 'room_min_c': 19.}
        result = engine.calculate(states, NOW, 12, control=control, temporary_heat=profile)
        self.assertEqual(dict(result['writes'])[engine.C1], 3.)
        states[engine.ROOM1].state = '20.4'
        result = engine.calculate(states, NOW, 12, control=control, temporary_heat=profile)
        self.assertEqual(dict(result['writes'])[engine.C1], -10.)

    def test_secondary_load_can_indirectly_change_primary_degree_minutes(self):
        # Holding C1's target fixed, a lower actual primary supply still matters.
        self.assertGreater(native.primary_degree_minutes_step(-50,25.7,20,.1),-50)
        self.assertLess(native.primary_degree_minutes_step(-50,18,20,.1),-50)

    def test_transition_preserves_existing_bounds_and_rejects_invalid_inputs(self):
        self.assertEqual(native.primary_degree_minutes_step(-2990,20,40,1),-3000)
        self.assertEqual(native.primary_degree_minutes_step(990,40,20,1),1000)
        for args in ((0,25,20,-1),(0,float('nan'),20,1)):
            with self.assertRaises(ValueError):native.primary_degree_minutes_step(*args)


if __name__=='__main__':unittest.main()
