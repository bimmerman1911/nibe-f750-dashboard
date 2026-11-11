"""Activity timing describes simulated production, and remains as issued."""
import unittest, copy
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL
from integration_test import load

class ActivityTests(unittest.TestCase):
    def test_timing_covers_each_interval_without_gaps_or_overlaps(self):
        result=joint.plan(timeline(count=8),readings(tank=45),NOW,MODEL,command_not_before=NOW+75)
        for s in result['steps']:
            cursor=s['start']
            for a in s['activity']:
                self.assertAlmostEqual(a['start'],cursor)
                self.assertGreater(a['end'],a['start'])
                self.assertIn(a['action'],('heat','dhw','off'))
                cursor=a['end']
            self.assertAlmostEqual(cursor,s['end'])
        self.assertEqual(result['commands'][0]['end'],NOW+120)

    def test_normal_permission_without_native_charging_has_no_dhw_activity(self):
        states=readings(tank=52)
        states['select.vp_comfort_mode'].state='Normal'
        result=joint.plan(timeline(count=4),states,NOW,{**MODEL,'dhw_profile':[0.]*24},command_not_before=NOW+1800)
        for s in result['steps']:
            if s['end']<=NOW+1800:
                self.assertNotIn('dhw',[a['action'] for a in s['activity']])

    def test_activity_history_is_immutable_after_issue_and_survives_restore(self):
        module=load('accounting');store=module.Accounting()
        segments=[{'start':NOW,'end':NOW+45,'action':'dhw','inline_kw':0.},
                  {'start':NOW+45,'end':NOW+900,'action':'off','inline_kw':0.}]
        step={'start':NOW,'end':NOW+900,'compressor_kw':.05,'inline_kw':0.,'price':2.,'action':'dhw','activity':segments}
        store.forecast({'generated_at':NOW-60,'steps':[step]},NOW-60)
        saved=copy.deepcopy(segments);segments.clear()
        store.forecast({'generated_at':NOW+60,'steps':[{**step,'activity':[]}]},NOW+60)
        self.assertEqual(store.view(NOW+60)['history'][0]['activity'],saved)
        restored=module.Accounting();restored.restore(copy.deepcopy(store.dump()))
        self.assertEqual(restored.view(NOW+60)['history'][0]['activity'],saved)
        merged=module.Accounting();merged.merge_history(restored,NOW+60)
        self.assertEqual(merged.view(NOW+60)['history'][0]['activity'],saved)

if __name__=='__main__':unittest.main()
