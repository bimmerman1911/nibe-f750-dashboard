"""Verify proposed inline windows and the shared cloud-write/approval gates."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from integration_test import Fixture, Store, engine, load, runtime
from joint_scenarios_test import NOW, MODEL, joint, readings, timeline
from runtime_quality_test import Predictor

inline = load('inline')
work = load('work')


class WindowTests(unittest.TestCase):
    def test_night_request_timing_uses_local_clock_across_dst(self):
        zone = ZoneInfo('Europe/Stockholm')
        def at(value):
            return datetime.fromisoformat(value).replace(tzinfo=zone).timestamp()
        start = at('2026-03-29T06:30')
        for value, expected in (('2026-03-28T21:44', False), ('2026-03-28T21:45', True),
                                ('2026-03-28T22:00', False), ('2026-03-29T05:59', False),
                                ('2026-03-29T06:00', True)):
            self.assertEqual(inline.request_due(at(value), start, zone), expected, value)

    def test_compares_cheapest_usable_windows_and_checks_actual_native_draw(self):
        now = NOW
        slots = timeline(now, count=28, price=lambda i: .3 if 4 <= i <= 5 else 2.)
        states = readings(now, room=18.7, tank=52.)
        states['sensor.vp_degree_minutes_2'].state = '-1200'
        states[engine.REQUIRED].state = '44'
        states[engine.C1].state = '0'
        model = {**MODEL, 'room_min_c': 19., 'room_max_c': 21., 'heat_loss_kw_per_k': .22,
                 'heating_lag_hours': .5, 'dhw_morning_completed': True}
        response = {'theta': [.5,.5,.2,1.]}
        commands = {'commands': [{'start': now, 'end': slots[-1]['end'], 'offset': 0, 'dhw_mode': 'Economy'}]}
        base = joint._search(slots, states, now, model, response, strategy='previous', incumbent=commands)

        def replay(trial, kw):
            result = joint._search(trial, states, now, {**model, 'auxiliary_limit_kw': kw}, response,
                                   strategy='previous', incumbent=base)
            self.assertTrue(all(r['inline_kw']==0 for r in result['steps'] if not r['inline_allowed']))
            self.assertTrue(all(0 <= r['inline_kw'] <= 6.5 + 1e-8 for r in result['steps']))
            return result

        self.assertEqual(next(inline.candidate_windows(slots, base, now, now, slots[-1]['end'])),
                         (now+3600, now+4560))
        plan = inline.compare_windows(slots, base, now, now, 6.5, replay, work.PlanningBudget(10))
        self.assertIsNotNone(plan)
        for window in plan['windows']:
            self.assertGreater(window['estimated_kwh'], 0)
            duration_hours = (window['end'] - window['start']) / 3600
            self.assertLessEqual(window['estimated_kwh'], 6.5 * duration_hours + 1e-8)
        result = replay(list(inline.trial_slots(slots, [(w['start'], w['end']) for w in plan['windows']])), 6.5)
        self.assertLess(result['constraint_violation_score'], base['constraint_violation_score'])

    def test_does_not_offer_for_a_small_comfort_simulation_error(self):
        base = {'model': {'room_min_c': 19., 'tank_min_c': 42.}, 'morning_shortfall': 0.,
                'constraint_violation_score': .001, 'steps': [{'room1': 18.99, 'room2': 19.1, 'water': 45}]}
        self.assertIsNone(inline.compare_windows([], base, NOW, NOW, 6.5, None, work.PlanningBudget()))

    def test_cumulative_plan_covers_distant_cheap_quarters_within_visible_horizon(self):
        cheap = (2, 3, 28, 50)
        slots = timeline(NOW, count=60, price=lambda i: .1 if i in cheap else 10.)
        base = {'model': {'room_min_c': 19., 'tank_min_c': 42.}, 'morning_shortfall': 0.,
                'constraint_violation_score': 3., 'inline_kwh': 0., 'model_cost': 0.,
                'steps': [{'end': NOW + 900, 'room1': 18.5, 'room2': 19.1, 'water': 45}]}
        def replay(trial, kw):
            steps = [{**s, 'inline_kw': kw if s['inline_allowed'] and s['price'] == .1 else 0.}
                     for s in trial]
            energy = sum(s['inline_kw'] * s['dt'] for s in steps)
            cost = sum(s['inline_kw'] * s['dt'] * s['price'] for s in steps)
            return {**base, 'steps': [{**s, **base['steps'][0], 'end': s['end']} for s in steps],
                    'inline_kwh': energy, 'model_cost': cost,
                    'constraint_violation_score': max(0., 3 - energy / (kw * .25))}

        result = inline.compare_windows(slots, base, NOW, NOW, 6.5, replay, work.PlanningBudget(10))
        self.assertEqual(result['horizon_end'], NOW + 12 * 3600)
        self.assertEqual([(w['start'], w['end']) for w in result['windows']],
                         [(NOW+1800, NOW+3660), (NOW+25200, NOW+26160)])
        preferred = inline.compare_windows(slots, base, NOW+4000, NOW+4000, 6.5, replay,
                                           work.PlanningBudget(10), preferred=result)
        self.assertEqual(preferred['windows'], result['windows'][1:])

    def test_adjacent_cheap_quarters_beat_a_pricier_spaced_run(self):
        prices = {2: 2., 3: 2.2, 7: 3.}
        slots = timeline(NOW, count=16, price=lambda i: prices.get(i, 10.))
        base = {'model': {'room_min_c': 19., 'tank_min_c': 42., 'response_uncertainty_c': .10},
                'morning_shortfall': 0., 'constraint_violation_score': 1., 'inline_kwh': 0., 'model_cost': 5.,
                'steps': [{'end': NOW+900, 'room1': 18.5, 'room2': 19.1, 'water': 45}]}

        def replay(trial, kw):
            steps = [{**s, 'inline_kw': kw if s['inline_allowed'] and s['price'] < 10. else 0.}
                     for s in trial]
            energy = sum(s['inline_kw'] * s['dt'] for s in steps)
            cost = sum(s['inline_kw'] * s['dt'] * s['price'] for s in steps)
            rms = .25 - min(2., energy) * .09
            return {**base, 'steps': [{**s, 'room1': 18.5, 'room2': 19.1, 'water': 45.} for s in steps],
                    'inline_kwh': energy, 'model_cost': 5. + cost,
                    'constraint_violation_score': rms*rms*4,
                    'recovery': {'rms_deficit_c': rms, 'worst_deficit_c': .5, 'end_deficit_c': rms,
                                 'last_deficit_hours': 4., 'morning_shortfall_c': 0.}}

        result = inline.compare_windows(slots, base, NOW, NOW, 4., replay, work.PlanningBudget(10))
        self.assertEqual([(w['start'], w['end']) for w in result['windows']], [(NOW+1800, NOW+3660)])
        self.assertAlmostEqual(sum(w['estimated_cost'] for w in result['windows']), 4.2)

    def test_optional_heat_cannot_set_its_own_earlier_recovery_deadline(self):
        slots = timeline(NOW, count=56)
        base = {'model': {'room_min_c': 19., 'tank_min_c': 42.}, 'morning_shortfall': 0.,
                'constraint_violation_score': 1., 'inline_kwh': 0., 'model_cost': 78.,
                'recovery': {'rms_deficit_c': .31, 'worst_deficit_c': .55, 'end_deficit_c': 0.,
                             'last_deficit_hours': 13.5, 'morning_shortfall_c': 0.},
                'steps': [{'end': NOW+900, 'room1': 18.5, 'room2': 19.1, 'water': 49}]}
        def replay(trial, kw):
            steps = [{**s, 'room1': 18.5, 'room2': 19.1, 'water': 49.,
                      'inline_kw': 1. if s['inline_allowed'] else 0.} for s in trial]
            return {**base, 'steps': steps, 'model_cost': 81., 'constraint_violation_score': .9,
                    'inline_kwh': sum(s['inline_kw'] * s['dt'] for s in steps),
                    'recovery': {**base['recovery'], 'rms_deficit_c': .30, 'last_deficit_hours': 12.}}

        self.assertIsNone(inline.compare_windows(slots, base, NOW, NOW, 6.5, replay, work.PlanningBudget(10)))
        offered = {'windows': [{'start': NOW+1800, 'end': NOW+2760, 'kw': 6.5}], 'horizon_end': NOW+43200}
        self.assertIsNone(inline.compare_windows(slots, base, NOW, NOW, 6.5, replay,
                                                work.PlanningBudget(10), preferred=offered))

    def test_unmet_recovery_tests_a_late_cheap_quarter_on_its_own(self):
        late = NOW+3*3600
        slots = timeline(NOW, count=24, price=lambda i: 1. if i == 12 else 4.)
        base = {'model': {'room_min_c': 19., 'tank_min_c': 42.}, 'morning_shortfall': 0.,
                'constraint_violation_score': 1., 'inline_kwh': 0., 'model_cost': 10.,
                'recovery': {'rms_deficit_c': .31, 'worst_deficit_c': .55, 'end_deficit_c': .29,
                             'last_deficit_hours': 6., 'morning_shortfall_c': 0.},
                'steps': [{'end': NOW+900, 'room1': 18.5, 'room2': 19.1, 'water': 49}]}
        def replay(trial, kw):
            steps = [{**s, 'room1': 18.5, 'room2': 19.1, 'water': 49.,
                      'inline_kw': 1. if s['inline_allowed'] else 0.} for s in trial]
            return {**base, 'steps': steps, 'constraint_violation_score': .5,
                    'inline_kwh': sum(s['inline_kw'] * s['dt'] for s in steps),
                    'model_cost': 10. + sum(s['inline_kw'] * s['dt'] * s['price'] for s in steps),
                    'recovery': {**base['recovery'], 'rms_deficit_c': .20, 'end_deficit_c': 0.,
                                 'last_deficit_hours': 5.}}

        result = inline.compare_windows(slots, base, NOW, NOW, 6.5, replay, work.PlanningBudget(10))
        self.assertEqual([(w['start'], w['end']) for w in result['windows']], [(late, late+960)])


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Store.saved = None
        Store.other = {}
        self.hass = Fixture()
        self.hass.time = NOW
        self.cap = '0.0 kw'
        self.notifications = []
        self.cap_writes = []
        self.reject_cap = False
        self.clock = lambda: self.hass.time
        self.predictor = Predictor({'inline_notify_service': 'mobile_app_test', 'inline_max_kw': 6.5})
        self.controller = runtime.Controller(self.hass, clock=self.clock, predictor=self.predictor)
        self.controller.inline_approval_entity = 'button.nibe_inline_approval'
        self.offer = {'start': NOW+1200, 'end': NOW+2160, 'kw': 6.5, 'estimated_cost': 1.23}
        self.later = {'start': NOW+4800, 'end': NOW+5760, 'kw': 6.5, 'estimated_cost': .65}
        self.plan = {'windows': [self.offer, self.later], 'horizon_end': NOW+43200}
        self.publish(NOW)
        self.hass.services.has_service = lambda domain, service: (domain, service)==('notify','mobile_app_test')

        async def call(domain, service, data, blocking):
            if domain == 'notify':
                self.notifications.append(data)
                return
            assert Store.saved['inline_restore']
            assert Store.saved['last_attempt'] == self.hass.time
            self.cap_writes.append(data['option'])
            if self.reject_cap:
                raise RuntimeError('Native write failed')
            self.cap = data['option']

        self.hass.services.async_call = call

    def states(self):
        reported = datetime.fromtimestamp(self.hass.time, timezone.utc)
        def state(value, **attributes):
            return SimpleNamespace(state=value, attributes=attributes, last_reported=reported)
        return {
            inline.CAP_ENTITY: state(self.cap, options=['0.0 kw','6.50 kw']),
            inline.STATUS_ENTITY: state('Blocked' if self.cap == '0.0 kw' else 'Active'),
            engine.PRIORITY: state('Heating'),
            engine.ROOM1: state('19.1'),
            engine.ROOM2: state('18.9'),
            'sensor.vp_degree_minutes_2': state('-800'),
        }

    async def ask(self):
        await self.controller._offer_inline(self.hass.time)
        return self.notifications[-1]['data']['actions']

    async def answer(self, action):
        await self.controller._inline_response(SimpleNamespace(data={'action':action}))

    async def tick(self, at):
        self.hass.time = at
        await self.controller._inline_tick(self.states(), at)

    def publish(self, at, plan=None):
        self.controller.forecast = {'inline_plan': self.plan if plan is None else plan, 'generated_at': at}

    async def test_one_approval_covers_two_runs_and_both_return_to_zero(self):
        actions = await self.ask()
        self.assertEqual(actions[0]['title'], 'Approve plan')
        self.assertIn('1.88 SEK total', self.notifications[0]['message'])
        await self.controller._offer_inline(NOW+30)
        self.assertEqual(len(self.notifications), 1)
        await self.answer('NIBE_INLINE_APPROVE_wrong')
        self.assertFalse(self.controller.inline.approved)
        await self.answer(actions[0]['action'])
        await self.tick(self.offer['start']-1)
        self.assertEqual(self.cap_writes, [])
        await self.tick(self.offer['start'])
        self.assertEqual(self.cap_writes, ['6.50 kw'])
        self.assertTrue(Store.saved['inline_restore'])
        await self.tick(self.offer['start']+900)
        self.assertEqual(self.cap_writes, ['6.50 kw'])
        await self.tick(self.offer['end'])
        self.assertEqual(self.cap_writes, ['6.50 kw','0.0 kw'])
        self.assertTrue(Store.saved['inline_restore'])
        await self.tick(self.offer['end']+60)
        self.assertFalse(Store.saved['inline_restore'])
        self.assertTrue(self.controller.inline.approved)
        self.publish(self.later['start']-60, {**self.plan, 'windows': [self.later]})
        await self.controller._offer_inline(self.later['start']-60)
        await self.tick(self.later['start'])
        await self.tick(self.later['end'])
        await self.tick(self.later['end']+60)
        self.assertEqual(self.cap_writes, ['6.50 kw','0.0 kw','6.50 kw','0.0 kw'])
        self.assertEqual(len(self.notifications), 1)

    async def test_tap_links_to_current_plan_and_local_approval_shares_deadline(self):
        self.controller.inline_approval_entity = 'button.renamed_nibe_approval'
        await self.ask()
        notification, = self.notifications
        self.assertIn('Press and hold for actions or tap to review', notification['message'])
        self.assertEqual(notification['data']['url'], '/?more-info-entity-id=button.renamed_nibe_approval')
        self.assertEqual(notification['data']['clickAction'], notification['data']['url'])
        self.assertTrue(self.controller.inline_approval_pending)
        self.assertTrue(await self.controller.async_respond_inline(approve_current=True))
        self.assertTrue(Store.saved['inline_request']['approved'])
        self.assertFalse(await self.controller.async_respond_inline(approve_current=True))

    async def test_disabling_requests_invalidates_offer_without_hiding_estimate(self):
        actions = await self.ask()
        async def no_tick():
            pass
        self.controller.async_tick = no_tick
        await self.controller.async_enable_inline_requests(False)
        await self.answer(actions[0]['action'])
        self.assertFalse(await self.controller.async_respond_inline(approve_current=True))
        self.assertFalse(Store.saved['inline_requests_enabled'])
        self.assertIsNone(Store.saved['inline_request']['offer'])
        await self.controller._offer_inline(NOW+30)
        self.assertEqual(len(self.notifications), 1)
        self.assertEqual(self.controller._inline_status()['state'], 'Requests blocked')
        self.assertEqual(self.controller._latest_inline_plan(NOW), self.plan)
        await self.tick(self.offer['start'])
        self.assertEqual(self.cap_writes, [])

    async def test_disabled_switch_survives_restart_and_requires_a_new_approval(self):
        actions = await self.ask()
        async def no_tick():
            pass
        self.controller.async_tick = no_tick
        await self.controller.async_enable_inline_requests(False)
        self.hass.bus = SimpleNamespace(async_listen=lambda *_: lambda: None)
        restored = runtime.Controller(self.hass, clock=self.clock, predictor=self.predictor)
        restored.async_tick = no_tick
        restored.inline_approval_entity = self.controller.inline_approval_entity
        await restored.async_start()
        self.controller = restored
        self.publish(NOW)
        self.assertFalse(restored.inline_requests_allowed)
        await restored._offer_inline(NOW)
        self.assertEqual(len(self.notifications), 1)
        await restored.async_enable_inline_requests(True)
        fresh_actions = await self.ask()
        self.assertNotEqual(actions[0]['action'], fresh_actions[0]['action'])
        await self.answer(actions[0]['action'])
        self.assertFalse(restored.inline.approved)
        await self.answer(fresh_actions[0]['action'])
        self.assertTrue(restored.inline.approved)

    async def test_disabling_during_active_run_preserves_write_spacing_and_restores_zero(self):
        actions = await self.ask()
        await self.answer(actions[0]['action'])
        await self.tick(self.offer['start'])
        async def no_tick():
            pass
        self.controller.async_tick = no_tick
        await self.controller.async_enable_inline_requests(False)
        self.assertTrue(Store.saved['inline_restore'])
        await self.tick(self.offer['start']+900)
        self.assertEqual(self.cap_writes, ['6.50 kw'])
        await self.tick(self.offer['start']+902)
        self.assertEqual(self.cap_writes, ['6.50 kw', '0.0 kw'])

    async def test_late_reply_defaults_to_off(self):
        actions = await self.ask()
        self.hass.time = self.offer['start']
        await self.answer(actions[0]['action'])
        await self.tick(self.offer['start'])
        self.assertEqual(self.cap_writes, [])
        self.assertIsNone(self.controller.inline.offer)
        self.assertEqual(self.controller.inline.closed_until, self.plan['horizon_end'])
        self.publish(self.later['start']-1800, {**self.plan, 'windows': [self.later]})
        await self.controller._offer_inline(self.later['start']-1800)
        await self.tick(self.later['start'])
        self.assertEqual(len(self.notifications), 1)
        self.assertEqual(self.cap_writes, [])

    async def test_decline_and_modified_offer_do_not_reuse_approval(self):
        actions = await self.ask()
        await self.answer(actions[1]['action'])
        await self.tick(self.offer['start'])
        self.assertEqual(self.cap_writes, [])
        self.assertIsNone(self.controller.inline.offer)
        self.controller.inline.closed_until = 0
        self.hass.time = NOW
        actions = await self.ask()
        await self.answer(actions[0]['action'])
        changed = {**self.offer, 'end': self.offer['end']+900}
        self.publish(NOW+60, {**self.plan, 'windows': [changed, self.later]})
        await self.controller._offer_inline(NOW+60)
        await self.tick(self.offer['start'])
        self.assertEqual(self.cap_writes, [])
        self.publish(self.later['start']-60, {**self.plan, 'windows': [self.later]})
        await self.tick(self.later['start'])
        self.assertEqual(self.cap_writes, ['6.50 kw'])

    async def test_requests_only_in_hour_before_first_window(self):
        later_plan = {**self.plan, 'windows': [self.later]}
        self.publish(NOW, later_plan)
        await self.controller._offer_inline(NOW)
        self.assertEqual(self.notifications, [])
        await self.controller._offer_inline(self.later['start']-3600)
        self.assertEqual(len(self.notifications), 1)

    async def test_night_request_covers_the_plan_and_decline_keeps_the_estimate(self):
        zone = self.controller.accounting.zone
        def at(value):
            return datetime.fromisoformat(value).replace(tzinfo=zone).timestamp()
        now = at('2026-11-09T21:45')
        first = {**self.offer, 'start': at('2026-11-10T02:00'), 'end': at('2026-11-10T02:16')}
        second = {**self.later, 'start': at('2026-11-10T06:30'), 'end': at('2026-11-10T06:46')}
        plan = {'windows': [first, second], 'horizon_end': now+43200}
        self.hass.time = now
        self.publish(now, plan)
        actions = await self.ask()
        self.assertIn('02:00', self.notifications[0]['message'])
        self.assertIn('06:30', self.notifications[0]['message'])
        await self.answer(actions[1]['action'])
        self.assertEqual(self.controller._inline_status()['state'], 'Not approved')
        self.publish(first['start']-60, plan)
        await self.tick(first['start'])
        self.assertEqual(self.controller._latest_inline_plan(first['start']), plan)
        self.assertEqual(self.cap_writes, [])
        self.publish(second['start']-1800, plan)
        await self.controller._offer_inline(second['start']-1800)
        self.assertEqual(len(self.notifications), 1)

    async def test_new_need_during_quiet_hours_only_offers_still_future_windows_at_six(self):
        zone = self.controller.accounting.zone
        def at(value):
            return datetime.fromisoformat('2026-11-10T'+value).replace(tzinfo=zone).timestamp()
        first = {**self.offer, 'start': at('05:30'), 'end': at('05:46')}
        second = {**self.later, 'start': at('06:30'), 'end': at('06:46')}
        plan = {'windows': [first, second], 'horizon_end': at('15:30')}
        self.hass.time = at('05:00')
        self.publish(self.hass.time, plan)
        await self.controller._offer_inline(self.hass.time)
        self.assertEqual(self.notifications, [])
        await self.tick(first['start'])
        self.assertEqual(self.cap_writes, [])
        self.hass.time = at('06:00')
        self.publish(self.hass.time, plan)
        await self.ask()
        self.assertEqual(self.controller.inline.offer['windows'], [second])

    async def test_persistence_that_crosses_ten_does_not_send(self):
        zone = self.controller.accounting.zone
        now = datetime(2026, 11, 9, 21, 59, 50, tzinfo=zone).timestamp()
        self.hass.time = now
        window = {**self.offer, 'start': now+7200, 'end': now+8160}
        self.publish(now, {'windows': [window], 'horizon_end': now+43200})
        save = self.controller._save_inline_request
        async def delay_save():
            self.hass.time += 15
            await save()
        self.controller._save_inline_request = delay_save
        await self.controller._offer_inline(now)
        self.assertEqual(self.notifications, [])
        self.assertIsNone(Store.saved['inline_request']['offer'])

    async def test_restart_preserves_the_phone_reply_for_the_remaining_windows(self):
        actions = await self.ask()
        saved = Store.saved['inline_request']
        self.controller.inline = inline.Approval()
        self.controller.inline.restore(saved, 'mobile_app_test', NOW+60)
        await self.answer(actions[0]['action'])
        await self.tick(self.offer['start'])
        await self.tick(self.offer['end'])
        await self.tick(self.offer['end']+60)
        saved = Store.saved['inline_request']
        self.controller.inline = inline.Approval()
        self.controller.inline.restore(saved, 'mobile_app_test', self.hass.time)
        self.publish(self.later['start']-60)
        await self.tick(self.later['start'])
        self.assertEqual(self.cap_writes, ['6.50 kw','0.0 kw','6.50 kw'])
        self.assertEqual(len(self.notifications), 1)

    async def test_restart_closes_an_ambiguous_write_at_first_permitted_tick(self):
        actions = await self.ask()
        await self.answer(actions[0]['action'])
        self.reject_cap = True
        with self.assertLogs(runtime._LOGGER, level='ERROR'):
            await self.tick(self.offer['start'])
        self.assertTrue(Store.saved['inline_restore'])
        self.reject_cap = False
        restored = runtime.Controller(self.hass, clock=self.clock, predictor=Predictor())
        restored.data.update(Store.saved)
        self.controller = restored
        await self.tick(self.offer['start']+900)
        self.assertEqual(self.cap_writes, ['6.50 kw'])
        await self.tick(self.offer['start']+902)
        self.assertEqual(self.cap_writes, ['6.50 kw','0.0 kw'])
        await self.tick(self.offer['start']+960)
        self.assertFalse(Store.saved['inline_restore'])


if __name__=='__main__':
    unittest.main()
