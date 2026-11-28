"""Check the empirical SMHI correction and the planner's weather inputs."""
from datetime import datetime, timedelta, timezone
from math import cos, tau
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase, main
from unittest.mock import patch

from integration_test import load
import predictive_test

weather = load('local_weather')
predictor_module = predictive_test.f


def slot_at(when):
    t = datetime.fromisoformat(when).timestamp()
    return {'start': t - 450, 'end': t + 450, 'outdoor': 0.}


class CorrectionTests(TestCase):
    def test_default_cycle_matches_the_supplied_table(self):
        slots = [slot_at(f'2026-11-28T{hour:02}:00:00+01:00') for hour in range(0, 24, 3)]
        settings = weather.correct_outdoor(slots, {})
        self.assertEqual(settings['timezone'], 'Europe/Stockholm')
        self.assertEqual([round(slot['outdoor'], 2) for slot in slots],
                         [-1.78, -1.92, -1.78, -1.45, -1.12, -.98, -1.12, -1.45])
        self.assertTrue(all(slot['outdoor_raw'] == 0. for slot in slots))

    def test_custom_decimal_peak_uses_stockholm_time_in_winter_and_summer(self):
        slots = [slot_at('2026-01-15T13:30:00+00:00'), slot_at('2026-07-15T12:30:00+00:00')]
        weather.correct_outdoor(slots, {'temperature_offset': -2., 'daily_amplitude': .8, 'peak_hour': 14.5})
        for slot in slots:
            self.assertAlmostEqual(slot['outdoor'], -1.2)

    def test_both_occurrences_of_a_repeated_local_hour_get_the_same_correction(self):
        slots = [slot_at('2026-10-25T02:30:00+02:00'), slot_at('2026-10-25T02:30:00+01:00')]
        weather.correct_outdoor(slots, {})
        self.assertEqual(slots[1]['outdoor'], slots[0]['outdoor'])

    def test_invalid_forecast_temperatures_are_skipped_and_valid_zero_is_preserved(self):
        samples = [{'datetime': predictive_test.iso(predictive_test.BASE + i*3600), 'temperature': value}
                   for i, value in enumerate((32, 'unavailable', None, 'NaN', 'inf', 50))]
        self.assertEqual(predictive_test.p.weather_points(samples, '°F'),
                         [(predictive_test.BASE, 0.), (predictive_test.BASE + 5*3600, 10.)])


class ForecastTests(IsolatedAsyncioTestCase):
    async def run_forecast(self, forecast, sensor_value, sensor_age=0, current=0):
        hass, states, calls = predictive_test.SourceTests().make()
        now = predictive_test.BASE
        states['sensor.vp_current_outd_temp_bt1'].state = '-12'
        states['weather.home'].attributes['temperature'] = current
        states[weather.SMHI_TEMPERATURE] = SimpleNamespace(
            state=sensor_value, attributes={'unit_of_measurement': '°C'},
            last_reported=datetime.fromtimestamp(now, timezone.utc) - timedelta(seconds=sensor_age))

        async def get_forecast(domain, service, data, **_kwargs):
            calls.append((domain, service))
            return {'weather.home': {'forecast': forecast}}

        hass.services.async_call = get_forecast
        predictor = predictor_module.Predictor(hass, {'weather_entity': 'weather.home'})

        def plan(slots, *_args, **_kwargs):
            return {'steps': slots, 'horizon_end': slots[-1]['end']}

        with patch.object(predictor_module, 'joint_plan', side_effect=plan) as planner:
            result = await predictor.async_update(states, now)
        self.assertEqual(calls, [('weather', 'get_forecasts')])
        return result, planner.called

    async def test_current_smhi_reading_replaces_the_now_point_and_future_uses_hourly_data(self):
        result, planned = await self.run_forecast(predictive_test.weather(), '8')
        self.assertTrue(planned)
        first, later = result['steps'][0], result['steps'][24]
        self.assertGreater(first['outdoor_raw'], 6.)
        self.assertEqual(later['outdoor_raw'], 0.)
        for step in (first, later):
            local = datetime.fromtimestamp((step['start'] + step['end']) / 2, weather.STOCKHOLM)
            hour = local.hour + local.minute / 60 + local.second / 3600
            self.assertAlmostEqual(step['outdoor'], step['outdoor_raw'] - 1.45 + .47*cos(tau*(hour-15)/24))

    async def test_missing_or_stale_smhi_uses_valid_hourly_data(self):
        for value, age in [('unavailable', 0), ('NaN', 0), ('8', 1900)]:
            with self.subTest(value=value, age=age):
                result, planned = await self.run_forecast(predictive_test.weather(), value, age, current=9)
                self.assertTrue(planned)
                self.assertEqual(result['steps'][0]['outdoor_raw'], 0.)

    async def test_weather_entity_current_temperature_bridges_to_first_future_hour(self):
        result, planned = await self.run_forecast(predictive_test.weather()[2:], 'unknown', current=-3)
        self.assertTrue(planned)
        self.assertLess(result['steps'][0]['outdoor_raw'], -2.5)

    async def test_missing_weather_start_clears_the_schedule(self):
        result, planned = await self.run_forecast(predictive_test.weather()[2:], 'unknown', current=None)
        self.assertFalse(planned)
        self.assertEqual(result['steps'], [])
        self.assertIn('No continuous known-price and weather interval', result['message'])


if __name__ == '__main__':
    main()
