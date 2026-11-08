"""Translate the current planned interval into native, bounded control targets."""
from .engine import C1, ROOM1, ROOM2, fresh, number
from .offset import offset_levels


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
    horizon=[s for s in steps if now <= s['end'] <= now+3600]
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
    # Economy may produce essentially no DHW. Do not count a future charge
    # when checking whether deferral is possible until the next control cycle.
    hold_end=now+1800
    capacity=model.get('tank_capacity_kwh_per_k',.209)
    profile=model.get('dhw_profile')
    deferred=tank
    for slot in steps:
        duration=max(0.,min(slot['end'],hold_end)-max(slot['start'],now))/3600
        if duration:
            draw=profile[slot.get('local_hour',0)] if profile else model.get('dhw_draw_kw',.15)
            deferred-=(draw+.0015*(deferred-20))*duration/capacity
    approaching_charge=any(s['action']=='dhw' and now<=s['start']<hold_end for s in steps)
    low_water=min([tank]+[s['water'] for s in horizon])
    charging=states.get('sensor.vp_priority')
    finish_charge=charging and charging.state=='Hot water' and tank<model['tank_target_c']
    if (current['action']=='dhw' or approaching_charge or finish_charge
        or tank < model['tank_min_c']+2 or deferred < model['tank_min_c']+2
        or low_water < model['tank_min_c']+1):
        dhw='Normal'
        dhw_reason='Charging enabled to build or preserve the hot-water reserve'
        if current['action']=='dhw' or approaching_charge:
            reason='Preparing hot water ahead of demand'
    else:
        dhw='Economy'
        dhw_reason='Charging deferred; stored hot water covers expected demand'
    return {'offset_c1':offset,'target_c':round(desired,2),'dhw':dhw,'action':current['action'],
            'reason':reason,'dhw_reason':dhw_reason,'dhw_action':'Charge enabled' if dhw=='Normal' else 'Deferred','mode':'Adaptive','generated_at':now}
