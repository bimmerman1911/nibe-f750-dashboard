"""Verify proposed inline windows and the shared cloud-write/approval gates."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from integration_test import Fixture, Store, engine, load, runtime
from joint_scenarios_test import NOW, MODEL, joint, readings, timeline
from runtime_quality_test import Predictor

inline = load('inline')
work = load('work')


class WindowTests(unittest.TestCase):
    def test_compares_cheapest_usable_windows_and_checks_actual_native_draw(self):
        now = NOW
        slots = timeline(now, count=28, price=lambda i: .3 if 4 <= i <= 5 else 2.)
        states = readings(now, room=18.7, tank=52.)
        states['sensor.vp_degree_minutes_2'].state = '-1200'
        states[engine.REQUIRED].state = '44'
        states[engine.C1].state = '0'
        model = {**MODEL, 'room_min_c': 19., 'room_max_c': 21., 'heat_loss_kw_per_k': .18,
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
                'constraint_violation_score': 3., 'inline_kwh': 0.,
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
