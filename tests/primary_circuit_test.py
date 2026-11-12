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
