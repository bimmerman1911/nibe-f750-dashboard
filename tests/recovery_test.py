"""Near-limit recovery with blocked auxiliary heat and secondary-circuit release."""
import unittest
from integration_test import load, engine
from adaptive_test import states_at, BASE
p=load('predictive')

class Tests(unittest.TestCase):
    def test_cold_start_and_low_tank_get_recovery_without_unblocking_heater(self):
        # Minimal numeric regression from the reported state, not private diagnostics.
        model={**p.DEFAULTS,'heat_loss_kw_per_k':.0981587742,'thermal_capacity_kwh_per_k':9,
            'internal_gain_kw':.20716551,'heating_lag_hours':1,'initial_heat_kw':0,
            'dhw_heat_kw':3.862855,'dhw_fraction':.772908,'dhw_start_c':48,'tank_max_c':51.45,
            'initial_mode':'dhw','auxiliary_limit_kw':0,'dhw_profile':[.15]*24}
        slots=[{'start':BASE+i*900,'end':BASE+(i+1)*900,'dt':.25,'price':2.949,'outdoor':-1.3} for i in range(96)]
        result=p.plan(slots,19.185,41.5,96,model)
        self.assertTrue(result['steps'])
        self.assertTrue(result['recovery_plan'])
        self.assertGreaterEqual(result['steps'][-1]['room'],20)
        self.assertGreaterEqual(result['steps'][-1]['water'],48)
        self.assertEqual(result['inline_kwh'],0)
        self.assertTrue(all(s['room']<=20.5 and s['water']<=51.45+1e-6 for s in result['steps']))

    def test_both_cold_rooms_can_recover_when_supply_is_available(self):
        s=states_at(BASE,room=19.2)
        s[engine.C2].state='-10'
        self.assertIn((engine.C2,-9),engine.calculate(s,BASE,12)['writes'])
        s[engine.C2].state='-9'
        s[engine.SUPPLY].state='25'
        self.assertIn((engine.C2,-8),engine.calculate(s,BASE,12,persistent_shortfall=True)['writes'])
        s[engine.ROOM2].state='19.6'
        self.assertNotIn(engine.C2,dict(engine.calculate(s,BASE,12)['writes']))
        self.assertIn((engine.C2,-10),engine.calculate(s,BASE,12,persistent_shortfall=True)['writes'])
        s[engine.SUPPLY].state='36';s[engine.PRIORITY].state='Hot water'
        self.assertNotIn(engine.C2,dict(engine.calculate(s,BASE,12)['writes']))

    def test_reported_supply_gap_does_not_lock_out_colder_or_equal_c2(self):
        for downstairs in (19.,19.12,19.43):
            s=states_at(BASE)
            for e,v in {engine.ROOM1:19.43,engine.ROOM2:downstairs,engine.C1:9,engine.C2:-10,
                         engine.SUPPLY:34.6,engine.REQUIRED:48.9}.items():
                s[e].state=str(v)
            result=engine.calculate(s,BASE,12,persistent_shortfall=True)
            self.assertEqual(result['targets'],[20,20])
            self.assertIn((engine.C2,-9),result['writes'])
            self.assertLessEqual(len(result['writes']),3)
        s[engine.ROOM2].state='19.6';s[engine.C2].state='-9'
        self.assertIn((engine.C2,-10),engine.calculate(s,BASE,12,persistent_shortfall=True)['writes'])

if __name__=='__main__':unittest.main()
