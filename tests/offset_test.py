"""Native response learning, degree backlog and direct offset actuation checks."""
import unittest
import copy
from adaptive_test import states_at, BASE, predictive
from integration_test import load, engine
module=load('offset')
supervisor=load('supervisor')

def states(t=BASE,dm=-120,offset=0,q=2.1):
    s=states_at(t,q=q)
    from types import SimpleNamespace
    from datetime import datetime,timezone
    s[module.DM]=SimpleNamespace(state=str(dm),attributes={},last_reported=datetime.fromtimestamp(t,timezone.utc))
    s[engine.C1].state=str(offset)
    s[engine.REQUIRED].state=str(34+2.5*offset)
    return s

def forecast():
    return {'model':{**predictive.DEFAULTS,'heating_lag_hours':1,'initial_heat_kw':2.1,'internal_gain_kw':.3,'auxiliary_limit_kw':3},
            'initial_room':20,'initial_water':49,'generated_at':BASE,
            'steps':[{'start':BASE+i*900,'end':BASE+(i+1)*900,'dt':.25,'price':3 if i<8 else .2,
                      'outdoor':5,'action':'heat','inline_kw':0,'room':20,'water':49} for i in range(24)]}

class Tests(unittest.TestCase):
    def test_degree_backlog_changes_predictions_and_offsets_respect_steps(self):
        a=module.plan_offsets(forecast(),states(dm=-50),BASE,{},20,84)
        b=module.plan_offsets(forecast(),states(dm=-900),BASE,{},20,84)
        self.assertNotEqual([s['compressor_kw'] for s in a['steps']],[s['compressor_kw'] for s in b['steps']])
        for result in (a,b):
            last=0
            for s in result['steps']:
                self.assertLessEqual(abs(s['offset']-last),1)
                self.assertTrue(-10<=s['offset']<=10)
                self.assertTrue(-3000<=s['degree_minutes']<=1000)
                last=s['offset']
        changed=forecast()
        for s in changed['steps']:
            s['price']=.2 if s['start']<BASE+7200 else 3
        c=module.plan_offsets(changed,states(dm=-50),BASE,{},20,84)
        self.assertNotEqual([s['offset'] for s in a['steps']],[s['offset'] for s in c['steps']])

    def test_direct_offset_not_binary_temperature_mapping_and_missing_dm(self):
        f=forecast();f['steps'][0]['offset']=-1
        control=supervisor.request(f,states(),BASE,f['model'])
        self.assertEqual(control['target_c'],20)
        self.assertEqual(dict(engine.calculate(states(),BASE,12,control=control)['writes'])[engine.C1],-1)
        s=states();del s[module.DM]
        self.assertIsNone(module.plan_offsets(f,s,BASE,{},20,84))

    def test_native_start_observations_refine_thresholds(self):
        learner=module.OffsetLearner()
        learner.update(states(q=0,dm=-150),BASE,4.2)
        s=states(BASE+60,q=2,dm=-200)
        learner.update(s,BASE+60,4.2)
        self.assertLess(learner.start_dm,-60)
        s=states(BASE+120,q=2,dm=-900)
        s['sensor.vp_power_internal_add_heat'].state='1'
        learner.update(s,BASE+120,4.2)
        self.assertLess(learner.aux_dm,-700)

    def test_learning_persistence_and_restart_gap(self):
        learner=module.OffsetLearner()
        for minute in range(121):
            learner.update(states(BASE+minute*60,q=1.5+minute/120),BASE+minute*60,4.2)
        self.assertGreater(learner.count,0)
        self.assertNotEqual(learner.bank['theta'],[.35,.25,.75,0])
        restored=module.OffsetLearner()
        self.assertTrue(restored.restore(copy.deepcopy(learner.dump())))
        self.assertEqual(restored.parameters(),learner.parameters())
        count=learner.count
        learner.update(states(BASE+10000),BASE+10000,4.2)
        self.assertEqual(learner.count,count)
        self.assertIsNone(learner.anchor)

if __name__=='__main__':unittest.main()
