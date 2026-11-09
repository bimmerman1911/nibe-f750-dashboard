"""Independent behavioural checks for the joint native-command planner."""
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import unittest
from integration_test import load, engine
from adaptive_test import states_at

joint=load('joint')
NOW=datetime.fromisoformat('2026-11-09T12:00:00+01:00').timestamp()
MODEL={'room_min_c':18.,'dhw_draw_kw':0.,'dhw_profile':[0.]*24,
       'auxiliary_limit_kw':0.,'initial_heat_kw':2.1,'heating_lag_hours':1.,
       'timezone':'Europe/Stockholm'}


def readings(now=NOW,room=19.,tank=52.,mode='Heating',q=2.1):
    states=states_at(now,room=room,outdoor=0.,q=q,tank=tank,mode=mode)
    states[engine.ROOM1].state=states[engine.ROOM2].state=str(room)
    return states


def timeline(now=NOW,count=48,price=lambda i:4. if i<16 else .2,outdoor=0.):
    return [{'start':now+i*900,'end':now+(i+1)*900,'dt':.25,
             'price':price(i),'outdoor':outdoor} for i in range(count)]


def electric(result,until):
    return sum((s['compressor_kw']+s['inline_kw'])*(min(until,s['end'])-s['start'])/3600
               for s in result['steps'] if s['start']<until)

class LimitedBudget:
    def __init__(self,cancelled=False):self.cancelled=cancelled
    def remaining(self):return 2.
    def check(self):raise AssertionError('Reduced-search completion should use the cancellation check')
    def check_cancelled(self):
        if self.cancelled:raise RuntimeError('cancelled')

