"""Control policy. No Home Assistant imports or cloud access."""
import math
from .coordination import committed_offset, sustaining_supply_target

C1 = 'number.vp_heating_offset_climate_system_1'
C2 = 'number.vp_heating_offset_climate_system_2'
ROOM1 = 'sensor.ovanvaning_temperature'
ROOM2 = 'sensor.nedervaning_temperature'
SUPPLY = 'sensor.vp_supply_line_bt61'
REQUIRED = 'sensor.vp_calculated_supply_climate_system_1'
C2_SUPPLY = 'sensor.vp_supply_line_ep21_bt2'
C2_REQUIRED = 'sensor.vp_calculated_supply_climate_system_2'
# C1's calculated target drives the primary supply-error/degree-minute model.
# C2's target belongs to its ECS mixing valve, never a second compressor demand.
PRIORITY = 'sensor.vp_priority'
PRICE = 'sensor.nordpool_kwh_se3_sek_3_10_025'
DHW = 'select.vp_comfort_mode'
REQUIRED_READINGS = (ROOM1, ROOM2, C1, C2)
TELEMETRY = (*REQUIRED_READINGS, SUPPLY, REQUIRED, PRIORITY, PRICE, DHW,
 'sensor.vp_return_line_bt62', 'sensor.vp_supply_line_ep21_bt2', 'sensor.vp_return_line_ep21_bt3',
 'sensor.vp_calculated_supply_climate_system_2', 'sensor.vp_degree_minutes_2',
 'sensor.vp_current_outd_temp_bt1', 'sensor.vp_average_outdoor_temp_bt1',
 'sensor.vp_current_compressor_frequency', 'sensor.vp_min_compressor_frequency',
 'sensor.vp_max_compressor_frequency', 'sensor.vp_condenser_bt12',
 'sensor.vp_power_internal_add_heat', 'sensor.vp_int_elec_add_heat',
 'sensor.vp_hot_water_top_bt7', 'sensor.vp_hot_water_charging_bt6',
 'sensor.vp_reference_air_speed_sensor', 'select.vp_set_max_electrical_add', 'select.vp_op_mode')


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def fresh(state, now):
    if not state or state.state in ('unknown', 'unavailable') or state.attributes.get('restored'):
        return False
    reported = getattr(state, 'last_reported', None)
    return reported is not None and -5 <= now - reported.timestamp() <= 1800


def offset_levels(control):
    """Return the native actuator grid, bounded even for invalid metadata."""
    lower, upper = (number(control.attributes.get(k)) for k in ('min', 'max'))
    step = number(control.attributes.get('step', 1.))
    if lower is None or upper is None or step is None or step <= 0 or lower > upper:
        return []
    count = math.floor((upper - lower) / step + 1e-8) + 1
    return [round(lower + i * step, 10) for i in range(count)] if count <= 2048 else []


def capacity_balance(states, now, room_min, room_max, response, compressor_heat_kw):
    """Find a C1 target for a cold secondary room with a fully loaded compressor."""
    if not response or (number(response.get('windows')) or 0) < 6:
        return None
    if not fresh(states.get(PRIORITY), now) or states[PRIORITY].state != 'Heating':
        return None
    for entity in ('sensor.vp_status', 'sensor.vp_status_compressor'):
        status = states.get(entity)
        if fresh(status, now) and any(word in status.state.lower() for word in ('defrost', 'avfrost')):
            return None
    entities = (ROOM1, ROOM2, C1, SUPPLY, REQUIRED, C2_SUPPLY, C2_REQUIRED,
                'sensor.vp_degree_minutes_2', 'sensor.vp_current_compressor_frequency',
                'sensor.vp_max_compressor_frequency', 'sensor.vp_power_internal_add_heat')
    values = [number(states[e].state) if fresh(states.get(e), now) else None for e in entities]
    if None in values:
        return None
    room1, room2, offset, supply, target, secondary_supply, secondary_target, dm, hz, max_hz, inline = values
    if not (5 <= room2 < room_min and room_min + .25 <= room1 <= room_max and room1 - room2 >= .3):
        return None
    if not (20 <= max_hz <= 150 and .9 * max_hz <= hz <= 150 and -3000 <= dm <= -300 and 0 <= inline <= .05):
        return None
    if not (15 <= supply <= 60 and 5 <= secondary_supply <= 60 and 5 <= secondary_target <= 80):
        return None
    if abs(secondary_supply - supply) > 2 or secondary_target - secondary_supply < 1:
        return None
    gain = number(response.get('offset_gain'))
    coefficients = response.get('theta')
    if gain is None or not 0 < gain <= 10 or not isinstance(coefficients, (list, tuple)) or len(coefficients) != 4:
        return None
    theta = [number(x) for x in coefficients]
    capacity = number(compressor_heat_kw)
    if None in theta or capacity is None or capacity <= 0:
        return None
    if not (0 <= theta[0] <= 2 and 0 <= theta[1] <= 2 and 0 <= theta[2] < 1 and -2 <= theta[3] <= 2):
        return None
    # Preserve output up to the currently reported maximum on the same
    # nominal heat basis as the native model. The shunt heat split is unknown.
    needed = sustaining_supply_target(max(supply, secondary_supply), dm, capacity, theta)
    if needed is None or not 15 <= target <= 60:
        return None
    level = next((v for v in offset_levels(states[C1]) if needed <= target + gain * (v - offset)), None)
    if level is None:
        return None
    return {'offset': level, 'target_c': target + gain * (level - offset)}


