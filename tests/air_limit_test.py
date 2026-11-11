"""Simple physical envelope: qualify, calibrate, scale and preserve heat units."""
import copy,unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from integration_test import load
from joint_scenarios_test import joint,readings,timeline,NOW,MODEL

air=load('air_limit')

def states(t,flow=160,tin=20,evap=-16.5,hz=80,dm=-300,mode='Heating'):
    def s(v,u=''):return SimpleNamespace(state=str(v),attributes={'unit_of_measurement':u},last_reported=datetime.fromtimestamp(t,timezone.utc),last_updated=datetime.fromtimestamp(t,timezone.utc))
    return {air.FLOW:s(flow,'m³/h'),air.INLET:s(tin,'°C'),air.EVAP:s(evap,'°C'),air.HZ:s(hz,'Hz'),
            'sensor.vp_priority':s(mode),'sensor.vp_degree_minutes_2':s(dm),
            'sensor.vp_supply_line_bt61':s(35),'sensor.vp_calculated_supply_climate_system_1':s(45)}

def calibrated():
    model=air.AirLimit()
    for i in range(11):model.update(states(NOW+i*60),NOW+i*60)
    return model

class AirTests(unittest.TestCase):
    def test_coefficient_is_calibrated_only_after_ten_minutes(self):
        m=calibrated();self.assertEqual(len(m.observations),1)
        self.assertAlmostEqual(m.observations[0]['k'],80/(160*36.5))
        a=m.estimate(states(NOW+600),NOW+600,120,20)
        b=m.estimate(states(NOW+600,flow=80),NOW+600,120,20)
        self.assertTrue(a['calibrated']);self.assertAlmostEqual(a['effective_max_hz'],2*b['effective_max_hz'])
        self.assertLess(a['effective_max_hz'],80)
        self.assertEqual(m.estimate(states(NOW+600),NOW+600,60,20)['effective_max_hz'],60)
        c=m.estimate(states(NOW+600,tin=15),NOW+600,120,20)
        self.assertLess(c['effective_max_hz'],a['effective_max_hz'])

    def test_plateau_without_cold_evaporator_or_demand_is_not_a_limit(self):
        for kwargs in ({'evap':-5},{'dm':-20},{'mode':'Hot water'}):
            m=air.AirLimit()
            for i in range(11):m.update(states(NOW+i*60,**kwargs),NOW+i*60)
            self.assertEqual(m.observations,[])
        m=air.AirLimit()
        for i in range(11):m.update(states(NOW+i*60,hz=40+i*3),NOW+i*60)
        self.assertEqual(m.observations,[])

    def test_cached_values_missing_units_defrost_and_gaps_do_not_calibrate(self):
        m=air.AirLimit();s=states(NOW)
        for i in range(11):m.update(s,NOW+i*60)
        self.assertEqual(m.observations,[])
        for i in range(11):
            s=states(NOW+i*60);s[air.FLOW].attributes={};m.update(s,NOW+i*60)
        self.assertEqual(m.observations,[])
        s=states(NOW);s['sensor.vp_status']=SimpleNamespace(state='Defrosting',attributes={},last_reported=s[air.HZ].last_reported)
        self.assertIsNone(air.sample(s,NOW))
        m.update(states(NOW),NOW);m.update(states(NOW+600),NOW+600)
        self.assertEqual(m.observations,[])
        self.assertEqual(len(m.samples),1)

    def test_state_restore_and_stale_calibration(self):
        m=calibrated();n=air.AirLimit();self.assertTrue(n.restore(copy.deepcopy(m.dump())))
        self.assertTrue(n.estimate(states(NOW+600),NOW+600,120,20)['calibrated'])
        t=NOW+15*86400;r=n.estimate(states(t,hz=40),t,120,20)
        self.assertFalse(r['calibrated']);self.assertEqual(r['effective_max_hz'],40)
        self.assertFalse(air.AirLimit().restore({'version':1,'observations':[{'k':float('nan')}]}))

    def test_volume_unit_conversion_and_sustained_provisional_cap(self):
        m=air.AirLimit()
        for i in range(11):m.update(states(NOW+i*60,evap=-5,hz=60),NOW+i*60)
        s=states(NOW+600,flow=160/3.6);s[air.FLOW].attributes['unit_of_measurement']='l/s'
        r=m.estimate(s,NOW+600,120,20)
        self.assertFalse(r['calibrated']);self.assertEqual(r['effective_max_hz'],60)
        self.assertAlmostEqual(r['airflow_m3h'],160)

    def test_frequency_cap_reduces_available_heat_without_renormalising_it(self):
        s=readings(room=19.,tank=45.);s['sensor.vp_max_compressor_frequency'].state='120'
        r=joint.plan(timeline(count=8),s,NOW,{**MODEL,'frequency_reference_hz':120.,'dhw_fraction':.9},max_hz=80)
        self.assertAlmostEqual(r['planning']['available_compressor_heat_kw'],4.2*80/120)
        self.assertTrue(all(row['hz']<=80+1e-7 for row in r['steps']))
        self.assertEqual(r['model']['dhw_fraction'],80/120)

    def test_recorder_replay_qualifies_observed_continuous_windows(self):
        recorded={}
        for i in range(21):
            for e,s in states(NOW+i*60,evap=-16.5+(i%2)*.1).items():recorded.setdefault(e,[]).append(s)
        data=air.replay(recorded,NOW,NOW+1200)
        self.assertEqual(len(data['observations']),2)
        empty=air.replay({e:[rows[0]] for e,rows in recorded.items()},NOW,NOW+1200)
        self.assertEqual(empty['observations'],[])

if __name__=='__main__':unittest.main()
