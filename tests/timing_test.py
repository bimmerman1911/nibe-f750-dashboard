"""Reject economically dominated schedules using the full native simulation."""
import copy,unittest
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL
from integration_test import load

timing=load('timing')
work=load('work')


def case():
    states=readings(room=20.,tank=52.)
    model={**MODEL,'room_min_c':19.3,'room_max_c':22.,'heat_loss_kw_per_k':.12,
           'thermal_capacity_kwh_per_k':16.,'initial_heat_kw':2.1}
    slots=timeline(count=40,price=lambda i:5. if 4<=i<16 else 1.,outdoor=5)
    commands=[{'start':NOW+i*960,'end':min(NOW+(i+1)*960,slots[-1]['end']),
               'offset':0 if i<16 else -10,'dhw_mode':'Economy'} for i in range(38)]
    def replay(commands):
        return joint._search(slots,states,NOW,model,max_hz=84,strategy='previous',incumbent={'commands':commands})
    return slots,replay(commands),replay


class TimingTests(unittest.TestCase):
    def test_moves_expensive_heating_to_cheaper_period_in_same_native_model(self):
        slots,seed,replay=case()
        self.assertEqual(seed['constraint_violation_score'],0.)
        result=timing.improve(seed,slots,list(range(-10,11)),replay,joint.selection_key)
        energy=lambda r,p:sum(s['compressor_kw']*s['dt'] for s in r['steps'] if s['price']==p)
        self.assertLess(energy(result,5),energy(seed,5)*.5)
        self.assertGreater(energy(result,1),energy(seed,1))
        self.assertLess(result['model_cost'],seed['model_cost']*.75)
        self.assertEqual(result['constraint_violation_score'],0.)
        self.assertEqual(result['morning_shortfall'],seed['morning_shortfall'])
        self.assertGreaterEqual(min(min(s['room1'],s['room2']) for s in result['steps']),19.3)
        self.assertTrue(any(r['kind']=='price-transfer' for r in result['planning']['timing_comparison']['improvements']))
        self.assertLessEqual(result['planning']['timing_comparison']['evaluated'],256)
        # Comparison replays do not change timestamp alignment or command rate.
        self.assertEqual([(c['start'],c['end']) for c in result['commands']],[(c['start'],c['end']) for c in seed['commands']])

    def test_transfers_preserve_locks_dhw_modes_and_native_offset_grid(self):
        slots,seed,_=case();seed=copy.deepcopy(seed)
        seed['commands'][0]['locked']=True
        seed['commands'][0]['offset']=0
        original=copy.deepcopy(seed)
        candidates=list(timing.transfers(seed,slots,list(range(-10,11,2))))
        self.assertTrue(candidates)
        for commands in candidates:
            self.assertEqual(commands[0],seed['commands'][0])
            self.assertEqual([c['dhw_mode'] for c in commands],[c['dhw_mode'] for c in seed['commands']])
            self.assertTrue(all(c['offset'] in range(-10,11,2) for c in commands))
            self.assertEqual([(c['start'],c['end']) for c in commands],[(c['start'],c['end']) for c in seed['commands']])
        self.assertEqual(seed,original)

    def test_budget_exhaustion_returns_existing_complete_schedule(self):
        slots,seed,_=case();budget=work.PlanningBudget(0)
        def no_replay(commands):self.fail('No budget remains')
        result=timing.improve(seed,slots,list(range(-10,11)),no_replay,joint.selection_key,budget)
        self.assertIs(result,seed)
        self.assertEqual(result['planning']['timing_comparison']['evaluated'],0)
        self.assertTrue(result['planning']['timing_comparison']['budget_limited'])

    def test_cancellation_propagates(self):
        slots,seed,replay=case();budget=work.PlanningBudget();budget.cancelled.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            timing.improve(seed,slots,list(range(-10,11)),replay,joint.selection_key,budget)

    def test_rejects_cheaper_schedules_that_add_comfort_violation(self):
        slots,seed,_=case()
        def unsafe(commands):
            candidate=copy.deepcopy(seed);candidate['commands']=commands
            candidate['model_cost']=0.;candidate['selection_score'][1]=0.
            candidate['constraint_violation_score']=.01
            return candidate
        result=timing.improve(seed,slots,list(range(-10,11)),unsafe,joint.selection_key,max_evaluations=8)
        self.assertIs(result,seed)
        self.assertTrue(result['planning']['timing_comparison']['cheaper_rejected'])

    def test_window_comparison_is_not_tied_to_clock_or_now_price(self):
        slots,seed,_=case()
        # Future peak/valley pairs are still tested when the current price is low.
        candidates=list(timing.transfers(seed,slots,list(range(-10,11))))
        self.assertTrue(any(any(a['start']>=NOW+3600 and a['offset']<b['offset'] for a,b in zip(c,seed['commands']))
                            and any(a['start']>=NOW+4*3600 and a['offset']>b['offset'] for a,b in zip(c,seed['commands'])) for c in candidates))

    def test_reserved_budget_shares_cancellation_and_preserves_parent_time(self):
        clock=[0.];parent=work.PlanningBudget(12,clock=lambda:clock[0]);child=work.ReservedBudget(parent,3)
        self.assertEqual(child.remaining(),9)
        clock[0]=10
        self.assertEqual(child.remaining(),0);self.assertEqual(parent.remaining(),2)
        with self.assertRaises(RuntimeError):child.check()
        parent.cancelled.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):child.check_cancelled()


if __name__=='__main__':unittest.main()
