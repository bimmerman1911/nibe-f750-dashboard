"""Learn overnight heat balance and sustained compressor output from myUplink."""
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from math import exp, isfinite, sqrt
from statistics import median
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .air_limit import FLOW, INLET, airflow
from .engine import PRIORITY, ROOM1, ROOM2, SUPPLY, fresh, number
from .predictive import ACTIVE_COMPRESSOR_HEAT_KW

OUTLET = 'sensor.vp_extract_air_bt21'
CONDENSER = 'sensor.vp_condenser_bt12'
BT1 = 'sensor.vp_current_outd_temp_bt1'
FREQUENCY = 'sensor.vp_current_compressor_frequency'
MAXIMUM = 'sensor.vp_max_compressor_frequency'
INLINE = 'sensor.vp_power_internal_add_heat'
DM = 'sensor.vp_degree_minutes_2'
STATUS = ('sensor.vp_status', 'sensor.vp_status_compressor')
IDS = (ROOM1, ROOM2, PRIORITY, SUPPLY, FLOW, INLET, OUTLET, CONDENSER,
       BT1, FREQUENCY, MAXIMUM, INLINE, DM, *STATUS)
TEMPERATURES = (INLET, OUTLET, CONDENSER)
HEARTBEAT = (*TEMPERATURES, FREQUENCY, DM, SUPPLY)
SUSTAINED_COMPRESSOR_HEAT_KW = 2.0
SUSTAINED_REFERENCE_HZ = 70.


@dataclass(frozen=True)
class Reading:
    time: float
    rooms: tuple[float, float]
    outside: float
    heat: float | None
    inline: float
    frequency: float
    limit: float
    flow: float | None
    supply: float
    demand: bool
    defrost: bool
    dhw: bool


def reading(states, now, recent_flow=None):
    def value(entity):
        state = states.get(entity)
        return number(state.state) if fresh(state, now) else None

    rooms = (value(ROOM1), value(ROOM2))
    outside, frequency, limit, supply, minutes, inline = (
        value(entity) for entity in (BT1, FREQUENCY, MAXIMUM, SUPPLY, DM, INLINE)
    )
    priority = states.get(PRIORITY)
    status = [states[entity].state.lower() for entity in STATUS if fresh(states.get(entity), now)]
    if (None in (*rooms, outside, frequency, limit, supply, minutes, inline)
            or not fresh(priority, now) or not status
            or priority.state not in ('Heating', 'Hot water', 'Off')):
        return None
    if not (all(5 <= room <= 35 for room in rooms) and -45 <= outside <= 40
            and 0 <= frequency <= 150 and 20 <= limit <= 150 and 5 <= supply <= 90 and 0 <= inline <= 10):
        return None
    defrost = any('defrost' in state or 'avfrost' in state for state in status)
    dhw = priority.state == 'Hot water'
    flow = airflow(states, now)
    if flow is not None and not 50 <= flow <= 500:
        flow = None
    if flow is None:
        flow = recent_flow
    heat = 0.
    if priority.state == 'Heating' and not defrost and frequency >= 20:
        inlet, outlet, condenser = (value(entity) for entity in TEMPERATURES)
        if (flow is None or None in (inlet, outlet, condenser)
                or any(states[e].attributes.get('unit_of_measurement') not in ('°C', 'C') for e in TEMPERATURES)
                or not (5 <= inlet <= 40 and -35 <= outlet <= 45 and 10 <= condenser <= 80)):
            heat = None
        else:
            sensible = 1.206 * flow / 3600 * max(0., inlet - outlet)
            electric = frequency * (.0161 + .000208 * (condenser - 45))
            heat = sensible + electric
    return Reading(now, rooms, outside, heat, inline, frequency, limit, flow, supply,
                   minutes <= -120, defrost, dhw)


@dataclass(frozen=True)
class Night:
    day: int
    hours: float
    degree_hours: float
    heat_kwh: float
    change: float
    coldest_change: float


@dataclass(frozen=True)
class Capacity:
    end: float
    hours: float
    heat_kw: float
    outside: float
    supply: float
    flow: float
    limit: float
    defrost_fraction: float