class JointScenarios(unittest.TestCase):
    def test_price_flexibility_uses_allowed_minimum_and_future_prices(self):
        slots=timeline()
        flexible=joint.plan(slots,readings(),NOW,MODEL)
        tighter=joint.plan(slots,readings(),NOW,{**MODEL,'room_min_c':19.})
        cheap_first=joint.plan(timeline(price=lambda i:.2 if i<16 else 4.),readings(),NOW,MODEL)
        self.assertLess(electric(flexible,NOW+4*3600),electric(tighter,NOW+4*3600))
        self.assertLess(electric(flexible,NOW+4*3600),electric(cheap_first,NOW+4*3600))
        self.assertNotEqual([c['offset'] for c in flexible['commands']],[c['offset'] for c in cheap_first['commands']])
        self.assertTrue(any(s['room1']<19. for s in flexible['steps']))
        self.assertGreaterEqual(min(s['room1'] for s in flexible['steps']),18.)
        self.assertGreaterEqual(min(s['room1'] for s in tighter['steps']),19.)

    def test_saturated_reported_state_uses_observed_emitter_capacity(self):
        states=readings(room=19.265,q=4.2*87/88)
        for entity,value in {engine.C1:9,engine.SUPPLY:34.6,engine.REQUIRED:48.9,
                             'sensor.vp_current_compressor_frequency':87,
                             'sensor.vp_max_compressor_frequency':88,
                             'sensor.vp_degree_minutes_2':-759}.items():
            states[entity].state=str(value)
        result=joint.plan(timeline(count=24,price=lambda i:2.7),states,NOW,MODEL,max_hz=88)
        self.assertAlmostEqual(result['emitter']['conductance_kw_per_k'],4.2*(87/88)/(34.6-19.265))
        self.assertTrue(all(-10<=c['offset']<=10 for c in result['commands']))
        self.assertTrue(any(abs(c['offset']-9)>1 for c in result['commands']))
        self.assertLess(result['steps'][-1]['supply'],42.)
        self.assertTrue(all(s['inline_kw']==0 for s in result['steps']))

    def test_normal_permission_does_not_force_dhw_above_native_start(self):
        states=readings(room=20.,tank=49.,mode='Off',q=0.)
        states[engine.DHW].state='Normal'
        result=joint.plan(timeline(count=8),states,NOW,{**MODEL,'initial_heat_kw':0.},command_not_before=NOW+3600)
        self.assertEqual(result['commands'][0]['dhw_mode'],'Normal')
        self.assertTrue(result['commands'][0]['locked'])
        self.assertTrue(all(s['action']!='dhw' for s in result['steps'] if s['end']<=NOW+3600))

    def test_shared_compressor_is_not_allocated_to_space_and_dhw_together(self):
        now=datetime.fromisoformat('2026-11-09T05:00:00+01:00').timestamp()
        states=readings(now,room=20.,tank=42.)
        charge=joint.charge;filtered=joint.filtered_heat
        current={'water':False,'count':0}
        def water(*args,**kwargs):
            result=charge(*args,**kwargs);current['water']=result[1]>0
            if current['water']:current['count']+=1
            return result
        def heat(previous,command,hours,lag):
            if current['water']:self.assertEqual(command,0.)
            return filtered(previous,command,hours,lag)
        with patch.object(joint,'charge',side_effect=water),patch.object(joint,'filtered_heat',side_effect=heat):
            result=joint.plan(timeline(now,count=8),states,now,MODEL,budget=LimitedBudget())
        self.assertGreater(current['count'],0)
        self.assertEqual(len(result['steps']),8)

    def test_command_gate_spacing_and_quarter_hour_energy_remain_consistent(self):
        slots=timeline(count=8,price=lambda i:1 if i<3 else 3)
        result=joint.plan(slots,readings(),NOW,MODEL,command_not_before=NOW+600)
        commands=result['commands'];steps=result['steps']
        self.assertTrue(commands[0]['locked'])
        self.assertEqual(commands[0]['offset'],0.)
        self.assertGreaterEqual(commands[0]['end'],NOW+600)
        unlocked=[c for c in commands if not c['locked']]
        for before,after in zip(unlocked,unlocked[1:]):
            self.assertGreaterEqual(after['start']-before['start'],960.)
        self.assertEqual([(s['start'],s['end']) for s in steps],[(s['start'],s['end']) for s in slots])
        self.assertAlmostEqual(result['model_cost'],sum((s['compressor_kw']+s['inline_kw'])*s['dt']*s['price'] for s in steps))
        self.assertTrue(result['planning']['short_horizon'])

    def test_morning_reserve_pause_and_late_full_charge_work_across_dst(self):
        for stamp in ('2026-11-09T00:00:00+01:00','2026-03-29T00:00:00+01:00'):
            with self.subTest(start=stamp):
                now=datetime.fromisoformat(stamp).timestamp()
                end=datetime.fromtimestamp(now,ZoneInfo('Europe/Stockholm')).replace(hour=6).timestamp()
                slots=timeline(now,count=int((end-now)/900),price=lambda i:.2 if i<8 else 2.,outdoor=10.)
                result=joint.plan(slots,readings(now,room=20.,tank=46.),now,{**MODEL,'dhw_profile':[.1]*24})
                self.assertEqual(result['horizon_end'],end)
                self.assertEqual(datetime.fromtimestamp(end,ZoneInfo('Europe/Stockholm')).hour,6)
                self.assertGreaterEqual(result['steps'][-1]['water'],51.5)
                self.assertEqual(result['dhw_deadline_shortfall_c'],0.)
                self.assertTrue(any(c.get('economic_pause') for c in result['commands']))
                expected=max(0,result['model']['tank_max_c']-.5-result['steps'][-1]['water'])
                self.assertAlmostEqual(result['dhw_deadline_shortfall_c'],expected)

    def test_imminent_morning_charge_reaches_full_when_physically_reachable(self):
        now=datetime.fromisoformat('2026-11-09T04:30:00+01:00').timestamp()
        result=joint.plan(timeline(now,count=6,outdoor=10.),readings(now,room=20.,tank=42.),now,
                          {**MODEL,'dhw_profile':[.1]*24})
        self.assertEqual(result['commands'][0]['dhw_mode'],'Normal')
        self.assertEqual(result['dhw_deadline_shortfall_c'],0.)
        self.assertGreaterEqual(result['steps'][-1]['water'],51.5)

    def test_native_start_threshold_can_prevent_morning_topup(self):
        now=datetime.fromisoformat('2026-11-09T04:30:00+01:00').timestamp()
        result=joint.plan(timeline(now,count=6,outdoor=10.),readings(now,room=20.,tank=49.),now,
                          {**MODEL,'dhw_profile':[.1]*24})
        self.assertGreater(result['dhw_deadline_shortfall_c'],.5)
        self.assertTrue(any(c['dhw_mode']=='Normal' for c in result['commands']))

    def test_budget_reduction_completes_horizon_and_cancellation_stops(self):
        slots=timeline(count=32)
        result=joint.plan(slots,readings(),NOW,MODEL,budget=LimitedBudget())
        self.assertTrue(result['planning']['search_limited'])
        self.assertEqual(result['horizon_end'],slots[-1]['end'])
        self.assertEqual(len(result['steps']),len(slots))
        self.assertTrue(all(s['compressor_kw']>=0 for s in result['steps']))
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            joint.plan(slots,readings(),NOW,MODEL,budget=LimitedBudget(cancelled=True))

if __name__=='__main__':unittest.main()
