"""Configured comfort is protected; in-band preferences cannot override price."""
import copy, unittest
from joint_peak_test import scenario
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL
from offset_test import states as native_states
from integration_test import load,engine
from adaptive_test import BASE

class EconomicTests(unittest.TestCase):
    def test_feasible_cheaper_plan_wins_despite_large_preference_penalty(self):
        def result(cost,penalty,violation=0,morning=0):
            return {'constraint_violation_score':violation,'morning_shortfall':morning,
                    'selection_score':[violation,cost],'inline_kwh':0,
                    'objective_components':{'control_penalties':penalty}}
        cheap=result(60,1000);warm=result(70,0)
        self.assertIs(min([warm,cheap],key=joint.selection_key),cheap)
        self.assertIs(min([cheap,result(40,0,violation=.1)],key=joint.selection_key),cheap)
        self.assertIs(min([cheap,result(40,0,morning=1)],key=joint.selection_key),cheap)

    def test_live_tiny_buffer_difference_cannot_override_electricity_savings(self):
        def result(cost,risk,violation=0):
            return {'constraint_violation_score':violation,'morning_shortfall':0,
                    'selection_score':[violation,cost],'comfort_risk':risk,
                    'inline_kwh':0,'objective_components':{'control_penalties':0}}
        expensive=result(27.3324,.00091595)
        cheap=result(21.9404,.00117743)
        self.assertIs(min([expensive,cheap],key=joint.selection_key),cheap)
        self.assertIs(min([cheap,result(1,0,.001)],key=joint.selection_key),cheap)
        # A substantial uncertainty exposure still has an economic consequence.
        self.assertIs(min([expensive,result(21.94,.2)],key=joint.selection_key),expensive)

    def test_actual_delayed_response_case_selects_least_economic_score_when_feasible(self):
        slots,states,model,response,emitter=scenario()
        result=joint.plan(slots,states,NOW,model,response,max_hz=89,emitter=emitter)
        feasible=[c for c in result['planning']['candidate_costs'] if c['violation']==0 and c['morning_shortfall']==0]
        self.assertEqual(joint.selection_key(result)[2],min(c['ranked_objective'] for c in feasible))
        self.assertTrue(any(c['strategy'].startswith('coast-patch') for c in result['planning']['candidate_costs']))
        self.assertAlmostEqual(result['selection_score'][1],result['model_cost']+result['objective_components']['terminal_reserve'])
        self.assertGreaterEqual(min(s['room1'] for s in result['steps']),model['room_min_c'])

    def test_part_load_calibration_requires_continuous_stable_space_heating(self):
        offset=load('offset');learner=offset.OffsetLearner()
        learner.emitter={'conductance_kw_per_k':.17,'observations':100,'time':BASE-60}
        for minute in range(16):
            s=native_states(BASE+minute*60,q=1,dm=-100,offset=0)
            s[engine.SUPPLY].state='45';s[engine.REQUIRED].state='45'
            learner.update(s,BASE+minute*60,4.2)
        self.assertLess(learner.emitter['conductance_kw_per_k'],.06)
        self.assertEqual(learner.emitter['steady_observations'],1)
        saved=copy.deepcopy(learner.emitter)
        # A repeated cloud snapshot cannot generate another calibration.
        learner.update(s,BASE+16*60,4.2)
        self.assertEqual(learner.emitter,saved)
        s=native_states(BASE+17*60,q=2,dm=-100);s[engine.PRIORITY].state='Hot water'
        learner.update(s,BASE+17*60,4.2)
        self.assertEqual(learner.steady,[])
        self.assertEqual(learner.emitter,saved)

    def test_missing_room_sample_resets_part_load_calibration(self):
        offset=load('offset');learner=offset.OffsetLearner()
        for minute in range(21):
            s=native_states(BASE+minute*60,q=1,dm=-100)
            s[engine.SUPPLY].state='45';s[engine.REQUIRED].state='45'
            if minute==10:s[engine.ROOM1].state='unavailable'
            learner.update(s,BASE+minute*60,4.2)
        self.assertEqual(learner.emitter.get('steady_observations',0),0)

    def test_variable_supply_does_not_identify_a_false_steady_emitter(self):
        offset=load('offset');learner=offset.OffsetLearner()
        for minute in range(16):
            s=native_states(BASE+minute*60,q=1,dm=-100)
            s[engine.SUPPLY].state=str(30+minute*.5)
            learner.update(s,BASE+minute*60,4.2)
        self.assertEqual(learner.emitter.get('steady_observations',0),0)

if __name__=='__main__':unittest.main()
