"""Near-limit recovery with blocked auxiliary heat and secondary-circuit release."""
import unittest
from integration_test import Fixture, Store, load, engine, runtime
from adaptive_test import states_at, BASE
p=load('predictive')
recovery=load('degree_recovery')

class Tests(unittest.TestCase):
    def test_cold_start_and_low_tank_get_recovery_without_unblocking_heater(self):
        # Minimal numeric regression from the reported state, not private diagnostics.
        model={**p.DEFAULTS,'heat_loss_kw_per_k':.0981587742,'thermal_capacity_kwh_per_k':9,
            'internal_gain_kw':.20716551,'heating_lag_hours':1,'initial_heat_kw':0,
            'dhw_heat_kw':3.862855,'dhw_fraction':.772908,'dhw_start_c':48,'tank_max_c':51.45,
            'initial_mode':'dhw','auxiliary_limit_kw':0,'dhw_profile':[.15]*24}
        slots=[{'start':BASE+i*900,'end':BASE+(i+1)*900,'dt':.25,'price':2.949,'outdoor':-1.3} for i in range(96)]
        result=p.plan(slots,19.185,41.5,96,model)
        self.assertTrue(result['steps'])
        self.assertTrue(result['recovery_plan'])
        self.assertGreaterEqual(result['steps'][-1]['room'],20)
        self.assertGreaterEqual(result['steps'][-1]['water'],48)
        self.assertEqual(result['inline_kwh'],0)
        self.assertTrue(all(s['room']<=20.5 and s['water']<=51.45+1e-6 for s in result['steps']))

    def test_both_cold_rooms_can_recover_when_supply_is_available(self):
        s=states_at(BASE,room=19.2)
        s[engine.C2].state='-10'
        self.assertIn((engine.C2,-9),engine.calculate(s,BASE,12)['writes'])
        s[engine.C2].state='-9'
        s[engine.SUPPLY].state='25'
        self.assertIn((engine.C2,-8),engine.calculate(s,BASE,12,persistent_shortfall=True)['writes'])
        s[engine.ROOM2].state='19.6'
        self.assertNotIn(engine.C2,dict(engine.calculate(s,BASE,12)['writes']))
        self.assertIn((engine.C2,-10),engine.calculate(s,BASE,12,persistent_shortfall=True)['writes'])
        s[engine.SUPPLY].state='36';s[engine.PRIORITY].state='Hot water'
        self.assertNotIn(engine.C2,dict(engine.calculate(s,BASE,12)['writes']))

    def test_reported_supply_gap_does_not_lock_out_colder_or_equal_c2(self):
        for downstairs in (19.,19.12,19.43):
            s=states_at(BASE)
            for e,v in {engine.ROOM1:19.43,engine.ROOM2:downstairs,engine.C1:9,engine.C2:-10,
                         engine.SUPPLY:34.6,engine.REQUIRED:48.9}.items():
                s[e].state=str(v)
            result=engine.calculate(s,BASE,12,persistent_shortfall=True)
            self.assertEqual(result['targets'],[20,20])
            self.assertIn((engine.C2,-9),result['writes'])
            self.assertLessEqual(len(result['writes']),3)
        s[engine.ROOM2].state='19.6';s[engine.C2].state='-9'
        self.assertIn((engine.C2,-10),engine.calculate(s,BASE,12,persistent_shortfall=True)['writes'])

