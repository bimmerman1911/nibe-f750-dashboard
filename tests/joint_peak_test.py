"""Delayed-response search must retain peak avoidance through the full horizon."""
import unittest
from joint_scenarios_test import joint, readings, timeline, NOW


def scenario():
    states=readings(NOW,room=19.815,tank=46.75,q=4.2*20/89)
    values={'sensor.ovanvaning_temperature':19.4,'sensor.nedervaning_temperature':20.23,
            'number.vp_heating_offset_climate_system_1':10,
            'sensor.vp_supply_line_bt61':48.8,
            'sensor.vp_calculated_supply_climate_system_1':48.1,
            'sensor.vp_current_compressor_frequency':20,
            'sensor.vp_max_compressor_frequency':89,
            'sensor.vp_degree_minutes_2':-42,'sensor.vp_current_outd_temp_bt1':5.2}
    for e,v in values.items():states[e].state=str(v)
    model={'heat_loss_kw_per_k':.144,'thermal_capacity_kwh_per_k':14.7,
           'internal_gain_kw':.395,'heating_lag_hours':4.,'initial_heat_kw':2.48,
           'room_min_c':19.,'room_max_c':21.,'room_target_c':20.,
           'dhw_morning_completed':True,'timezone':'Europe/Stockholm'}
    response={'theta':[.56,.19,.11,1.6],'offset_gain':2.23,'start_dm':-255}
    emitter={'conductance_kw_per_k':.17,'observations':20}
    slots=timeline(NOW,count=48,price=lambda i:4.5 if i<12 else 7.5 if i<28 else 3.4,outdoor=5.)
    return slots,states,model,response,emitter


class PeakTests(unittest.TestCase):
    def test_delayed_heat_does_not_discard_cheaper_peak_avoidance(self):
        slots,states,model,response,emitter=scenario()
        result=joint.plan(slots,states,NOW,model,response,max_hz=89,emitter=emitter)
        peak=sum(s['compressor_kw']*.25 for s in result['steps'][12:28])
        self.assertLess(peak,3.)
        self.assertLess(result['model_cost'],45.)
        self.assertLessEqual(result['constraint_violation_score'],1e-10)
        self.assertGreaterEqual(min(s['room1'] for s in result['steps']),19.)
        self.assertLessEqual(max(s['room2'] for s in result['steps']),21.)
        candidates=result['planning']['candidate_costs']
        self.assertEqual(result['planning']['candidate_schedules'],5)
        self.assertEqual(tuple(result['selection_score']),min((c['violation'],c['objective']) for c in candidates))

    def test_surviving_strategies_observe_a_future_native_write_gate(self):
        slots,states,model,response,emitter=scenario()
        result=joint.plan(slots,states,NOW,model,response,max_hz=89,emitter=emitter,command_not_before=NOW+930)
        self.assertTrue(result['commands'][0]['locked'])
        self.assertEqual(result['commands'][0]['offset'],10.)
        self.assertEqual(result['commands'][0]['end'],NOW+960)
        self.assertTrue(all(c['end']-c['start']>=960 for c in result['commands'][:-1]))


if __name__=='__main__':unittest.main()
