"""Control policy. No Home Assistant imports or cloud access."""
import math

C1 = 'number.vp_heating_offset_climate_system_1'
C2 = 'number.vp_heating_offset_climate_system_2'
ROOM1 = 'sensor.ovanvaning_temperature'
ROOM2 = 'sensor.nedervaning_temperature'
SUPPLY = 'sensor.vp_supply_line_bt61'
REQUIRED = 'sensor.vp_calculated_supply_climate_system_1'
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


def calculate(states, now, hour, persistent_shortfall=False, control=None):
    """Return targets and at most three setting requests, or None for missing data."""
    if not all(fresh(states.get(e), now) and number(states[e].state) is not None for e in REQUIRED_READINGS):
        return None
    r1, r2, current1, current2 = (number(states[e].state) for e in REQUIRED_READINGS)
    if not 5 <= r1 <= 35 or not 5 <= r2 <= 35:
        return None
    def value(entity):
        state = states.get(entity)
        return number(state.state) if state else None
    p = value(PRICE)
    outside = value('sensor.vp_average_outdoor_temp_bt1')
    extract = value('sensor.vp_exhaust_air_bt20')
    attrs = states[PRICE].attributes if states.get(PRICE) else {}
    target1 = 20 if (None in (p, outside, extract) or attrs.get('low_price') is True
                     or p < 1.5 or outside < 2 or extract < 18) else 19
    if control is not None:
        target1 = float(control['target_c'])
    target2 = min(math.ceil(r2), target1)
    e1, e2 = target1-r1, target2-r2
    next1 = current1 + (1 if e1 > .3 else -1 if e1 < -.3 else 0)
    heating = states.get(PRIORITY) and states[PRIORITY].state == 'Heating'
    water_valid = all(fresh(states.get(e), now) for e in (SUPPLY, REQUIRED, PRIORITY))
    water_valid = water_valid and value(SUPPLY) is not None and value(REQUIRED) is not None
    shortfall = bool(heating and water_valid and value(SUPPLY) < value(REQUIRED)-2)
    increase = bool(heating and water_valid and not shortfall and e1 <= .3)
    next2 = current2 + (-1 if e2 < -.3 or (persistent_shortfall and shortfall and e2 <= .3)
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
    return {'targets': [target1, target2], 'writes': writes, 'shortfall': shortfall}


def restore_dhw(states):
    """Release deliberate deferral; leave an explicit Lux selection alone."""
    state=states.get(DHW)
    if state and state.state=='Economy' and 'Normal' in state.attributes.get('options',[]):
        return [(DHW,'Normal')]
    return []
