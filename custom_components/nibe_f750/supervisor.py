"""Translate the current planned interval into native, bounded control targets."""
from .engine import ROOM1, ROOM2, fresh, number


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
    # Measured room comfort overrides a coast segment; average forecasts cannot
    # justify allowing the colder room to drift below its own minimum.
    if min(rooms) < lo+.3:
        desired=target
        reason='Restoring indoor comfort'
    elif max(rooms) > hi:
        desired=lo
        reason='Letting stored warmth cover demand'
    elif current['action']=='heat':
        predicted=max([target]+[s['room'] for s in horizon])
        desired=min(hi,max(target,predicted+.2))
        reason='Heating ahead of future demand and prices'
    else:
        desired=lo
        reason='Using stored warmth while heating is deferred'
    low_water=min([tank]+[s['water'] for s in horizon])
    if current['action']=='dhw' or tank < model['tank_min_c']+2 or low_water < model['tank_min_c']+1:
        dhw='Normal'
        if current['action']=='dhw':
            reason='Preparing hot water ahead of demand'
    else:
        dhw='Economy'
    return {'target_c':round(desired,2),'dhw':dhw,'action':current['action'],
            'reason':reason,'mode':'Adaptive','generated_at':now}
