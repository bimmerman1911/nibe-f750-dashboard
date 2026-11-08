"""Execute the package's actual Jinja and action tree with HA-shaped state fixtures."""
import copy
import ast
import datetime as dt
import math
import pathlib
import unittest
from types import SimpleNamespace
import yaml
from jinja2.nativetypes import NativeEnvironment

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = yaml.safe_load((ROOT / 'packages/nibe_f750_trial.yaml').read_text())
SEQUENCE = PACKAGE['script']['nibe_smart_control_cycle']['sequence']
C1 = 'number.vp_heating_offset_climate_system_1'
C2 = 'number.vp_heating_offset_climate_system_2'
ENABLED = 'input_boolean.nibe_smart_control_enabled'
READY = 'input_boolean.nibe_smart_control_ready'
LAST = 'input_datetime.nibe_smart_control_last_attempt'
PRICE = 'sensor.nordpool_kwh_se3_sek_3_10_025'


class Halt(Exception):
    pass


class Fixture:
    def __init__(self):
        self.time = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc).timestamp()
        self.states = {ENABLED: 'on', READY: 'on', C1: '0', C2: '0',
                       'sensor.ovanvaning_temperature': '19.2',
                       'sensor.nedervaning_temperature': '18.2',
                       PRICE: '0.8', 'sensor.vp_average_outdoor_temp_bt1': '5',
                       'sensor.vp_supply_line_bt61': '36',
                       'sensor.vp_calculated_supply_climate_system_1': '34',
                       'sensor.vp_priority': 'Heating',
                       'sensor.vp_exhaust_air_bt20': '20', 'select.vp_comfort_mode': 'Economy'}
        self.attrs = {C1: {'min': -10, 'max': 10}, C2: {'min': -10, 'max': 10},
                      'select.vp_comfort_mode': {'options': ['Normal', 'Economy']},
                      PRICE: {'average': 1, 'min': .5, 'max': 2, 'low_price': False}}
        self.calls = []
        self.fail = False
        self.reported = {}
        fixture = self
        class States:
            def __call__(self, e):
                return fixture.states.get(e, 'unknown')
            def __getitem__(self, e):
                return SimpleNamespace(last_reported=fixture.reported.get(e, fixture.time))
        self.env = NativeEnvironment()
        self.env.globals.update(states=States(),
            state_attr=lambda e, k: self.attrs.get(e, {}).get(k),
            has_value=lambda e: self.states.get(e, 'unknown') not in ('unknown', 'unavailable'),
            is_state=lambda e, v: self.states.get(e) == v,
            is_number=lambda v: self.number(v),
            now=lambda: dt.datetime.fromtimestamp(self.time, dt.timezone.utc),
            as_timestamp=self.timestamp)

    @staticmethod
    def number(v):
        try:
            return v is not None and math.isfinite(float(v))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def timestamp(v, default=0):
        if isinstance(v, dt.datetime):
            return v.timestamp()
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    def render(self, value, ctx):
        if isinstance(value, dict):
            return {k: self.render(v, ctx) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render(v, ctx) for v in value]
        if isinstance(value, str) and ('{{' in value or '{%' in value):
            result = self.env.from_string(value).render(**ctx)
            # HA template results strip whitespace before parsing native values.
            if isinstance(result, str):
                result = result.strip()
                try:
                    result = ast.literal_eval(result)
                except (ValueError, SyntaxError):
                    pass
            return result
        return value

    def condition(self, step, ctx):
        if isinstance(step, str):
            return bool(self.render(step, ctx))
        if step['condition'] == 'state':
            return self.states.get(step['entity_id']) == step['state']
        return bool(self.render(step['value_template'], ctx))

    def execute(self, steps, ctx):
        for step in steps:
            if 'condition' in step:
                if not self.condition(step, ctx):
                    raise Halt()
            elif 'variables' in step:
                for k, v in step['variables'].items():
                    ctx[k] = self.render(v, ctx)
            elif 'if' in step:
                if self.condition(step['if'], ctx):
                    self.execute(step['then'], ctx)
            elif 'repeat' in step:
                for item in self.render(step['repeat']['for_each'], ctx):
                    ctx['repeat'] = {'item': item}
                    self.execute(step['repeat']['sequence'], ctx)
            elif 'choose' in step:
                branch = next((b for b in step['choose'] if self.condition(b['conditions'], ctx)), None)
                self.execute(branch['sequence'] if branch else step.get('default', []), ctx)
            elif 'action' in step:
                action = step['action']
                entity = self.render(step['target']['entity_id'], ctx)
                data = self.render(step.get('data', {}), ctx)
                if action == 'input_datetime.set_datetime':
                    self.states[entity] = str(math.floor(float(data['timestamp'])))
                elif action == 'input_boolean.turn_on':
                    for item in entity if isinstance(entity, list) else [entity]:
                        self.states[item] = 'on'
                elif action.startswith('input_number.'):
                    self.states[entity] = str(data['value'])
                else:
                    # The durable reservation must precede every cloud attempt.
                    assert self.time - float(self.states[LAST]) < 1.01
                    self.calls.append((self.time, entity, data))
                    self.time += .6
                    if not self.fail:
                        self.states[entity] = str(data.get('value', data.get('option')))
                    elif not step.get('continue_on_error'):
                        raise RuntimeError('Cloud failure')
            else:
                raise AssertionError(f'Unhandled action: {step}')

    def cycle(self):
        ctx = {}
        try:
            self.execute(SEQUENCE, ctx)
        except Halt:
            pass
        return ctx