class ResetDetectionTests(unittest.TestCase):
    def setUp(self):
        self.hass = Fixture()
        self.hass.states.values.update({engine.ROOM1: '19.4', engine.ROOM2: '19.2',
                                        engine.SUPPLY: '51.6', engine.REQUIRED: '50.6',
                                        recovery.FREQUENCY: '71', recovery.DM: '-565'})

    def observe(self, tracker, elapsed, *, action='heat', **changes):
        self.hass.time += elapsed
        self.hass.states.values.update(changes)
        return tracker.observe({s.entity_id: s for s in self.hass.states.async_all()},
                               self.hass.time, True, action, 20.5)

    def test_reset_retains_the_original_deficit_until_it_is_restored(self):
        tracker = recovery.DegreeMinuteRecovery()
        self.observe(tracker, 0.)
        self.assertTrue(self.observe(tracker, 264., **{recovery.DM: '2', engine.REQUIRED: '20',
                                                     engine.PRIORITY: 'Off'}))
        self.assertEqual(tracker.event['target_dm'], -565.)
        self.assertFalse(self.observe(tracker, 60., **{recovery.DM: '-564'}))
        self.assertTrue(tracker.active)
        self.assertTrue(self.observe(tracker, 60., **{recovery.DM: '-565'}))
        self.assertEqual(tracker.event['status'], 'Restored')

    def test_normal_accumulation_and_planned_transitions_leave_no_recovery(self):
        cases = (
            (240, 'heat', {recovery.DM: '-10', engine.REQUIRED: '20'}),
            (60, 'off', {recovery.DM: '-10'}),
            (420, 'heat', {recovery.DM: '-10'}),
            (60, 'heat', {recovery.DM: '-10', engine.PRIORITY: 'Hot water'}),
            (60, 'heat', {recovery.DM: '-10', 'sensor.vp_status': 'Defrosting'}),
        )
        for index, (gap, action, changes) in enumerate(cases):
            with self.subTest(case=index):
                self.setUp()
                if index == 0:
                    self.hass.states.values[recovery.DM] = '-125'
                tracker = recovery.DegreeMinuteRecovery()
                self.observe(tracker, 0.)
                self.assertFalse(self.observe(tracker, gap, action=action, **changes))
                self.assertIsNone(tracker.event)

    def test_warm_room_and_timeout_end_recovery(self):
        for elapsed, changes, status in (
                (60, {engine.ROOM1: '20.5'}, 'Room limit reached'),
                (recovery.RECOVERY_LIMIT, {}, 'Timed out')):
            with self.subTest(status=status):
                self.setUp()
                tracker = recovery.DegreeMinuteRecovery()
                self.observe(tracker, 0.)
                self.assertTrue(self.observe(tracker, 60., **{recovery.DM: '-20'}))
                self.assertTrue(self.observe(tracker, elapsed, **changes))
                self.assertEqual(tracker.event['status'], status)


class ResetDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_survives_reload_respects_write_gate_and_resumes_the_plan(self):
        Store.other = {}
        hass = Fixture()
        hass.time = now = BASE
        Store.saved = {'last_attempt': now - 60, 'last_cycle': now - 60,
                       'c1_direction': -1., 'c1_changed': now - 60}
        hass.states.values.update({engine.C1: '2', engine.ROOM1: '19.8', engine.ROOM2: '19.8',
                                   engine.DHW: 'Economy', engine.SUPPLY: '36', engine.REQUIRED: '32',
                                   recovery.DM: '-565', recovery.FREQUENCY: '60',
                                   'sensor.vp_hot_water_top_bt7': '51',
                                   'sensor.vp_hot_water_charging_bt6': '51'})

        class Predictor:
            options = {}
            last_refresh = now

            async def async_update(self, states, at):
                command = {'start': at, 'end': at + 900, 'offset': 2, 'dhw_mode': 'Economy', 'action': 'heat'}
                return {'generated_at': at, 'model': p.DEFAULTS, 'commands': [command],
                        'steps': [{**command, 'room': 19.8, 'water': 51., 'hz': 60., 'inline_kw': 0.}]}

        predictor = Predictor()
        controller = runtime.Controller(hass, clock=lambda: hass.time, predictor=predictor)
        await controller.async_start()
        hass.time += 60.
        hass.states.values.update({recovery.DM: '2', engine.PRIORITY: 'Off', recovery.FREQUENCY: '0'})
        await controller.async_tick()
        self.assertEqual(hass.calls, [])
        self.assertEqual(Store.saved['degree_minute_recovery']['target_dm'], -565.)
        await controller.async_stop()

        controller = runtime.Controller(hass, clock=lambda: hass.time, predictor=predictor)
        await controller.async_start()
        self.assertEqual(hass.calls, [])
        hass.time = now + 900
        await controller.async_tick()
        self.assertEqual([(c[3]['entity_id'], c[3]['value']) for c in hass.calls], [(engine.C1, 8.)])
        hass.states.values[engine.C1] = '8'
        hass.states.values[recovery.DM] = '-565'
        hass.time = now + 1000
        await controller.async_tick()
        self.assertEqual(Store.saved['degree_minute_recovery']['status'], 'Restored')
        self.assertIsNone(predictor.last_refresh)
        self.assertEqual(len(hass.calls), 1)
        hass.time = now + 1900
        await controller.async_tick()
        self.assertEqual([(c[3]['entity_id'], c[3]['value']) for c in hass.calls], [(engine.C1, 8.), (engine.C1, 2.)])
        self.assertGreaterEqual(hass.calls[1][0] - hass.calls[0][0], 902)
        await controller.async_stop()


if __name__=='__main__':unittest.main()