def calculate(states, now, hour, persistent_shortfall=False, control=None, options=None,
              response=None, compressor_heat_kw=4.2):
    """Return bounded setting requests; release negative coasting if inputs fail."""
    if not all(fresh(states.get(e), now) and number(states[e].state) is not None for e in REQUIRED_READINGS):
        return release_coast(states,now)
    r1, r2, current1, current2 = (number(states[e].state) for e in REQUIRED_READINGS)
    if not 5 <= r1 <= 35 or not 5 <= r2 <= 35:
        return release_coast(states,now)
    def value(entity):
        state = states.get(entity)
        return number(state.state) if state else None
    # Fallback is an ordinary stable thermostat, using the configured preference.
    # A lower comfort minimum is a planning constraint, not a price switch.
    preferred=number((options or {}).get('room_target_c',20.))
    target1=preferred if preferred is not None and 5<=preferred<=35 else 20.
    if control is not None:
        target1 = float(control['target_c'])
    target2 = target1
    e1, e2 = target1-r1, target2-r2
    if control is not None and 'offset_c1' in control:
        next1=control['offset_c1']
        transition=control.get('c1_transition',{})
        next1=committed_offset(next1,current1,transition.get('direction',0),transition.get('time',0),now,
            min(r1,r2)<control.get('room_min_c',19.) or max(r1,r2)>control.get('room_max_c',20.5))
    else:
        error=max(e1,e2)
        next1=max(0.,current1)+min(4.,max(1.,round(3*error))) if error>.3 else current1-1 if e1<-.3 and e2<-.3 else current1
    maximum=number((options or {}).get('room_max_c',max(20.5,target1)))
    if control is None and maximum is not None and max(r1,r2)>maximum:
        next1=min(next1,current1-1)
    minimum = number((control or {}).get('room_min_c', (options or {}).get('room_min_c', 19.)))
    maximum = number((control or {}).get('room_max_c', maximum))
    balance = None
    if minimum is not None and maximum is not None:
        balance = capacity_balance(states, now, minimum, maximum, response, compressor_heat_kw)
    if balance:
        next1 = balance['offset']
    elif (control or {}).get('confirm_capacity_balance'):
        # The planned trim was based on observed saturation. If that evidence
        # disappears, hold the offset unless a measured room limit is breached.
        next1 = current1
        if maximum is not None and max(r1, r2) > maximum:
            next1 -= 1
        elif minimum is not None and min(r1, r2) < minimum:
            next1 += 1
    primary=states[C1]
    lower=number(primary.attributes.get('min'));upper=number(primary.attributes.get('max'))
    if lower is not None and upper is not None:next1=max(lower,min(upper,next1))
    heating = states.get(PRIORITY) and states[PRIORITY].state == 'Heating'
    water_valid = all(fresh(states.get(e), now) for e in (SUPPLY, REQUIRED, PRIORITY))
    water_valid = water_valid and value(SUPPLY) is not None and value(REQUIRED) is not None
    shortfall = bool(heating and water_valid and value(SUPPLY) < value(REQUIRED)-2)
    secondary_warmer = r2 > r1
    secondary=states.get(C2_REQUIRED)
    secondary_target=number(secondary.state) if fresh(secondary,now) else None
    # Freeze upward shunt integration at primary supply saturation. This never
    # reduces the secondary offset merely because that room is colder.
    saturated=bool(balance or (water_valid and secondary_target is not None and secondary_target>=value(SUPPLY)-1.))
    increase = bool(heating and water_valid and not saturated and (not shortfall or not secondary_warmer))
    # This adjusts the native shunt target only. Primary production remains C1.
    next2 = current2 + (-1 if e2 < -.3 or (persistent_shortfall and shortfall and secondary_warmer)
                        else 1 if e2 > .3 and increase else 0)
    # Economy is an intentional DHW deferral preset, not a lower reserve.
    # Only a valid forecast supervisor may defer; fallback restores Normal.
    comfort = control['dhw'] if control is not None else 'Normal'
    candidates = [(C1, next1), (C2, next2), (DHW, comfort)]
    writes = []
    for entity, proposed in candidates:
        state = states.get(entity)
        if not state or state.state in ('unknown', 'unavailable'):
            continue
        if entity == DHW:
            if proposed in state.attributes.get('options', []) and state.state != proposed:
                writes.append((entity, proposed))
        else:
            lo, hi = (number(state.attributes.get(k)) for k in ('min', 'max'))
            if lo is not None and hi is not None and lo <= proposed <= hi and abs(number(state.state)-proposed) > .01:
                writes.append((entity, proposed))
    return {'targets': [target1, target2], 'writes': writes, 'shortfall': shortfall,
            'capacity_balance': balance, 'offset_c1': next1}


def restore_dhw(states):
    """Release deliberate deferral; leave an explicit Lux selection alone."""
    state=states.get(DHW)
    if state and state.state=='Economy' and 'Normal' in state.attributes.get('options',[]):
        return [(DHW,'Normal')]
    return []


def release_coast(states,now):
    # Release deliberate negative offsets even when a room sensor is lost.
    # Use the configured native curve (offset zero), never a stale room value.
    primary=states.get(C1);writes=restore_dhw(states)
    if fresh(primary,now) and number(primary.state) is not None:
        lower=number(primary.attributes.get('min'));upper=number(primary.attributes.get('max'))
        if lower is not None and upper is not None and lower<=0<=upper and float(primary.state)<0:
            writes.insert(0,(C1,0.))
    return {'targets':[], 'writes':writes,'shortfall':False,'fallback_release':True}
