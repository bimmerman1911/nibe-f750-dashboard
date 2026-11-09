"""Read forecasts/prices through HA integrations; no credentials or pump setters."""
from datetime import datetime, timedelta, timezone
from homeassistant.util import dt as dt_util
from .engine import ROOM1, ROOM2, number, fresh, PRICE
from .predictive import prices, timeline, DEFAULTS
from .joint import plan as joint_plan
from .dhw import next_deadline
from .work import PlanningBudget
from zoneinfo import ZoneInfo


class Predictor:
    def __init__(self, hass, options=None):
        self.hass=hass
        self.options=options or {}
        self.last_refresh=None
        self.retry_after=900
        self.adaptive_model={}
        self.learning={}
        self.offset_response={}
        self.command_not_before=0.
        self.result={'status':'Waiting for forecast','message':'Loading prices and hourly weather.', 'steps':[]}

    async def async_update(self, states, now):
        if self.last_refresh is not None and now-self.last_refresh < self.retry_after:
            return self.result
        self.last_refresh=now
        self.retry_after=900
        try:
            candidates=[s for e,s in states.items() if e.startswith('weather.') and s.state not in ('unknown','unavailable')]
            weather_id=self.options.get('weather_entity')
            if not weather_id:
                from homeassistant.helpers import entity_registry as er
                registry=er.async_get(self.hass)
                smhi=[s for s in candidates if (entry:=registry.async_get(s.entity_id)) and entry.platform=='smhi']
                chosen=smhi if smhi else candidates
                if len(chosen)!=1:
                    raise ValueError('Select one hourly weather entity in integration options')
                weather_id=chosen[0].entity_id
            weather=states.get(weather_id)
            if weather is None:
                raise ValueError('Hourly weather entity unavailable')
            response=await self.hass.services.async_call('weather','get_forecasts',
                {'entity_id':weather_id,'type':'hourly'},blocking=True,return_response=True)
            rows=list(response[weather_id]['forecast'])
            unit=weather.attributes.get('temperature_unit')
            if rows:
                from .predictive import timestamp
                if 0<timestamp(rows[0]['datetime'])-now<=5400 and number(weather.attributes.get('temperature')) is not None:
                    rows.insert(0,{'datetime':datetime.fromtimestamp(now,timezone.utc).isoformat(),
                                   'temperature':weather.attributes['temperature']})
            entity=states.get(PRICE)
            attrs=entity.attributes if entity else {}
            unpublished=False
            if attrs.get('raw_today'):
                upcoming=(attrs.get('raw_tomorrow') or []) if attrs.get('tomorrow_valid') is not False else []
                market=prices(list(attrs['raw_today'])+list(upcoming),attrs.get('unit_of_measurement'))
                unpublished=not bool(upcoming)
            else:
                from homeassistant.helpers import entity_registry as er
                registry=er.async_get(self.hass)
                entry=registry.async_get(PRICE)
                config_id=entry.config_entry_id if entry else None
                if not config_id:
                    ids={e.config_entry_id for e in registry.entities.values() if e.platform=='nordpool' and e.config_entry_id}
                    config_id=next(iter(ids)) if len(ids)==1 else None
                if not config_id:
                    raise ValueError('Timestamped Nord Pool prices unavailable or multiple price integrations found')
                date=dt_util.now().date()
                async def fetch(day):
                    r=await self.hass.services.async_call('nordpool','get_prices_for_date',
                      {'config_entry':config_id,'date':day.isoformat(),'areas':['SE3'],'currency':'SEK'},
                      blocking=True,return_response=True)
                    return r['SE3']
                today=await fetch(date)
                try:
                    tomorrow=await fetch(date+timedelta(days=1))
                except Exception:
                    tomorrow=[];unpublished=True
                market=prices(today+tomorrow,'SEK/MWh')
            slots=timeline(market,rows,now,unit)
            required=(ROOM1,ROOM2,'sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6')
            if not all(fresh(states.get(e),now) and number(states[e].state) is not None for e in required):
                raise ValueError('Fresh room and tank readings are needed for predictions')
            room=(float(states[ROOM1].state)+float(states[ROOM2].state))/2
            tank=sum(float(states[e].state) for e in required[2:])/2
            frequency=states.get('sensor.vp_max_compressor_frequency')
            max_hz=number(frequency.state) if frequency and fresh(frequency,now) else None
            if max_hz is None:
                raise ValueError('Fresh reported compressor frequency limit is needed')
            minimum=states.get('sensor.vp_min_compressor_frequency')
            min_hz=number(minimum.state) if minimum and fresh(minimum,now) else 20.
            model={**DEFAULTS, **{k:v for k,v in self.options.items() if k in DEFAULTS}, **self.adaptive_model}
            model['timezone']=getattr(getattr(self.hass,'config',None),'time_zone','Europe/Stockholm')
            local_timezone=ZoneInfo(model['timezone'])
            for slot in slots:
                slot['local_hour']=datetime.fromtimestamp(slot['start'],local_timezone).hour
                slot['dhw_deadline']=slot['start']<next_deadline(slot['start'],model['timezone'])<=slot['end']
            power_limit=states.get('select.vp_set_max_electrical_add')
            try:
                available=float(power_limit.state.lower().replace('kw','').strip()) if fresh(power_limit,now) else 0.
            except (ValueError,AttributeError):
                available=0.
            heater_state=states.get('sensor.vp_int_elec_add_heat')
            if heater_state and heater_state.state=='Blocked':
                available=0.
            model['auxiliary_limit_kw']=min(6.5,max(0.,available))
            model['auxiliary_step_kw']=min(1.,model['auxiliary_limit_kw'])
            priority=states.get('sensor.vp_priority')
            running=states.get('sensor.vp_current_compressor_frequency')
            on=running and fresh(running,now) and (number(running.state) or 0)>0
            model['initial_mode']='dhw' if on and priority and priority.state=='Hot water' else 'heat' if on and priority and priority.state=='Heating' else 'off'
            bt12=states.get('sensor.vp_condenser_bt12')
            if bt12 and fresh(bt12,now) and number(bt12.state) is not None:
                model['dhw_supply_c' if model['initial_mode']=='dhw' else 'supply_c']=float(bt12.state)
            # Pure model evaluation stays off HA's event loop.
            budget=PlanningBudget()
            response=dict(self.offset_response)
            def evaluate():
                return joint_plan(slots,states,now,model,response,min_hz,max_hz,
                    command_not_before=self.command_not_before,budget=budget,
                    emitter=response.get('emitter'))
            try:
                result=await self.hass.async_add_executor_job(evaluate)
            finally:
                # Cancelling an asyncio executor future cannot stop its thread.
                # The worker observes this flag at each search expansion.
                budget.cancelled.set()
            self.retry_after=min(900,max(60,result.get('horizon_end',now+900)-now-30))
            self.result={**result,'generated_at':now,'weather_entity':weather_id,
                         'tomorrow_unavailable':unpublished,'currency':'SEK',
                         'initial_room':room,'initial_water':tank,'learning':self.learning,
                         'price_basis':'Source Nord Pool prices; no extra VAT/add-ons applied.'}
        except Exception as err:
            self.retry_after=120
            # Clear previous recommendations on any source/model failure.
            self.result={'status':'Waiting for forecast','message':str(err),'steps':[], 'generated_at':now}
        return self.result
