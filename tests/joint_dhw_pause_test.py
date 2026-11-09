"""Explicitly planned reserve top-up pauses must remain safely restartable."""
import unittest
from datetime import datetime
from integration_test import load
module=load('dhw');predictive=load('predictive')
MODEL={**predictive.DEFAULTS,'timezone':'Europe/Stockholm','dhw_start_c':48.,'dhw_fraction':.75,'dhw_profile':[.1]*24}
NOON=datetime.fromisoformat('2026-11-09T12:00:00+01:00').timestamp()

class PauseTests(unittest.TestCase):
    def test_only_explicit_economy_plan_may_pause_a_restartable_active_charge(self):
        ordinary=module.policy(46,True,False,NOON,MODEL)
        self.assertEqual(ordinary['dhw'],'Normal')
        decision=module.policy(46,True,False,NOON,MODEL,allow_pause=True)
        self.assertEqual(decision['dhw'],'Economy')
        self.assertTrue(decision['dhw_economic_pause'])
        self.assertIn('restartable',decision['dhw_reason'])
        self.assertEqual(module.policy(46,True,True,NOON,MODEL,allow_pause=True)['dhw'],'Normal')

    def test_low_reserve_morning_and_pending_recovery_cannot_be_interrupted(self):
        self.assertEqual(module.policy(44,True,False,NOON,MODEL,allow_pause=True)['dhw'],'Normal')
        self.assertEqual(module.policy(44.4,True,False,NOON,MODEL,allow_pause=True)['dhw'],'Normal')
        dawn=datetime.fromisoformat('2026-11-09T05:45:00+01:00').timestamp()
        self.assertEqual(module.policy(46,True,False,dawn,MODEL,allow_pause=True)['dhw'],'Normal')
        pending={**MODEL,'dhw_morning_pending':True}
        self.assertEqual(module.policy(46,True,False,NOON,pending,allow_pause=True)['dhw'],'Normal')
        high_draw={**MODEL,'dhw_profile':[2.]*24}
        self.assertEqual(module.policy(46,True,False,NOON,high_draw,allow_pause=True)['dhw'],'Normal')

    def test_tank_above_restart_threshold_must_finish_charge(self):
        for tank in (47.8,48.,49.):
            decision=module.policy(tank,True,False,NOON,MODEL,allow_pause=True)
            self.assertEqual(decision['dhw'],'Normal')
            self.assertFalse(decision['dhw_economic_pause'])
        self.assertEqual(module.policy(47.5,True,False,NOON,MODEL,allow_pause=True)['dhw'],'Economy')
        learned={**MODEL,'dhw_start_c':46.}
        self.assertEqual(module.policy(46,True,False,NOON,learned,allow_pause=True)['dhw'],'Normal')
        self.assertEqual(module.policy(45.5,True,False,NOON,learned,allow_pause=True)['dhw'],'Economy')

if __name__=='__main__':unittest.main()
