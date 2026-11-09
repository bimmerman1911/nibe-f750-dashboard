"""Joint planner contract, extreme prices and daily reserve completion."""
import unittest
from joint_scenarios_test import joint, readings, timeline, NOW, MODEL

class Budget:
    def __init__(self):self.calls=0
    def remaining(self):
        self.calls+=1
        return 10 if self.calls<3 else 0
    def check(self):pass
    def check_cancelled(self):pass

class Tests(unittest.TestCase):
    def test_deadline_expires_inside_expansion_but_complete_plan_is_returned(self):
        slots=timeline(count=12)
        r=joint.plan(slots,readings(),NOW,MODEL,budget=Budget())
        self.assertTrue(r['planning']['search_limited'])
        self.assertEqual(r['horizon_end'],slots[-1]['end'])
        self.assertEqual(len(r['steps']),12)

    def test_negative_prices_do_not_buy_comfort_violations(self):
        r=joint.plan(timeline(count=24,price=lambda i:-100.),readings(room=20.),NOW,MODEL)
        self.assertTrue(all(18<=s['room1']<=20.5 for s in r['steps']))
        self.assertLessEqual(r['constraint_violation_score'],1e-10)
        self.assertEqual(r['inline_kwh'],0.)

    def test_input_validation_and_narrow_comfort_range(self):
        for key,value in [('thermal_capacity_kwh_per_k',0),('offset_gain',0),('dhw_fraction',float('nan'))]:
            with self.subTest(key=key):
                options={**MODEL,key:value};response={'offset_gain':value} if key=='offset_gain' else {}
                with self.assertRaises(ValueError):joint.plan(timeline(count=4),readings(),NOW,options,response)
        slots=timeline(count=4);slots[1]['start']+=1
        with self.assertRaisesRegex(ValueError,'timeline'):joint.plan(slots,readings(),NOW,MODEL)
        r=joint.plan(timeline(count=4),readings(room=20.),NOW,{**MODEL,'room_min_c':20,'room_target_c':20,'room_max_c':20})
        self.assertEqual(r['planning']['comfort_margin_c'],0.)

    def test_lower_native_tank_ceiling_does_not_disable_space_heat_planning(self):
        r=joint.plan(timeline(count=4),readings(),NOW,{**MODEL,'tank_max_c':49.,'tank_target_c':55.,'tank_min_c':50.})
        self.assertTrue(r['steps'])
        self.assertTrue(r['planning']['native_tank_goal_limited'])
        self.assertEqual(r['planning']['requested_tank_target_c'],55.)
        self.assertEqual(r['model']['tank_target_c'],49.)

    def test_successful_morning_does_not_trigger_another_missed_goal_after_draw(self):
        from datetime import datetime
        now=datetime.fromisoformat('2026-11-09T07:00:00+01:00').timestamp()
        r=joint.plan(timeline(now,count=4,price=lambda i:4),readings(now,tank=49.),now,
                     {**MODEL,'dhw_morning_completed':True,'dhw_morning_pending':True})
        self.assertEqual(r['commands'][0]['dhw_mode'],'Economy')

if __name__=='__main__':unittest.main()
