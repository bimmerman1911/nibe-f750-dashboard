"""Translate the current planned interval into native, bounded control targets."""
from .engine import C1, ROOM1, ROOM2, fresh, number
from .offset import offset_levels
from .dhw import policy


def request(forecast, states, now, model):
    generated = forecast.get('generated_at') if forecast else None
    if generated is None or not 0 <= now-generated <= 1200:
        return None
    steps=forecast.get('steps') or []
    current=next((s for s in steps if s['start'] <= now < s['end']),None)
    if current is None:
        return None
    rooms=[number(states[e].state) if fresh(states.get(e),now) else None for e in (ROOM1,ROOM2)]
    tank_ids=('sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6')
    water=[number(states[e].state) if fresh(states.get(e),now) else None for e in tank_ids]
    if any(v is None for v in rooms+water):
        return None
    tank=sum(water)/2
    lo,hi,target=(model[k] for k in ('room_min_c','room_max_c','room_target_c'))
    offset=number(current.get('offset'))
    if offset is None:
        return None
    degree=states.get('sensor.vp_degree_minutes_2')
    if not fresh(degree,now) or number(degree.state) is None:
        return None
    current_offset=number(states[C1].state) if fresh(states.get(C1),now) else None
    if current_offset is None:
        return None
    # Reconcile a cached plan with actual settings and current room comfort.
    increment=number(states[C1].attributes.get('step')) or 1.
    if min(rooms)<lo:
        offset=max(offset,current_offset+increment)
    elif max(rooms)>hi:
        offset=min(offset,current_offset-increment)
    levels=offset_levels(states[C1])
    if not levels:
        return None
    offset=min(levels,key=lambda v:abs(v-offset))
    desired=target
    reason='Optimising heating offset from prices, weather and delayed heat response'
    charging=states.get('sensor.vp_priority')
    decision=policy(tank,bool(charging and charging.state=='Hot water'),current.get('dhw_mode')=='Normal' if 'dhw_mode' in current else current['action']=='dhw',now,model)
    if decision['dhw']=='Normal':
        reason=decision['dhw_reason']
    return {'offset_c1':offset,'target_c':round(desired,2),**decision,'action':current['action'],
            'reason':reason,'mode':'Adaptive','generated_at':now}
