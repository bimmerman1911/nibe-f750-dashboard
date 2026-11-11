"""A cheaper evening beyond the visible/old heuristic horizon must be considered."""
import unittest
from joint_scenarios_test import joint,readings,timeline,NOW


def case(hours=14,room=20.2,lag=4.):
    states=readings(room=room,q=0,tank=52,mode='Off')
    model={'room_min_c':18.,'room_max_c':20.5,'room_target_c':20.,
           'heat_loss_kw_per_k':.12,'thermal_capacity_kwh_per_k':18.,
           'internal_gain_kw':0.,'heating_lag_hours':lag,'initial_heat_kw':.5,
           'dhw_profile':[0.]*24,'dhw_draw_kw':0.,'dhw_morning_completed':True,
           'timezone':'Europe/Stockholm'}
    slots=timeline(count=96,price=lambda i:5.5+.02*(i%3) if i<hours*4 else 1.)
    return slots,states,model


class FullHorizonTests(unittest.TestCase):
    def test_waits_for_cheaper_period_beyond_twelve_hours_when_comfort_allows(self):
        slots,states,model=case()
        result=joint.plan(slots,states,NOW,model)
        before=sum(s['compressor_kw']*.25 for s in result['steps'][:56])
        after=sum(s['compressor_kw']*.25 for s in result['steps'][56:])
        self.assertLess(before,.3)
        self.assertGreater(after,1.)
        self.assertEqual(result['planning']['price_lookahead_hours'],24.)
        self.assertTrue(any(t>=NOW+13*3600 for t in result['planning']['defer_until_candidates']))
        self.assertLessEqual(result['constraint_violation_score'],1e-10)
        self.assertGreaterEqual(min(s['room1'] for s in result['steps']),18.)
        self.assertLessEqual(max(s['room2'] for s in result['steps']),20.5)

    def test_low_room_cannot_wait_for_a_distant_cheap_evening(self):
        slots,states,model=case(room=18.2,lag=1.)
        result=joint.plan(slots,states,NOW,model)
        self.assertGreater(sum(s['compressor_kw']*.25 for s in result['steps'][:16]),1.)
        self.assertGreaterEqual(min(s['room1'] for s in result['steps']),18.)
        self.assertTrue(all(-10<=c['offset']<=10 for c in result['commands']))

    def test_flat_prices_do_not_invent_cheaper_windows_and_short_horizons_work(self):
        slots,states,model=case()
        for slot in slots:slot['price']=5.
        self.assertEqual(joint.cheaper_windows(slots,NOW),[])
        short=slots[:8]
        result=joint.plan(short,states,NOW,model)
        self.assertEqual(len(result['steps']),8)
        self.assertEqual(result['horizon_end'],short[-1]['end'])
        self.assertEqual(result['planning']['price_lookahead_hours'],2.)

    def test_partial_intervals_negative_prices_and_cancelled_budget(self):
        slots,states,model=case(hours=10)
        for slot in slots[40:]:slot['price']=-1.
        slots[0]['end']=NOW+600;slots[1]['start']=NOW+600
        result=joint.plan(slots,states,NOW,model)
        self.assertLessEqual(result['constraint_violation_score'],1e-10)
        self.assertLessEqual(max(s['room1'] for s in result['steps']),20.5)
        from integration_test import load
        budget=load('work').PlanningBudget();budget.cancelled.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            joint.plan(slots,states,NOW,model,budget=budget)


if __name__=='__main__':unittest.main()
