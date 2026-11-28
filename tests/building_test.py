"""Regression tests for overnight heat balances and defrost-inclusive capacity."""
from dataclasses import replace
from datetime import datetime
import unittest

from integration_test import load
from adaptive_test import states_at
from joint_scenarios_test import joint, readings, timeline, NOW, MODEL

building = load('building')


class BuildingTests(unittest.TestCase):
    def test_sparse_or_milder_cycles_use_the_sustained_fallback(self):
        sample = {'heat_kw': 1.65, 'outside': -2., 'supply': 32.,
                  'flow': 147., 'limit': 71., 'defrost_fraction': .15}
        estimate = building.planning_capacity([sample] * 4, -10., 32., 147., 71., 2.4)
        self.assertEqual(estimate['heat_kw'], 2.)
        self.assertEqual(estimate['source'], 'Provisional sustained output')
        self.assertIsNone(estimate['defrost_minutes_per_hour'])
        self.assertEqual(building.planning_capacity([], -10., 32., 147., 56., 2.4)['heat_kw'], 1.6)
        observed = building.planning_capacity([sample] * 3, -2., 32., 147., 71., 2.4)
        self.assertEqual(observed['heat_kw'], 1.65)
        self.assertEqual(observed['source'], 'Observed defrost cycles')

    def test_provisional_fit_uses_delivered_heat_and_actual_cooling(self):
        model = building.BuildingModel('Europe/Stockholm')
        prior = {'heat_loss_kw_per_k': .1, 'thermal_capacity_kwh_per_k': 9.,
                 'internal_gain_kw': .5}
        for day, (lift, change) in enumerate(((20., -.2), (23., -.7), (25., -1.5)), 1):
            energy = .145 * lift * 9 + 9 * change - .5 * 9
            model.nights.append(building.Night(day, 9., lift * 9, energy, change, change))
        result = model.estimate(NOW, prior)
        self.assertFalse(result['validated'])
        self.assertAlmostEqual(result['provisional_heat_loss_kw_per_k'], .145)
        states = readings(room=19.5, tank=53., q=4.2)
        plan = joint._search(timeline(count=8, outdoor=-7.), states, NOW,
                            {**MODEL, 'building_heat_loss': result}, width=1, strategy='flex')
        self.assertAlmostEqual(plan['model']['heat_loss_kw_per_k'], .145)

    def test_complete_defrost_cycle_counts_lost_heat_and_ramp(self):
        model = building.BuildingModel('Europe/Stockholm')
        reading = building.Reading(NOW, (19., 19.), -7., 2.6, 0., 75., 75.,
                                   145., 34., True, False, False)
        for i in range(101):
            defrost = 5 <= i < 15 or i >= 95
            ramp = 15 <= i < 20
            model.observe(replace(reading, time=NOW + i * 60, defrost=defrost,
                                  heat=0. if defrost else 1. if ramp else 2.6,
                                  frequency=0. if defrost else 32. if ramp else 75.))
        self.assertEqual(len(model.capacity), 1)
        cycle = model.capacity[0]
        self.assertAlmostEqual(cycle.defrost_fraction * 60, 60 * 10 / 90)
        self.assertAlmostEqual(cycle.heat_kw, (75 * 2.6 + 5) / 90)
        restored = building.BuildingModel('Europe/Stockholm')
        restored.restore(model.dump())
        self.assertEqual(restored.capacity, model.capacity)

    def test_overnight_counts_dhw_and_defrost_as_zero_heat(self):
        start = datetime.fromisoformat('2026-11-25T20:00:00+01:00').timestamp()
        model = building.BuildingModel('Europe/Stockholm')
        template = building.Reading(start, (19., 19.), -6., 2.6, 0., 75., 75.,
                                    145., 34., True, False, False)
        for i in range(12 * 60 + 1):
            dhw = 330 <= i < 390
            defrost = 420 <= i < 435
            model.observe(replace(template, time=start + i * 60, dhw=dhw, defrost=defrost,
                                  heat=0. if (dhw or defrost) else 2.6))
        night, = model.nights
        self.assertAlmostEqual(night.hours, 9.)
        self.assertAlmostEqual(night.degree_hours, 225.)
        self.assertAlmostEqual(night.heat_kwh, 2.6 * (9 - 1.25), delta=.08)

    def test_short_dropouts_preserve_night_but_inline_run_excludes_it(self):
        start = datetime.fromisoformat('2026-11-25T20:00:00+01:00').timestamp()
        template = building.Reading(start, (19., 19.), -6., 2.6, 0., 75., 75.,
                                    145., 34., True, False, False)
        for power, expected_nights in ((0., 1), (3., 0)):
            model = building.BuildingModel('Europe/Stockholm')
            for i in range(12 * 60 + 1):
                sample = None if 240 <= i <= 245 else replace(
                    template, time=start + i * 60, inline=power if 350 <= i <= 365 else 0.)
                model.observe(sample)
            self.assertEqual(len(model.nights), expected_nights)

    def test_fits_long_heat_balances_then_validates_cold_nights(self):
        model = building.BuildingModel('Europe/Stockholm')
        prior = {'heat_loss_kw_per_k': .08, 'thermal_capacity_kwh_per_k': 11.}
        for day, (lift, change) in enumerate(zip((13, 23, 17, 24, 20, 28, 30, 26),
                                                  (-.65, .5, 1., -.8, -.2, .45, -.25, -.9)), 1):
            energy = .12 * lift * 9 + 12 * change - .2 * 9
            model.nights.append(building.Night(day, 9., lift * 9, energy, change, change))
        result = model.estimate(NOW, prior)
        self.assertTrue(result['validated'])
        self.assertEqual(result['holdout_nights'], [7, 8])
        self.assertAlmostEqual(result['heat_loss_kw_per_k'], .12, delta=.015)
        self.assertLess(result['holdout_mae_c'], result['baseline_mae_c'])
        # A fit with the wrong sign on the cold nights never becomes active.
        for i in (-2, -1):
            model.nights[i] = replace(model.nights[i], change=-2.)
        self.assertFalse(model.estimate(NOW, prior)['validated'])

    def test_lower_observed_capacity_reduces_forecast_recovery(self):
        states = readings(room=19.5, tank=53., q=4.2)
        slots = timeline(count=12, price=lambda _: 2., outdoor=-7.)
        limited = [{**slot, 'sustained_heat_kw': 1.7} for slot in slots]
        normal = joint._search(slots, states, NOW, MODEL, width=1, strategy='flex')
        constrained = joint._search(limited, states, NOW, MODEL, width=1, strategy='flex')
        self.assertLess(constrained['steps'][-1]['room'], normal['steps'][-1]['room'])
        self.assertAlmostEqual(constrained['planning']['available_building_heat_kw'], 1.7)

    def test_capacity_protection_reverses_an_offset_cut_before_room_minimum(self):
        states = readings(room=18.8, tank=53., q=2.1)
        states[joint.C1].state = '-10'
        states[joint.REQUIRED].state = '22'
        slots = [{**slot, 'sustained_heat_kw': 1.7}
                 for slot in timeline(count=8, price=lambda i: 10. if i < 4 else 1., outdoor=-7.)]
        model = {**MODEL, 'room_min_c': 18.5, 'c1_direction': -1., 'c1_changed': NOW - 600}
        result = joint._search(slots, states, NOW, model, width=1, strategy=-10.)
        command = result['commands'][0]
        self.assertTrue(command['protect_heating_capacity'])
        self.assertGreater(command['offset'], -10)

    def test_sensible_heat_uses_sensor_units_and_excludes_defrost(self):
        states = states_at(NOW, room=19., outdoor=-7., q=3.55)
        for entity, value, unit in ((building.FLOW, 145., 'm³/h'), (building.INLET, 19., '°C'),
                                    (building.OUTLET, -11., '°C'), (building.CONDENSER, 35., '°C'),
                                    (building.STATUS[0], 'Heating', None)):
            states[entity] = replace_simple_state(states[building.BT1], value, unit)
        self.assertAlmostEqual(building.reading(states, NOW).heat, 2.45, delta=.04)
        states[building.STATUS[0]].state = 'Defrosting'
        self.assertEqual(building.reading(states, NOW).heat, 0.)
        states[building.STATUS[0]].state = 'Heating'
        states[building.FLOW].state = 'unknown'
        self.assertIsNone(building.reading(states, NOW).heat)
        self.assertGreater(building.reading(states, NOW, recent_flow=145).heat, 2.)


def replace_simple_state(template, value, unit):
    return type(template)(state=str(value), attributes={'unit_of_measurement': unit},
                          last_reported=template.last_reported)


if __name__ == '__main__':
    unittest.main()