def _fit(nights, prior_h, prior_c):
    """Fit Q = H × degree-hours + C × temperature change − gains × hours."""
    lift = [n.degree_hours / n.hours for n in nights]
    center = median(lift)
    rows = [(1., (d - center) / 10., 10. * n.change / n.hours, n.heat_kwh / n.hours)
            for d, n in zip(lift, nights)]
    prior = (prior_h * center, 10. * prior_h, prior_c / 10.)
    penalty = (.04, .12, .18)
    weights = [1.] * len(rows)
    for _ in range(3):
        matrix = [
            [sum(w * r[i] * r[j] for w, r in zip(weights, rows)) + (penalty[i] if i == j else 0.)
             for j in range(3)]
            + [sum(w * r[i] * r[3] for w, r in zip(weights, rows)) + penalty[i] * prior[i]]
            for i in range(3)
        ]
        for i in range(3):
            pivot = max(range(i, 3), key=lambda j: abs(matrix[j][i]))
            matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
            divisor = matrix[i][i]
            matrix[i] = [v / divisor for v in matrix[i]]
            for j in range(3):
                if j != i:
                    factor = matrix[j][i]
                    matrix[j] = [a - factor * b for a, b in zip(matrix[j], matrix[i])]
        base, slope, change = (r[-1] for r in matrix)
        h, c = slope / 10., change * 10.
        gain = h * center - base
        errors = [abs(base + slope * x + change * y - q) for _, x, y, q in rows]
        weights = [min(1., .25 / max(error, 1e-6)) for error in errors]
    if .02 <= h <= .6 and 3 <= c <= 70 and -1.5 <= gain <= 2.5:
        return h, c, gain
    return None


def _temperature_change(night, model):
    loss, thermal_mass, gain = model
    return (night.heat_kwh - loss * night.degree_hours + gain * night.hours) / thermal_mass


