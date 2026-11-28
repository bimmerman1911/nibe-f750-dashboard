"""Estimate BT1 from SMHI temperatures using the daily empirical correction."""
from datetime import datetime
from math import cos, tau
from zoneinfo import ZoneInfo

from .engine import fresh
from .predictive import numeric, temperature_c

SMHI_TEMPERATURE = 'sensor.utetemperatur_smhi'
STOCKHOLM = ZoneInfo('Europe/Stockholm')
DEFAULT_CORRECTION = {'temperature_offset': -1.45, 'daily_amplitude': 0.47, 'peak_hour': 15.0}


def anchor_smhi(points, states, weather, now):
    """Use the current SMHI observation and keep the hourly forecast ahead."""
    if not points or points[0][0] > now + 5400:
        return points
    sensor = states.get(SMHI_TEMPERATURE)
    if fresh(sensor, now):
        current = temperature_c(sensor.state, sensor.attributes.get('unit_of_measurement', '°C'))
        if current is not None:
            return [(now, current), *(point for point in points if point[0] > now)]

    # When the observation is missing, use an existing forecast bracket or
    # bridge to the first hour with the weather entity's current temperature.
    if points[0][0] > now and fresh(weather, now):
        current = temperature_c(weather.attributes.get('temperature'), weather.attributes.get('temperature_unit'))
        if current is not None:
            return [(now, current), *points]
    return points


def correct_outdoor(slots, options):
    """Apply the Stockholm-local correction at each interval's midpoint."""
    settings = {key: numeric(options.get(key, default)) for key, default in DEFAULT_CORRECTION.items()}
    offset, amplitude, peak_hour = (settings[key] for key in ('temperature_offset', 'daily_amplitude', 'peak_hour'))
    for slot in slots:
        local = datetime.fromtimestamp((slot['start'] + slot['end']) / 2, STOCKHOLM)
        hour = local.hour + local.minute / 60 + (local.second + local.microsecond / 1_000_000) / 3600
        slot['outdoor_raw'] = slot['outdoor']
        slot['outdoor'] += offset + amplitude * cos(tau * (hour - peak_hour) / 24)
    return {'active': bool(slots), 'model': 'SMHI-to-BT1 cosine', 'timezone': STOCKHOLM.key, **settings}