class TrialTests(unittest.TestCase):
    def test_c1_leads_and_cold_c1_blocks_c2_increase(self):
        f = Fixture()
        c = f.cycle()
        self.assertEqual(float(c['target_c1']), 20)
        self.assertEqual(float(c['target_c2']), 19)
        self.assertEqual(float(c['next_c1']), 1)
        self.assertEqual(float(c['next_c2']), 0)
        self.assertNotIn(C2, [call[1] for call in f.calls])

    def test_c2_can_increase_when_c1_satisfied_and_can_always_decrease(self):
        f = Fixture()
        f.states['sensor.ovanvaning_temperature'] = '20'
        c = f.cycle()
        self.assertEqual(float(c['next_c2']), 1)
        f = Fixture()
        f.states['sensor.nedervaning_temperature'] = '21'
        self.assertEqual(float(f.cycle()['next_c2']), -1)

    def test_changed_only_and_native_bounds(self):
        f = Fixture()
        f.states.update({C1: '10', 'sensor.nedervaning_temperature': '19', 'select.vp_comfort_mode': 'Normal'})
        f.cycle()
        self.assertEqual(f.calls, [])

    def test_failures_and_reloads_do_not_bypass_rate(self):
        f = Fixture()
        f.fail = True
        f.states['sensor.ovanvaning_temperature'] = '20'
        f.states['sensor.nedervaning_temperature'] = '21'
        f.states[C1] = '2'
        start = f.time
        f.cycle()
        self.assertEqual(len(f.calls), 2)  # C1 unchanged; C2 and DHW attempts fail.
        calls = len(f.calls)
        for elapsed in [1, 60, 899, 901]:
            f.time = start + elapsed
            f.cycle()
            self.assertEqual(len(f.calls), calls)
        # Restored helper state survives a fresh controller instance.
        restored = Fixture()
        restored.states = copy.deepcopy(f.states)
        restored.time = start + 901
        restored.cycle()
        self.assertEqual(restored.calls, [])
        restored.time = start + 963
        restored.cycle()
        self.assertGreater(len(restored.calls), 0)
        self.assertGreaterEqual(restored.calls[0][0] - f.calls[-1][0], 900)

    def test_at_most_three_calls_in_every_rolling_fifteen_minutes(self):
        f = Fixture()
        start = f.time
        for minute in range(65):
            f.time = start + minute * 60
            # Keep all three changes pending to exercise the maximum budget.
            f.states.update({C1: '0', C2: '0', 'select.vp_comfort_mode': 'Economy',
                             'sensor.ovanvaning_temperature': '20.5'})
            f.cycle()
        self.assertEqual(len(f.calls), 15)  # Five batches at 0,16,32,48,64 min.
        for time, _, _ in f.calls:
            self.assertLessEqual(sum(time <= t < time + 900 for t, _, _ in f.calls), 3)

    def test_unknown_room_off_and_startup_gate(self):
        for entity, value in [('sensor.ovanvaning_temperature', 'unavailable'),
                              (C2, 'unknown'), (ENABLED, 'off'), (READY, 'off')]:
            f = Fixture()
            f.states[entity] = value
            f.cycle()
            self.assertEqual(f.calls, [])

    def test_price_outage_uses_comfort_target_and_normal_dhw(self):
        f = Fixture()
        f.states[PRICE] = 'unavailable'
        c = f.cycle()
        self.assertEqual(float(c['target_c1']), 20)
        self.assertEqual(c['next_dhw'], 'Normal')

    def test_stale_and_restored_room_values_stop_writes(self):
        f = Fixture()
        f.reported['sensor.ovanvaning_temperature'] = f.time - 1801
        f.cycle()
        self.assertEqual(f.calls, [])

        f = Fixture()
        f.attrs['sensor.nedervaning_temperature'] = {'restored': True}
        f.cycle()
        self.assertEqual(f.calls, [])

    def test_c2_supply_guard_and_dhw_transition(self):
        for actual, priority in [('31', 'Heating'), ('36', 'Hot water')]:
            f = Fixture()
            f.states.update({'sensor.ovanvaning_temperature': '20',
                             'sensor.vp_supply_line_bt61': actual, 'sensor.vp_priority': priority})
            self.assertEqual(float(f.cycle()['next_c2']), 0)
        f = Fixture()
        f.states['sensor.ovanvaning_temperature'] = '20'
        f.reported['sensor.vp_supply_line_bt61'] = f.time - 1801
        self.assertEqual(float(f.cycle()['next_c2']), 0)

    def test_persistent_shortfall_reduces_only_when_c2_near_target(self):
        f = Fixture()
        f.states.update({'sensor.nedervaning_temperature': '19',
                         'sensor.vp_supply_line_bt61': '31',
                         'binary_sensor.nibe_c1_supply_shortfall': 'on'})
        self.assertEqual(float(f.cycle()['next_c2']), -1)
        f = Fixture()
        f.states['binary_sensor.nibe_c1_supply_shortfall'] = 'on'
        self.assertEqual(float(f.cycle()['next_c2']), 0)  # C2 is already cold.

    def test_shortfall_template_and_telemetry(self):
        f = Fixture()
        guard = next(b['binary_sensor'][0] for b in PACKAGE['template'] if 'binary_sensor' in b)
        self.assertEqual(guard['delay_on'], '00:15:00')
        self.assertFalse(f.render(guard['state'], {}))
        f.states['sensor.vp_supply_line_bt61'] = '31'
        self.assertTrue(f.render(guard['state'], {}))
        f.states['sensor.vp_priority'] = 'Hot water'
        self.assertFalse(f.render(guard['state'], {}))
        telemetry = next(e['attributes']['readings'] for b in PACKAGE['template'] for e in b.get('sensor', []) if e['unique_id'] == 'nibe_control_telemetry')
        readings = f.render(telemetry, {})
        self.assertEqual(readings['sensor.vp_supply_line_bt61']['value'], '31')
        self.assertEqual(readings['sensor.vp_hot_water_top_bt7']['value'], 'unknown')

    def test_dhw_price_rule_and_night_override(self):
        f = Fixture()
        f.states[PRICE] = '2'
        self.assertEqual(f.cycle()['next_dhw'], 'Economy')
        f.time += 11 * 3600
        self.assertEqual(f.cycle()['next_dhw'], 'Normal')

    def test_status_reports_real_cycle_health(self):
        f = Fixture()
        template = PACKAGE['template'][0]['sensor'][0]['state']
        self.assertEqual(f.render(template, {}), 'Waiting for first cycle')
        f.cycle()
        self.assertEqual(f.render(template, {}), 'Running')
        f.time += 1201
        self.assertEqual(f.render(template, {}), 'Controller not responding')
        f.states['sensor.ovanvaning_temperature'] = 'unavailable'
        self.assertEqual(f.render(template, {}), 'Waiting for readings')
        f.states[READY] = 'off'
        self.assertEqual(f.render(template, {}), 'Starting')
        f.states[ENABLED] = 'off'
        self.assertEqual(f.render(template, {}), 'Paused')

    def test_default_enable_once_preserves_later_pause(self):
        f = Fixture()
        f.states[ENABLED] = 'off'
        initialize = PACKAGE['automation'][0]['actions'][:1]
        f.execute(initialize, {})
        self.assertEqual(f.states[ENABLED], 'on')
        f.states[ENABLED] = 'off'
        f.execute(initialize, {})
        self.assertEqual(f.states[ENABLED], 'off')

    def test_serialization_and_restoration_configuration(self):
        self.assertEqual(PACKAGE['script']['nibe_smart_control_cycle']['mode'], 'single')
        for config in PACKAGE['input_datetime'].values():
            self.assertNotIn('initial', config)
        self.assertIs(PACKAGE['input_boolean']['nibe_smart_control_ready']['initial'], False)


if __name__ == '__main__':
    unittest.main()
