"""Power integration, counterfactual coverage, history replay and calendar checks."""
from datetime import datetime, timezone
import copy
import unittest
from types import SimpleNamespace
from integration_test import load
from adaptive_test import states_at

accounting=load('accounting')
history=load('history')
BASE=datetime(2026,11,4,11,0,tzinfo=timezone.utc).timestamp() # Wed noon Stockholm

def readings(t,kw_inline=1.,tariff=2.):
    states=states_at(t,room=20,outdoor=5,q=2.5,tank=49)
    states['sensor.vp_current_compressor_frequency'].state='50'
    states['sensor.vp_condenser_bt12']=SimpleNamespace(entity_id='sensor.vp_condenser_bt12',state='45',attributes={},last_reported=datetime.fromtimestamp(t,timezone.utc))
    states['sensor.vp_power_internal_add_heat'].state=str(kw_inline)
    states['sensor.nordpool_kwh_se3_sek_3_10_025']=SimpleNamespace(state=str(tariff),attributes={'unit_of_measurement':'SEK/kWh'},last_reported=datetime.fromtimestamp(t,timezone.utc))
    states['select.vp_set_max_electrical_add']=SimpleNamespace(state='6.5 kW',attributes={},last_reported=datetime.fromtimestamp(t,timezone.utc))
    return states

class AccountingTests(unittest.TestCase):
    def test_costs_and_power_use_duration_not_sample_count(self):
        a=accounting.Accounting()
        for minute in range(16):
            a.observe(readings(BASE+minute*60),BASE+minute*60,{}, {})
        row=a.view(BASE+900)['history'][0]
        expected=50*.0161+1
        self.assertAlmostEqual(row['actual_kw'],expected)
        week=a.view(BASE+900)['week']
        wed=week[2]
        self.assertAlmostEqual(wed['actual'],expected*.25*2)
        self.assertAlmostEqual(wed['covered_hours'],.25)
        self.assertIsNotNone(wed['baseline'])
        self.assertEqual(len(week),7)
        self.assertTrue(all(day['actual'] is None and day['baseline'] is None for day in week[3:]))

    def test_missing_inputs_and_downtime_are_not_zero_or_full_coverage(self):
        a=accounting.Accounting()
        a.observe(readings(BASE),BASE,{}, {})
        a.observe(readings(BASE+3600),BASE+3600,{}, {})
        self.assertTrue(all(day['actual'] is None for day in a.view(BASE+3600)['week']))
        bad=readings(BASE+3660);bad['sensor.ovanvaning_temperature'].state='unknown'
        a.observe(bad,BASE+3660,{}, {})
        a.observe(bad,BASE+3720,{}, {})
        wed=a.view(BASE+3720)['week'][2]
        self.assertGreater(wed['actual'],0)
        self.assertIsNone(wed['baseline'])

    def test_predicted_history_is_frozen_after_the_interval_starts(self):
        a=accounting.Accounting()
        def forecast(power):
            return {'generated_at':BASE,'steps':[{'start':BASE,'end':BASE+900,'compressor_kw':power,'inline_kw':0,'price':1,'action':'heat'}]}
        a.forecast(forecast(2),BASE-60)
        a.forecast(forecast(5),BASE+30)
        self.assertEqual(a.bins[BASE]['predicted_kw'],2)
        restored=accounting.Accounting();restored.restore(copy.deepcopy(a.dump()))
        self.assertEqual(restored.bins[BASE]['predicted_kw'],2)
        self.assertIsNone(restored.previous)

    def test_local_midnight_splits_and_negative_prices(self):
        midnight=datetime(2026,11,5,0,0,tzinfo=accounting.ZoneInfo('Europe/Stockholm')).timestamp()
        a=accounting.Accounting()
        for t in (midnight-60,midnight+60):
            a.observe(readings(t,tariff=-1),t,{}, {})
        self.assertEqual(set(a.days),{'2026-11-04','2026-11-05'})
        self.assertTrue(all(day['actual']<0 for day in a.days.values()))
        self.assertAlmostEqual(sum(day['seconds'] for day in a.days.values()),120)

    def test_merge_and_historical_replay(self):
        old={}
        for minute in range(16):
            for id,state in readings(BASE+minute*60).items():
                state.last_updated=datetime.fromtimestamp(BASE+minute*60,timezone.utc)
                old.setdefault(id,[]).append(state)
        replay=history.replay(old,BASE,BASE+900,'Europe/Stockholm',{})
        self.assertAlmostEqual(replay.days['2026-11-04']['seconds'],900)
        live=accounting.Accounting()
        live.observe(readings(BASE+900),BASE+900,{}, {})
        live.observe(readings(BASE+960),BASE+960,{}, {})
        live.merge_history(replay,BASE+900)
        self.assertAlmostEqual(live.days['2026-11-04']['seconds'],960)
        self.assertTrue(live.history_checked)

    def test_tariff_boundary_uses_published_intervals_and_unit_conversion(self):
        a=accounting.Accounting()
        for t in (BASE+840,BASE+960):
            states=readings(t,kw_inline=0,tariff=9000)
            states['sensor.nordpool_kwh_se3_sek_3_10_025'].attributes={
                'unit_of_measurement':'SEK/MWh','raw_today':[
                    {'start':datetime.fromtimestamp(BASE,timezone.utc).isoformat(),
                     'end':datetime.fromtimestamp(BASE+900,timezone.utc).isoformat(),'value':1000},
                    {'start':datetime.fromtimestamp(BASE+900,timezone.utc).isoformat(),
                     'end':datetime.fromtimestamp(BASE+1800,timezone.utc).isoformat(),'value':3000}]}
            a.observe(states,t,{}, {})
        self.assertAlmostEqual(a.days['2026-11-04']['actual'],50*.0161/60*(1+3))

    def test_incomplete_forecast_and_unknown_heater_limit_leave_comparison_blank(self):
        a=accounting.Accounting()
        for t in (BASE,BASE+60):
            states=readings(t)
            del states['select.vp_set_max_electrical_add']
            del states['sensor.nordpool_kwh_se3_sek_3_10_025']
            a.observe(states,t,{}, {'generated_at':BASE,'steps':[{'start':BASE,'end':BASE+900}]})
        self.assertIsNotNone(a.view(BASE+60)['history'][0]['actual_kw'])
        self.assertIsNone(a.view(BASE+60)['week'][2]['actual'])
        a=accounting.Accounting()
        for t in (BASE,BASE+60):
            states=readings(t)
            del states['select.vp_set_max_electrical_add']
            a.observe(states,t,{}, {})
        self.assertGreater(a.view(BASE+60)['week'][2]['actual'],0)
        self.assertIsNone(a.view(BASE+60)['week'][2]['baseline'])

if __name__=='__main__':
    unittest.main()