def _provisional_loss(nights, baseline):
    """Fit only loss while heat capacity and gains remain provisional."""
    _, mass, gain = baseline
    cold = sorted(nights, key=lambda night: night.degree_hours / night.hours, reverse=True)
    cold = cold[:max(3, min(7, len(cold) // 3))]
    if len(cold) < 3:
        return None

    def fit(rows):
        heat = sum(night.heat_kwh - mass * night.change + gain * night.hours for night in rows)
        return heat / sum(night.degree_hours for night in rows)

    fitted = fit(cold)
    errors = [_temperature_change(night, (fit(cold[:i] + cold[i + 1:]), mass, gain)) - night.change
              for i, night in enumerate(cold)]
    prior_error = sum(abs(_temperature_change(night, baseline) - night.change) for night in cold)
    # Leave each night out in turn and only prefer the refit if it improves the
    # previous model without predicting much more recovery than observed.
    if .01 <= fitted <= 1. and sum(map(abs, errors)) < prior_error and sum(errors) <= .3 * len(cold):
        return fitted
    return None


def capacity_at(samples, outside, supply, flow, limit):
    """Lower-quartile output in comparable complete operating periods."""
    comparable = []
    for sample in samples:
        distance = sqrt(((outside - sample['outside']) / 5.) ** 2
                        + ((supply - sample['supply']) / 8.) ** 2
                        + (((flow or sample['flow']) - sample['flow']) / 35.) ** 2
                        + ((limit - sample['limit']) / 18.) ** 2)
        if (distance <= 2. and abs(outside - sample['outside']) <= 4.
                and abs(supply - sample['supply']) <= 10.
                and (flow is None or abs(flow - sample['flow']) <= 30.)
                and abs(limit - sample['limit']) <= 15.):
            comparable.append((distance, sample))
    neighbors = sorted(comparable, key=lambda pair: pair[0])[:12]
    if not neighbors:
        return None
    closest = neighbors[0][0]
    neighbors = [(distance, sample) for distance, sample in neighbors if distance <= closest + .75]
    weighted = sorted((s['heat_kw'] * min(1., limit / s['limit']), exp(-2 * distance**2))
                      for distance, s in neighbors)
    cutoff = sum(weight for _, weight in weighted) / 4
    for heat, weight in weighted:
        cutoff -= weight
        if cutoff <= 0:
            break
    return {'heat_kw': heat,
            'defrost_minutes_per_hour': 60 * median(s['defrost_fraction'] for _, s in neighbors),
            'periods': len(neighbors), 'nearest_distance': neighbors[0][0]}


def planning_capacity(samples, outside, supply, flow, limit, active_kw):
    """Use comparable cycles, with a defrost-inclusive reference for sparse data."""
    observed = capacity_at(samples, outside, supply, flow, limit)
    if observed and observed['periods'] >= 3 and observed['nearest_distance'] <= 1.:
        return {**observed, 'source': 'Observed defrost cycles'}
    provisional = active_kw * SUSTAINED_COMPRESSOR_HEAT_KW / ACTIVE_COMPRESSOR_HEAT_KW
    return {'heat_kw': provisional * min(1., limit / SUSTAINED_REFERENCE_HZ),
            'defrost_minutes_per_hour': None, 'periods': observed['periods'] if observed else 0,
            'source': 'Provisional sustained output'}


class BuildingModel:
    def __init__(self, zone):
        self.zone = ZoneInfo(zone)
        self.nights = deque(maxlen=45)
        self.capacity = deque(maxlen=96)
        self.history_checked = False
        self.previous = None
        self.missing_since = None
        self.night = None
        self.cycle = None
        self.cycle_from_defrost = False
        self.filtered_heat = None
        self.continuous_hours = 0.
        self.recent_capacity = None
        self.revision = 0

    def dump(self):
        return {'nights': [asdict(n) for n in self.nights], 'capacity': [asdict(c) for c in self.capacity],
                'history_checked': self.history_checked}

    def restore(self, data):
        if not data:
            return
        try:
            nights = [Night(**row) for row in data['nights']]
            capacity = [Capacity(**row) for row in data['capacity']]
            if any(not all(isfinite(v) for v in asdict(row).values()) for row in (*nights, *capacity)):
                return
            if (any(not (0 < n.day and 6 <= n.hours <= 12 and 5 <= n.degree_hours / n.hours <= 65
                         and 0 <= n.heat_kwh <= 8 * n.hours and abs(n.change) <= 4
                         and abs(n.coldest_change) <= 4) for n in nights)
                    or any(not (c.end >= 0 and .3 <= c.hours <= 3.01 and .15 <= c.heat_kw <= 8
                                and -45 <= c.outside <= 40 and 5 <= c.supply <= 90 and 50 <= c.flow <= 500
                                and 20 <= c.limit <= 150 and 0 <= c.defrost_fraction <= .7) for c in capacity)):
                return
            self.nights.extend(nights[-self.nights.maxlen:])
            self.capacity.extend(capacity[-self.capacity.maxlen:])
            self.history_checked = data.get('history_checked') is True
        except (KeyError, TypeError, ValueError):
            return

    def merge(self, history):
        nights = {n.day: n for n in (*history.nights, *self.nights)}
        cycles = {round(c.end / 240): c for c in (*history.capacity, *self.capacity)}
        self.nights.clear()
        self.nights.extend(sorted(nights.values(), key=lambda n: n.day))
        self.capacity.clear()
        self.capacity.extend(sorted(cycles.values(), key=lambda c: c.end))
        self.history_checked = True
        self.revision += 1

    def observe(self, current, disturbed=False):
        if current is None or current.heat is None:
            if disturbed:
                self.night = None
            if self.missing_since is None and self.previous is not None:
                self.missing_since = self.previous.time
            return
        if self.missing_since is not None:
            if current.time - self.missing_since <= 600 and self.previous is not None:
                # Bounded linear integration across short dropouts. Do not
                # infer a complete defrost cycle across a missing status.
                self.cycle = None
            else:
                self.previous = None
                self._finish_night()
                self.cycle = None
            self.missing_since = None
        previous, self.previous = self.previous, current
        if current.heat >= .25 and current.frequency >= .75 * current.limit and not current.defrost:
            heat = current.heat * min(1.2, current.limit / current.frequency)
            self.recent_capacity = (current.time, heat)
        if previous is None or not 30 <= current.time - previous.time <= 600:
            self._finish_night()
            self.cycle = None
            self.continuous_hours = 0.
            self.filtered_heat = current.heat
            return

        hours = (current.time - previous.time) / 3600
        heat = (previous.heat + current.heat) / 2
        self.continuous_hours += hours
        old_heat = previous.heat if self.filtered_heat is None else self.filtered_heat
        self.filtered_heat = heat + (old_heat - heat) * exp(-hours)

        self._capacity(previous, current, hours)
        self._overnight(previous, current, hours, old_heat, disturbed)

    def _overnight(self, previous, current, hours, old_heat, disturbed):
        local = datetime.fromtimestamp(current.time, self.zone)
        day = (local.date() - timedelta(days=local.hour < 12)).toordinal()
        if self.night is not None and (self.night['day'] != day or 7 <= local.hour < 22):
            self._finish_night()
        if 7 <= local.hour < 22 or self.continuous_hours < 1.:
            return
        if (disturbed or max(previous.inline, current.inline) > .05
                or max(abs(a - b) for a, b in zip(previous.rooms, current.rooms)) > .3
                or abs(previous.outside - current.outside) > 3):
            # The balance cannot bridge a large unobserved input or an inline run.
            self.night = None
            return
        room = sum(current.rooms) / 2
        previous_room = sum(previous.rooms) / 2
        lift = (room + previous_room - current.outside - previous.outside) / 2
        if not 5 <= lift <= 65:
            self.night = None
            return
        if self.night is None:
            self.night = {'day': day, 'hours': 0., 'degree_hours': 0., 'heat_kwh': 0.,
                          'start_room': previous_room, 'start_heat': old_heat,
                          'start_coldest': min(previous.rooms)}
        self.night['hours'] += hours
        self.night['degree_hours'] += lift * hours
        self.night['heat_kwh'] += (previous.heat + current.heat) / 2 * hours
        self.night['room'] = room
        self.night['coldest'] = min(current.rooms)
        self.night['end_heat'] = self.filtered_heat

    def _finish_night(self):
        row, self.night = self.night, None
        if row is None or not 6. - 1e-6 <= row['hours'] <= 12.:
            return
        # The one-hour emitter lag contributes its change in stored energy
        # at the boundaries. DHW and defrost already contributed zero input.
        heat = max(0., row['heat_kwh'] + row['start_heat'] - row['end_heat'])
        night = Night(row['day'], row['hours'], row['degree_hours'], heat, row['room'] - row['start_room'],
                      row['coldest'] - row['start_coldest'])
        if ((not self.nights or self.nights[-1].day != night.day)
                and abs(night.change) <= 4 and abs(night.coldest_change) <= 4):
            self.nights.append(night)
            self.revision += 1

    def _capacity(self, previous, current, hours):
        if (current.time - previous.time > 180 or current.flow is None or current.dhw or current.inline > .05
                or previous.flow is None or previous.dhw or previous.inline > .05):
            self.cycle = None
            return
        defrost_start = current.defrost and not previous.defrost
        if not current.demand and not current.defrost and not (self.cycle_from_defrost and self.cycle):
            self.cycle = None
            return
        if self.cycle is None:
            if current.defrost and not defrost_start:
                return
            self.cycle = {'hours': 0., 'heat': 0., 'outside': 0., 'supply': 0., 'flow': 0.,
                          'limit': 0., 'defrost': 0., 'at_capacity': 0., 'demand': 0.}
            self.cycle_from_defrost = defrost_start
        cycle = self.cycle
        # Use the earlier state for each elapsed interval including on/off edges.
        if defrost_start and not cycle['hours']:
            return
        cycle['hours'] += hours
        for key in ('heat', 'outside', 'supply', 'flow', 'limit', 'defrost'):
            cycle[key] += hours * getattr(previous, key)
        cycle['at_capacity'] += hours * (not previous.defrost and previous.frequency >= .85 * previous.limit)
        cycle['demand'] += hours * (previous.demand or previous.defrost)
        if defrost_start:
            if self.cycle_from_defrost:
                self._finish_cycle(current.time)
            self.cycle = dict.fromkeys(cycle, 0.)
            self.cycle_from_defrost = True
        elif not self.cycle_from_defrost and cycle['hours'] >= 2. - 1e-6:
            self._finish_cycle(current.time)
            self.cycle = None
        elif cycle['hours'] > 3.:
            self.cycle = None

    def _finish_cycle(self, end):
        cycle = self.cycle
        hours = cycle['hours']
        if (hours < .3 or cycle['at_capacity'] < .60 * (hours - cycle['defrost'])
                or cycle['demand'] < .75 * hours):
            return
        heat = cycle['heat'] / hours
        defrost = cycle['defrost'] / hours
        if .15 <= heat <= 8 and defrost <= .7:
            self.capacity.append(Capacity(end, hours, heat, *(cycle[k] / hours for k in
                                          ('outside', 'supply', 'flow', 'limit')), defrost))
            self.revision += 1

    def estimate(self, now, prior):
        nights = list(self.nights)
        capacities = [asdict(c) for c in self.capacity if 0 <= now - c.end <= 21 * 86400]
        result = {'nights': len(nights), 'capacity_periods': len(capacities),
                  'capacity_samples': capacities, 'validated': False,
                  'effective_heat_loss_kw_per_k': prior['heat_loss_kw_per_k'],
                  'stored_heat_kw': self.filtered_heat if self.continuous_hours >= 1. and not self.missing_since else None,
                  'source': 'Airflow and sensible heat plus compressor power estimate'}
        if self.recent_capacity and 0 <= now - self.recent_capacity[0] <= 7200:
            result['recent_heating_kw'] = self.recent_capacity[1]
        h = prior['heat_loss_kw_per_k']
        c = prior['thermal_capacity_kwh_per_k']
        baseline = (h, c, prior.get('internal_gain_kw', 0.))
        provisional = _provisional_loss(nights, baseline)
        if provisional is not None:
            result.update({'provisional_heat_loss_kw_per_k': provisional,
                           'effective_heat_loss_kw_per_k': provisional})
        if len(nights) < 6:
            return result
        # Keep the latest two nights near the cold end of the observed range
        # out of fitting entirely. Check both total error and optimism.
        cold = sorted(nights, key=lambda n: n.degree_hours / n.hours)[len(nights) // 2:]
        verify = sorted(cold, key=lambda n: n.day)[-2:]
        train = [n for n in nights if n not in verify]
        lifts = [n.degree_hours / n.hours for n in train]
        result['training_lift_span_c'] = max(lifts) - min(lifts)
        if max(lifts) - min(lifts) < 3. or max(n.change / n.hours for n in train) - min(n.change / n.hours for n in train) < .06:
            return result
        fitted = _fit(train, h, c)
        if fitted is None:
            return result
        errors = [_temperature_change(n, fitted) - n.change for n in verify]
        baseline_errors = [_temperature_change(n, baseline) - n.change for n in verify]
        mae = sum(map(abs, errors)) / len(errors)
        bias = sum(errors) / len(errors)
        baseline_mae = sum(map(abs, baseline_errors)) / len(baseline_errors)
        result.update({'holdout_nights': [n.day for n in verify], 'holdout_mae_c': mae,
                       'baseline_mae_c': baseline_mae, 'holdout_bias_c': bias,
                       'holdout_coldest_room_change_c': [n.coldest_change for n in verify]})
        if mae <= min(.55, baseline_mae + .05) and max(errors) <= .50 and bias <= .25:
            loss, thermal_mass, gain = fitted
            result.pop('provisional_heat_loss_kw_per_k', None)
            result.update({'validated': True, 'heat_loss_kw_per_k': loss,
                           'effective_heat_loss_kw_per_k': loss,
                           'thermal_capacity_kwh_per_k': thermal_mass, 'internal_gain_kw': gain,
                           'observed_lift_c': [min(lifts), max(lifts)]})
        return result


def replay(recorded, start, end, zone):
    model = BuildingModel(zone)
    events = sorted(((max(start, state.last_updated.timestamp()), entity, state)
                     for entity, states in recorded.items() for state in states), key=lambda row: row[0])
    snapshot = {}
    index = 0
    updated = None
    recent_flow = None
    room_history = deque()
    for now in range(int(start) + 60, int(end) + 1, 60):
        while index < len(events) and events[index][0] <= now:
            timestamp, entity, state = events[index]
            snapshot[entity] = state
            if entity in HEARTBEAT:
                updated = timestamp
            index += 1
        # Recorder emits changes rather than every poll. Require a heat-pump
        # heartbeat; a long gap ends both the heat balance and the cycle.
        if updated is None or now - updated > 360:
            room_history.clear()
            model.observe(None)
            continue
        reported = datetime.fromtimestamp(now, timezone.utc)
        states = {e: SimpleNamespace(state=s.state, attributes=s.attributes, last_reported=reported)
                  for e, s in snapshot.items()}
        flow = airflow(states, now)
        if flow is not None and 50 <= flow <= 500:
            recent_flow = (now, flow)
        cached = recent_flow[1] if recent_flow is not None and now - recent_flow[0] <= 7200 else None
        sample = reading(states, now, cached)
        if sample is None:
            room_history.clear()
        while room_history and now - room_history[0][0] > 1800:
            room_history.popleft()
        disturbed = bool(sample and room_history and any(
            room - earlier > .55 for room, earlier in zip(sample.rooms, room_history[0][1])))
        if sample:
            room_history.append((now, sample.rooms))
        model.observe(sample, disturbed)
    model._finish_night()
    return model


async def backfill(hass, end, zone):
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import get_significant_states

    start = end - 9 * 86400
    recorder = get_instance(hass)
    recorded = await recorder.async_add_executor_job(partial(get_significant_states, hass,
        datetime.fromtimestamp(start, timezone.utc), datetime.fromtimestamp(end, timezone.utc),
        entity_ids=list(IDS), include_start_time_state=True, significant_changes_only=False,
        minimal_response=False, no_attributes=False))
    return await hass.async_add_executor_job(replay, recorded, start, end, zone)
