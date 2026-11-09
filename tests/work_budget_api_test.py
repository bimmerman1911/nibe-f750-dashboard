"""Soft deadline introspection stays distinct from executor cancellation."""
import unittest
from integration_test import load
work=load('work')

class BudgetApiTests(unittest.TestCase):
    def test_remaining_counts_down_and_never_becomes_negative(self):
        now=[100.]
        budget=work.PlanningBudget(12,clock=lambda:now[0])
        self.assertEqual(budget.remaining(),12)
        now[0]=109.5
        self.assertEqual(budget.remaining(),2.5)
        now[0]=115
        self.assertEqual(budget.remaining(),0)

    def test_soft_deadline_does_not_disable_cancellation_only_checks(self):
        now=[0.]
        budget=work.PlanningBudget(12,clock=lambda:now[0])
        now[0]=20
        budget.check_cancelled()
        self.assertRaisesRegex(RuntimeError,'budget',budget.check)
        budget.cancelled.set()
        self.assertRaisesRegex(RuntimeError,'cancelled',budget.check_cancelled)

    def test_cancellation_only_check_does_not_call_clock(self):
        budget=work.PlanningBudget()
        def bad_clock():
            raise AssertionError('Cancellation must not need a clock read')
        budget.clock=bad_clock
        budget.check_cancelled()
        budget.cancelled.set()
        self.assertRaisesRegex(RuntimeError,'cancelled',budget.check_cancelled)

if __name__=='__main__':unittest.main()
