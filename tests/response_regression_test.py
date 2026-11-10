"""Room divergence, restart memory and native start timing from the peak trace."""
import copy, math, unittest
from adaptive_test import states_at, BASE
from integration_test import load, engine
from offset_test import states as native_states
from joint_peak_test import scenario

adaptive=load('adaptive');offset=load('offset');joint=load('joint')

class ResponseTests(unittest.TestCase):
    def test_opposite_room_errors_are_learned_even_when_average_is_exact(self):
        learner=adaptive.ThermalLearner()
        for minute in range(61):
            t=BASE+minute*60;s=states_at(t,q=0,mode='Off')
            s[engine.ROOM1].state=str(19.74-.25*minute/60)
            s[engine.ROOM2].state=str(20.27-.03*minute/60)
            learner.update(s,t,12)
        response=learner.parameters()['room_response']
        self.assertAlmostEqual(response['coasting_rate'],-.11,places=5)
        restored=adaptive.ThermalLearner();self.assertTrue(restored.restore(copy.deepcopy(learner.dump())))
        self.assertEqual(restored.room_response,response)
        self.assertEqual(response['heating_rate'],0.)

    def test_short_restart_keeps_delayed_heat_without_training_across_gap(self):
        learner=adaptive.ThermalLearner();learner.heat_timestamp=BASE
        for bank in learner.banks:bank['heat']=2.
        restored=adaptive.ThermalLearner();self.assertTrue(restored.restore(copy.deepcopy(learner.dump())))
        restored.update(states_at(BASE+600,q=0,mode='Off'),BASE+600,12)
        self.assertAlmostEqual(restored.banks[-1]['heat'],2*math.exp(-(1/6)/4))
        self.assertEqual(restored.count,0);self.assertIsNone(restored.window)
        restored.update(states_at(BASE+8*3600,q=0,mode='Off'),BASE+8*3600,20)
        self.assertEqual(restored.banks[-1]['heat'],0.)

    def test_legacy_biased_threshold_is_replaced_by_clean_start_bracket(self):
        old=offset.OffsetLearner().dump();old.pop('start_samples');old['start_dm']=-255
        learner=offset.OffsetLearner();self.assertTrue(learner.restore(old))
        self.assertEqual(learner.start_dm,-60.)
        a=native_states(BASE,dm=-49,q=0);a[engine.PRIORITY].state='Off'
        learner.update(a,BASE,4.2)
        learner.update(native_states(BASE+60,dm=-64,q=2),BASE+60,4.2)
        self.assertAlmostEqual(learner.start_dm,-56.5)
        self.assertEqual(learner.start_source,'Bracketed starts')
        # A late cloud report with a huge degree-minute jump is not a bracket.
        learner.update(native_states(BASE+120,dm=-20,q=0),BASE+120,4.2)
        learner.update(native_states(BASE+180,dm=-900,q=2),BASE+180,4.2)
        self.assertAlmostEqual(learner.start_dm,-56.5)

    def test_native_setting_takes_priority_over_empirical_starts(self):
        from types import SimpleNamespace
        learner=offset.OffsetLearner();a=native_states()
        a['number.vp_start_compressor']=SimpleNamespace(state='-80',attributes={},last_reported=a[engine.C1].last_reported)
        learner.update(a,BASE,4.2)
        self.assertEqual(learner.parameters()['start_dm'],-80)
        self.assertEqual(learner.parameters()['start_source'],'Native setting')

    def test_dhw_transition_does_not_identify_space_heating_start(self):
        learner=offset.OffsetLearner();a=native_states(q=0,dm=-150)
        a[engine.PRIORITY].state='Hot water';learner.update(a,BASE,4.2)
        learner.update(native_states(BASE+60,dm=-200,q=2),BASE+60,4.2)
        self.assertEqual(learner.start_samples,[])

    def test_differential_prediction_is_bounded_and_conserves_average(self):
        slots,states,model,response,emitter=scenario()
        model['room_response']={'coasting_rate':-.11,'heating_rate':-.02}
        r=joint.plan(slots,states,slots[0]['start'],model,response,max_hz=89,emitter=emitter)
        self.assertTrue(any(abs((s['room2']-s['room1'])-.83)>.05 for s in r['steps']))
        self.assertTrue(all(abs((s['room1']+s['room2'])/2-s['room'])<1e-8 for s in r['steps']))
        self.assertTrue(all(abs(s['room2']-s['room1'])<=2.04 for s in r['steps']))
        self.assertLessEqual(r['constraint_violation_score'],1e-8)
        again=joint.plan(slots,states,slots[0]['start'],model,response,max_hz=89,emitter=emitter,incumbent={**r,'generated_at':slots[0]['start']})
        self.assertIn('price-aware previous',[c['strategy'] for c in again['planning']['candidate_costs']])

if __name__=='__main__':unittest.main()
