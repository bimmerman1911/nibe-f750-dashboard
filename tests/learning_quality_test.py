"""Learning windows must describe measured, uninterrupted operation."""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from integration_test import load, engine
from adaptive_test import states_at, BASE

adaptive=load('adaptive')

def comfort(states,value):
    states['select.vp_comfort_mode'].state=value
    return states

class QualityTests(unittest.TestCase):
    def test_opposing_room_jumps_do_not_cancel_into_a_valid_window(self):
        learner=adaptive.ThermalLearner()
        for minute in range(30):
            learner.update(states_at(BASE+minute*60),BASE+minute*60,12)
        s=states_at(BASE+1800)
        s[engine.ROOM1].state='21.1'
        s[engine.ROOM2].state='18.9'  # Average remains 20°C.
        self.assertFalse(learner.update(s,BASE+1800,12))
        self.assertEqual(learner.count,0)
        self.assertIsNone(learner.window)
        self.assertGreater(learner.rejected,0)

    def test_fresh_defrost_excludes_samples_but_stale_status_does_not(self):
        learner=adaptive.ThermalLearner()
        s=states_at(BASE)
        s['sensor.vp_status']=SimpleNamespace(state='Defrosting',attributes={},
            last_reported=datetime.fromtimestamp(BASE,timezone.utc))
        self.assertIsNone(learner.observation(s,BASE,12))
        s['sensor.vp_status'].last_reported=datetime.fromtimestamp(BASE-3600,timezone.utc)
        self.assertIsNotNone(learner.observation(s,BASE,12))

    def test_draw_window_ends_at_charge_and_missing_tank(self):
        learner=adaptive.ThermalLearner()
        for minute in range(21):
            t=BASE+minute*60
            learner.update(states_at(t,q=0,tank=49-minute*.02,mode='Off'),t,12)
        self.assertIsNotNone(learner.draw_window)
        t=BASE+21*60
        learner.update(states_at(t,q=2,tank=48.6,mode='Hot water'),t,12)
        self.assertIsNone(learner.draw_window)
        self.assertEqual(learner.draw_counts[12],1)
        learner.draw_window={'hour':12,'hours':.4,'energy':.4}
        s=states_at(t+60,q=0,mode='Off');s[adaptive.TANK[0]].state='unavailable'
        learner.update(s,t+60,12)
        self.assertIsNone(learner.draw_window)
        self.assertEqual(learner.draw_counts[12],1)

    def test_economy_interruption_is_not_a_native_full_charge(self):
        learner=adaptive.ThermalLearner()
        learner.update(states_at(BASE,q=2,tank=49,mode='Hot water'),BASE,12)
        learner.update(comfort(states_at(BASE+60,q=0,tank=49,mode='Off'),'Economy'),BASE+60,12)
        self.assertEqual(learner.tank_ceiling,52)
        self.assertEqual(learner.dhw_stop_observations,0)
        # A native stop while Normal remains selected is a valid observation.
        learner.update(states_at(BASE+120,q=2,tank=49,mode='Hot water'),BASE+120,12)
        learner.update(states_at(BASE+180,q=0,tank=49,mode='Off'),BASE+180,12)
        self.assertEqual(learner.dhw_stop_observations,1)

    def test_intentional_deferral_does_not_teach_a_false_start_temperature(self):
        learner=adaptive.ThermalLearner()
        for minute in range(20):
            t=BASE+minute*60
            learner.update(comfort(states_at(t,q=0,tank=43,mode='Off'),'Economy'),t,12)
        t=BASE+20*60
        learner.update(states_at(t,q=0,tank=43,mode='Off'),t,12)
        learner.update(states_at(t+60,q=2,tank=43,mode='Hot water'),t+60,12)
        self.assertEqual(learner.dhw_start_c,48)
        self.assertEqual(learner.dhw_start_observations,0)

    def test_old_valid_theta_box_cannot_emit_household_impossible_ratios(self):
        original=adaptive.ThermalLearner()
        data=copy.deepcopy(original.dump())
        data['banks'][data['selected']]['theta']=[.15,.01,.4]
        learner=adaptive.ThermalLearner()
        self.assertTrue(learner.restore(data))
        # Existing state is retained, but the planner receives guarded values.
        self.assertEqual(learner.banks,data['banks'])
        model=learner.parameters()
        self.assertEqual(model['heat_loss_kw_per_k'],1.)
        self.assertEqual(model['thermal_capacity_kwh_per_k'],100.)
        self.assertEqual(model['internal_gain_kw'],6.)
        self.assertTrue(model['physical_projection_applied'])
        self.assertGreaterEqual(model['response_uncertainty_c'],.35)
        self.assertFalse(model['heat_response_identified'])
        bank=copy.deepcopy(data['banks'][data['selected']])
        self.assertTrue(learner._fit(bank,[0.,0.,0.],0.))
        a,b,g=bank['theta']
        self.assertTrue(.01<=a/b<=1.)
        self.assertTrue(-3<=g/b<=6.)
        self.assertTrue(2<=1/b<=100.)

    def test_cooling_only_data_does_not_claim_identified_heat_response(self):
        learner=adaptive.ThermalLearner()
        for minute in range(6*60+1):
            t=BASE+minute*60
            learner.update(states_at(t,q=0,room=20-minute*.001,outdoor=5-minute*.005,mode='Off'),t,12)
        quality=learner.quality()
        self.assertGreater(quality['cooling_windows'],0)
        self.assertEqual(quality['heating_windows'],0)
        self.assertEqual(quality['model_confidence'],0)
        self.assertFalse(quality['heat_response_identified'])
        self.assertGreaterEqual(quality['response_uncertainty_c'],.15)
        saved=copy.deepcopy(learner.dump())
        restored=adaptive.ThermalLearner()
        self.assertTrue(restored.restore(saved))
        self.assertEqual(restored.quality(),quality)
        # The previous v1 store remains valid without new confidence counters.
        for key in ('heating_windows','cooling_windows','dhw_start_observations',
                    'dhw_stop_observations','dhw_charge_windows','draw_hours',
                    'last_learning_at','last_heating_at','projection_windows','projection_last_window'):
            saved.pop(key)
        self.assertTrue(adaptive.ThermalLearner().restore(saved))

if __name__=='__main__':unittest.main()
