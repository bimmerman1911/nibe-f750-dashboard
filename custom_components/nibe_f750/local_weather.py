"""Calibrate as-issued hourly forecasts against the F750's BT1 readings."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from math import isfinite
from statistics import median

HOUR = 3600
DAY = 24 * HOUR
LEADS = (2, 6, 12, 24)
RETENTION = 42 * DAY
MAX_ERROR = 12.
MAX_CORRECTION = 5.


def temperature(value):
    return type(value) in (int, float) and isfinite(value) and -60 <= value <= 65


def interpolate(points, times, when):
    """Interpolate between forecast points with adequate coverage."""
    i = bisect_left(times, when)
    if i < len(times) and times[i] == when:
        return points[i][1]
    if not 0 < i < len(times) or times[i] - times[i - 1] > 3 * HOUR:
        return None
    start, before = points[i - 1]
    end, after = points[i]
    return before + (after - before) * (when - start) / (end - start)


def _predict(profile, hour, outdoor):
    constant, features = profile
    if features is None:
        return constant
    band_position = (outdoor - 2.5) / 5
    band = int(band_position // 1)
    weight = band_position - band
    expected = (features.get(('hour', hour // 4), 0.)
                + (1 - weight) * features.get(('temperature', band), 0.)
                + weight * features.get(('temperature', band + 1), 0.))
    return _bounded(constant + expected)


def _bounded(value):
    return max(-MAX_CORRECTION, min(MAX_CORRECTION, value))


def _profile(samples):
    # Each valid hour supplies one error per lead. Learn broad hour and
    # temperature bands with shrinkage so a few unusual hours cannot dominate.
    center = _bounded(median(error for _, _, error in samples))
    groups = defaultdict(list)
    for hour, outdoor, error in samples:
        groups['hour', hour // 4].append(error - center)
    features = {key: median(values) * len(values) / (len(values) + 16)
                for key, values in groups.items() if len(values) >= 6}
    groups.clear()
    for hour, outdoor, error in samples:
        groups['temperature', int(outdoor // 5)].append(error - center - features.get(('hour', hour // 4), 0.))
    features.update({key: median(values) * len(values) / (len(values) + 16)
                     for key, values in groups.items() if len(values) >= 6})
    return center, features


class LocalWeather:
    def __init__(self):
        self.source = None
        self.pending = {}
        self.observed = {}
        self.revision = 0
        self.last_report = None
        self._calibration = None

    def dump(self):
        return {
            'source': self.source,
            'pending': [[target, lead, issued, outdoor]
                        for (target, lead), (issued, outdoor) in sorted(self.pending.items())],
            'observed': [[target, lead, outdoor, actual]
                         for (target, lead), (outdoor, actual) in sorted(self.observed.items())],
        }

    def restore(self, data, now):
        if not isinstance(data, dict) or not isinstance(data.get('source'), str):
            return
        pending, observed = {}, {}
        for key, destination in (('pending', pending), ('observed', observed)):
            rows = data.get(key, [])
            if not isinstance(rows, list):
                continue
            for row in rows[-24 * 42 * len(LEADS):]:
                if not isinstance(row, (list, tuple)) or len(row) != 4:
                    continue
                target, lead, first, second = row
                if type(target) is not int or type(lead) is not int or lead not in LEADS:
                    continue
                if key == 'pending':
                    valid = (now - 1200 <= target <= now + 25 * HOUR and type(first) in (int, float)
                             and 0 <= first <= now and 0 < target - first <= 25 * HOUR and temperature(second))
                else:
                    valid = (now - RETENTION <= target <= now and temperature(first)
                             and temperature(second) and abs(first - second) <= MAX_ERROR)
                if valid:
                    destination[target, lead] = first, second
        self.source = data['source']
        self.pending, self.observed = pending, observed
        self.last_report = None
        self._calibration = None

    def record(self, source, points, now):
        """Keep the snapshot closest to each lead, before the outcome exists."""
        if source != self.source:
            self.source = source
            self.pending.clear()
            self.observed.clear()
            self.last_report = None
            self._calibration = None
            self.revision += 1
        for when, outdoor in points:
            target = round(when)
            hours = (target - now) / HOUR
            lead = min(LEADS, key=lambda candidate: abs(candidate - hours))
            if abs(lead - hours) > .75 or not temperature(outdoor):
                continue
            key = target, lead
            current = self.pending.get(key)
            if current is None or abs(lead * HOUR - target + now) < abs(lead * HOUR - target + current[0]):
                self.pending[key] = now, outdoor
                self.revision += 1

    def observe(self, reported_at, actual, now):
        expired = [key for key in self.pending if key[0] < now - HOUR]
        for key in expired:
            del self.pending[key]
        old = [key for key in self.observed if key[0] < now - RETENTION]
        for key in old:
            del self.observed[key]
        if old:
            self._calibration = None
        if expired or old:
            self.revision += 1

        if not (temperature(actual) and reported_at is not None
                and 0 <= now - reported_at <= 1800
                and (self.last_report is None or reported_at > self.last_report)):
            return
        self.last_report = reported_at
        for key, (issued, outdoor) in list(self.pending.items()):
            target, _ = key
            if issued < target <= reported_at <= target + 1200:
                if abs(actual - outdoor) <= MAX_ERROR and key not in self.observed:
                    self.observed[key] = outdoor, actual
                    self._calibration = None
                del self.pending[key]
                self.revision += 1

    def adjust(self, slots, points, measured, now, zone):
        profiles, summary = self.calibrate(now, zone)
        current = interpolate(points, [t for t, _ in points], now)
        anchor = _bounded(measured - current) if measured is not None and current is not None else None
        for slot in slots:
            midpoint = (slot['start'] + slot['end']) / 2
            hours = (midpoint - now) / HOUR
            raw = slot['outdoor']
            bias = correction(profiles, zone, midpoint, raw, hours)
            if anchor is not None:
                weight = max(0., 1 - hours / 2)
                bias = weight * anchor + (1 - weight) * bias
            slot['outdoor_raw'] = raw
            slot['outdoor'] = raw + bias
        return {'active': bool(profiles), 'anchor_c': anchor, 'lead_hours': summary}

    def calibrate(self, now, zone):
        """Select bias corrections using earlier days and recent held-out days."""
        if self._calibration is not None and self._calibration[:2] == (int(now // DAY), zone):
            return self._calibration[2:]
        by_lead = defaultdict(list)
        for (target, lead), (outdoor, actual) in sorted(self.observed.items()):
            if now - RETENTION <= target <= now:
                local = datetime.fromtimestamp(target, zone)
                by_lead[lead].append((local.date().toordinal(), local.hour, outdoor, actual - outdoor))
        profiles, summary = {}, {}
        for lead in LEADS:
            rows = by_lead[lead]
            days = sorted({row[0] for row in rows})
            holdout = set(days[-3:])
            train = [row[1:] for row in rows if row[0] not in holdout]
            verify = [row[1:] for row in rows if row[0] in holdout]
            stats = {'pairs': len(rows), 'days': len(days)}
            summary[str(lead)] = stats
            if len(days) < 6 or len(train) < 48 or len(verify) < 24:
                continue
            constant, features = _profile(train)
            raw_mae = sum(abs(error) for _, _, error in verify) / len(verify)
            stats['raw_mae_c'] = round(raw_mae, 3)
            best_error = raw_mae
            for candidate in ((constant, None), (constant, features)):
                mae = sum(abs(error - _predict(candidate, hour, outdoor))
                          for hour, outdoor, error in verify) / len(verify)
                if mae < best_error - .05:
                    best_error = mae
                    profiles[lead] = candidate
            if lead in profiles:
                stats['corrected_mae_c'] = round(best_error, 3)
                stats['bias_c'] = round(constant, 2)
                stats['uses_patterns'] = profiles[lead][1] is not None
        self._calibration = (int(now // DAY), zone, profiles, summary)
        return profiles, summary


def correction(profiles, zone, when, outdoor, hours):
    if not profiles:
        return 0.
    local = datetime.fromtimestamp(when, zone)
    hour = local.hour
    # Blend feature bands on the chart rather than jumping at their boundaries.
    fraction = (local.minute * 60 + local.second) / HOUR
    def bias(profile):
        before = _predict(profile, hour, outdoor)
        after = _predict(profile, (hour + 1) % 24, outdoor)
        return before + (after - before) * fraction
    biases = {lead: bias(profiles[lead]) if lead in profiles else 0. for lead in LEADS}
    if hours <= LEADS[0]:
        return biases[LEADS[0]]
    for low, high in zip(LEADS, LEADS[1:]):
        if hours <= high:
            return biases[low] + (biases[high] - biases[low]) * (hours - low) / (high - low)
    return biases[LEADS[-1]]
