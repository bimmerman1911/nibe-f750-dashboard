"""Optional Recorder reconstruction. Runs outside the HA event loop."""
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace
from .accounting import Accounting
from .engine import TELEMETRY


def replay(recorded, start, end, zone, model):
    result=Accounting(zone)
    events=[]
    for entity,states in recorded.items():
        for state in states:
            events.append((max(start,state.last_updated.timestamp()),entity,state))
    events.sort(key=lambda e:e[0])
    current={};index=0;last_activity=None
    cursor=start
    while cursor<=end:
        while index<len(events) and events[index][0]<=cursor:
            time,entity,state=events[index]
            current[entity]=state
            last_activity=time
            forecast=state.attributes.get('forecast')
            if isinstance(forecast,dict) and forecast.get('steps'):
                result.forecast(forecast,time)
            index+=1
        # Recorder records changes, not every unchanged poll. A recorded telemetry
        # heartbeat or recent state event supplies coverage; unavailable/restored
        # values remain invalid. Never extrapolate through a long recording gap.
        if last_activity is not None and cursor-last_activity<=600:
            snapshot={e:SimpleNamespace(entity_id=e,state=s.state,attributes=s.attributes,
                         last_reported=datetime.fromtimestamp(cursor,timezone.utc)) for e,s in current.items()}
            result.observe(snapshot,cursor,model,{})
        else:
            result.previous=result.reference=None
        if cursor==end:
            break
        cursor=min(end,cursor+60)
    result.history_checked=True
    return result


async def backfill(hass, cutoff, zone, model, now=None):
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import get_significant_states
    from homeassistant.helpers import entity_registry as er
    local=datetime.fromtimestamp(now or cutoff,Accounting(zone).zone)
    monday=(local-timedelta(days=local.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    start=min(monday.timestamp(),(now or cutoff)-43200)
    if cutoff<=start:
        return Accounting(zone)
    registry=er.async_get(hass)
    own=[e.entity_id for e in registry.entities.values() if e.platform=='nibe_f750' and e.unique_id in
         ('nibe_f750_forecast','nibe_f750_telemetry')]
    entities=list(set(TELEMETRY)|set(own)|{'sensor.vp_exhaust_air_bt20','sensor.nibe_heating_forecast','sensor.nibe_control_telemetry'})
    recorder=get_instance(hass)
    recorded=await recorder.async_add_executor_job(partial(get_significant_states,hass,
        datetime.fromtimestamp(start,timezone.utc),datetime.fromtimestamp(cutoff,timezone.utc),
        entity_ids=entities,include_start_time_state=True,significant_changes_only=False,
        minimal_response=False,no_attributes=False))
    return await hass.async_add_executor_job(replay,recorded,start,cutoff,zone,model)
