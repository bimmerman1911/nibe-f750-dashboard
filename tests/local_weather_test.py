"""Verify as-issued forecast scoring, holdout selection and planner inputs."""
from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase, TestCase, main
from unittest.mock import patch
from zoneinfo import ZoneInfo

from integration_test import load, Store
import predictive_test

weather = load('local_weather')
predictor_module = predictive_test.f
BASE = 1795622400
UTC = ZoneInfo('UTC')


def seed(model, bias):
    """Populate eight days of genuinely prior forecasts."""
    for day in range(8):
        for hour in range(24):
            target = BASE + (day * 24 + hour) * 3600
            at = datetime.fromtimestamp(target, UTC).hour
            outdoor = -7.5 if (day + hour) % 2 else 2.5
            actual = outdoor + bias(day, at, outdoor)
            for lead in (24, 12, 6, 2):
                model.record('weather.smhi', [(target, outdoor)], target - lead * 3600)
            model.observe(target + 60, actual, target + 60)
    return BASE + 8 * 86400


class CalibrationTests(TestCase):
    def test_pairs_existing_forecast_only_and_restores(self):
        model = weather.LocalWeather()
        model.record('weather.smhi', [(BASE, -3)], BASE - 2 * 3600 - 300)
        model.record('weather.smhi', [(BASE, -4)], BASE - 2 * 3600)
        model.record('weather.smhi', [(BASE, -10)], BASE + 60)
        model.observe(BASE - 60, -8, BASE + 60)
        self.assertFalse(model.observed)
        restored = weather.LocalWeather()
        restored.restore(model.dump(), BASE + 60)
        restored.observe(BASE + 120, -7, BASE + 120)
        restored.observe(BASE + 360, -3, BASE + 360)
        self.assertEqual(restored.observed, {(BASE, 2): (-4, -7)})
        restored.record('weather.changed', [], BASE + 600)
        self.assertFalse(restored.observed)

    def test_heldout_patterns_distinguish_night_and_cold_weather(self):
        model = weather.LocalWeather()
        now = seed(model, lambda _, hour, outdoor: -.7 - (1.5 if hour < 8 else 0) - (.8 if outdoor < 0 else 0))
        profiles, stats = model.calibrate(now, UTC)
        self.assertEqual(set(profiles), set(weather.LEADS))
        self.assertTrue(stats['12']['uses_patterns'])
        midnight = BASE - BASE % 86400
        noon = midnight + 12 * 3600
        night = midnight + 2 * 3600
        self.assertLess(weather.correction(profiles, UTC, night, -7.5, 12),
                        weather.correction(profiles, UTC, noon, -7.5, 12))
        self.assertLess(weather.correction(profiles, UTC, noon, -7.5, 12),
                        weather.correction(profiles, UTC, noon, 2.5, 12))
        self.assertLess(stats['12']['corrected_mae_c'], stats['12']['raw_mae_c'])
        slots = [{'start': now, 'end': now + 60, 'outdoor': -4.},
                 {'start': now + 6 * 3600, 'end': now + 6 * 3600 + 60, 'outdoor': -4.}]
        model.adjust(slots, [(now, -4), (now + 3600, -4)], -8., now, UTC)
        self.assertAlmostEqual(slots[0]['outdoor'], -8., delta=.03)
        self.assertLess(slots[1]['outdoor'], -4.)
        self.assertEqual(slots[1]['outdoor_raw'], -4.)

    def test_unstable_bias_stays_disabled(self):
        model = weather.LocalWeather()
        now = seed(model, lambda day, *_: -3. if day < 5 else 1.)
        self.assertFalse(model.calibrate(now, UTC)[0])


class ForecastTests(IsolatedAsyncioTestCase):
    async def test_planner_receives_and_returns_local_temperatures(self):
        Store.other = {}
        hass, states, calls = predictive_test.SourceTests().make()
        bt1 = states['sensor.vp_current_outd_temp_bt1']
        bt1.state = '-2'
        predictor = predictor_module.Predictor(hass, {'weather_entity': 'weather.home'})
        seen = []

        def plan(slots, *_args, **_kwargs):
            seen.extend(slots)
            return {'steps': slots, 'horizon_end': slots[-1]['end']}

        now = predictive_test.BASE
        with patch.object(predictor_module, 'joint_plan', side_effect=plan):
            result = await predictor.async_update(states, now)
        self.assertTrue(seen)
        self.assertEqual(calls, [('weather', 'get_forecasts')])
        self.assertEqual(result['steps'][0]['outdoor_raw'], 0.)
        self.assertLess(result['steps'][0]['outdoor'], -1.8)
        self.assertEqual(result['steps'][24]['outdoor'], 0.)
        self.assertEqual(result['local_weather']['anchor_c'], -2.)
        self.assertTrue(Store.other['nibe_f750.local_weather']['pending'])
        # The source's pending forecasts persist before their valid time.
        self.assertTrue(all(row[0] > now for row in Store.other['nibe_f750.local_weather']['pending']))


if __name__ == '__main__':
    main()
