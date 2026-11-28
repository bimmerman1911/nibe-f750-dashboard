"""Persistent, serialized controller using HA's built-in myUplink setters."""
import asyncio
from datetime import datetime, timedelta
import logging
import time

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from .adaptive import ThermalLearner
from .building import BuildingModel, backfill as backfill_building, reading as building_reading
from .offset import OffsetLearner
from .accounting import Accounting
from .degree_recovery import DegreeMinuteRecovery
from .predictive import DEFAULTS, active_compressor_heat
from .supervisor import request as adaptive_request
from .engine import restore_dhw, calculate, fresh, number, C1, SUPPLY, REQUIRED, PRIORITY, ROOM1, ROOM2, TELEMETRY
from .inline import (Approval, CAP_ENTITY, EVENT, MIN_LEAD, START_GRACE,
                     WRITE_INTERVAL, power_option, request_due, supports_window)

_LOGGER = logging.getLogger(__name__)
DOMAIN = 'nibe_f750'


class Controller:
    def __init__(self, hass, clock=time.time, predictor=None):
        self.hass = hass
        self.clock = clock
        self.store = Store(hass, 1, DOMAIN + '.control')
        self.forecast_store = Store(hass, 1, DOMAIN + '.predictions')
        self.learning_store = Store(hass, 1, DOMAIN + '.learning')
        self.accounting_store = Store(hass, 1, DOMAIN + '.accounting')
        self.accounting = Accounting(getattr(getattr(hass,'config',None),'time_zone','Europe/Stockholm'))
        self.costs = {}
        self.last_accounting_save = 0
        self.air_history_task = None
        self.history_task = None
        self.building_history_task = None
        self.data = {'enabled': True, 'last_cycle': 0, 'last_attempt': 0, 'c1_direction':0., 'c1_changed':0., 'release_dhw':False,'dhw_morning_pending':False,'dhw_morning_completed_date':None}
        self.status = 'Starting'
        self.targets = []
        self.telemetry = {}
        self.short_since = None
        self.lock = asyncio.Lock()
        self.listeners = set()
        self.stopping = False
        self.unsubscribe = None
        self.last_sample = 0
        self.write_failed = False
        self.predictor = predictor
        self.forecast = {}
        self.prediction_log = []
        self.last_prediction = None
        self.decision_log = []
        options = getattr(predictor, 'options', {})
        # The native offset response uses its existing nominal units. The
        # room learner takes estimated space heat in physical kW.
        self.native_heat_kw = options.get('compressor_heat_kw', DEFAULTS['compressor_heat_kw'])
        self.thermal_options = {**options, 'compressor_heat_kw': active_compressor_heat(options)}
        self.learner = ThermalLearner(self.thermal_options)
        self.building = BuildingModel(str(self.accounting.zone))
        self.saved_learning_revision = 0
        self.offset_learner = OffsetLearner()
        self.offset_store = Store(hass,1,DOMAIN+'.offset_response')
        self.control = {'mode':'Thermostat fallback','reason':'Waiting for prices and weather.'}
        self.inline = Approval()
        self.inline_service = getattr(predictor, 'options', {}).get('inline_notify_service', '')
        self.inline_approval_entity = None
        self.inline_active_until = None
        self.unsubscribe_inline = None
        self.data['inline_restore'] = False
        self.data['inline_zero_requested'] = None
        self.data['inline_request'] = None
        self.data['inline_requests_enabled'] = True
        self.degree_recovery = DegreeMinuteRecovery()
        self.data['degree_minute_recovery'] = None

    async def async_start(self):
        self.accounting.restore(await self.accounting_store.async_load())
        self.offset_learner.restore(await self.offset_store.async_load())
        learning = await self.learning_store.async_load()
        if learning and not self.learner.restore(learning, self.native_heat_kw):
            _LOGGER.warning('Invalid adaptive model data; restarting learning from initial parameters')
        self.building.restore((learning or {}).get('building'))
        if self.predictor:
            history = await self.forecast_store.async_load() or {}
            self.prediction_log = history.get('records', [])[-192:]
            self.decision_log = history.get('decisions', [])[-512:]
        restored = await self.store.async_load()
        if restored:
            self.data.update({k: restored[k] for k in self.data if k in restored})
            if 'release_dhw' not in restored and not self.data['enabled']:
                self.data['release_dhw'] = True
        # Reject corrupt persistent gates rather than silently resetting a budget.
        if type(self.data['enabled']) is not bool or type(self.data['release_dhw']) is not bool or any(number(self.data[k]) is None for k in ('last_cycle', 'last_attempt','c1_direction','c1_changed')) or self.data['c1_direction'] not in (-1.,0.,1.) or self.data['c1_changed']<0:
            raise ValueError('Invalid persisted controller state')
        self.data['inline_requests_enabled'] = self.data['inline_requests_enabled'] is True
        self.degree_recovery.restore(self.data['degree_minute_recovery'])
        if self.inline_service:
            if self.inline_requests_allowed:
                self.inline.restore(self.data['inline_request'], self.inline_service, self.clock())
            self.unsubscribe_inline = self.hass.bus.async_listen(EVENT, self._inline_response)
        self.unsubscribe = async_track_time_interval(self.hass, self.async_tick, timedelta(minutes=1))
        await self.async_tick()
        if (not self.building.history_checked and 'recorder' in getattr(getattr(self.hass, 'config', None), 'components', set())
                and hasattr(self.hass, 'async_create_background_task')):
            self.building_history_task = self.hass.async_create_background_task(
                self.async_backfill_building(), 'NIBE overnight heat and defrost history')
        if ((not self.offset_learner.air_limit.observations or not self.offset_learner.air_limit.last_airflow) and 'recorder' in getattr(getattr(self.hass,'config',None),'components',set()) and hasattr(self.hass,'async_create_background_task')):
            self.air_history_task=self.hass.async_create_background_task(self.async_backfill_air_limit(),'NIBE evaporator calibration history')
        if (not self.accounting.history_checked and 'recorder' in getattr(getattr(self.hass,'config',None),'components',set())
            and hasattr(self.hass,'async_create_background_task')):
            cutoff=min([self.accounting.previous['time'] if self.accounting.previous else self.clock()]+[r.get('observed_start',t) for t,r in self.accounting.bins.items() if r.get('seconds')])
            self.history_task=self.hass.async_create_background_task(self.async_backfill_accounting(cutoff),'NIBE electricity history')

    async def async_backfill_air_limit(self):
        try:
            from .air_limit import backfill,AirLimit
            data=await backfill(self.hass,self.clock())
            restored=AirLimit()
            if not restored.restore(data):return
            async with self.lock:
                if self.stopping:return
                live=self.offset_learner.air_limit
                unique={int(r['time']//600):r for r in restored.observations+live.observations}
                live.observations=sorted(unique.values(),key=lambda r:r['time'])[-9:]
                if restored.sustained and 0<=self.clock()-restored.sustained['time']<=86400 and (not live.sustained or self.clock()-live.sustained['time']>86400 or restored.sustained['hz']>live.sustained['hz']):live.sustained=restored.sustained
                if restored.last_airflow and (not live.last_airflow or restored.last_airflow['time']>live.last_airflow['time']):live.last_airflow=restored.last_airflow
                await self.offset_store.async_save(self.offset_learner.dump())
                if self.predictor:self.predictor.last_refresh=None
                self.notify()
        except Exception:
            _LOGGER.exception('Evaporator history unavailable; calibration continues from live observations')

    async def async_backfill_building(self):
        building = self.building
        try:
            history = await backfill_building(self.hass, self.clock(), str(building.zone))
            async with self.lock:
                if self.stopping or self.building is not building:
                    return
                building.merge(history)
                await self.learning_store.async_save({**self.learner.dump(), 'building': building.dump()})
                if self.predictor:
                    self.predictor.last_refresh = None
                self.notify()
        except Exception:
            _LOGGER.exception('Building heat history unavailable; learning continues from live observations')

    async def async_backfill_accounting(self, cutoff):
        try:
            from .history import backfill
            restored=await backfill(self.hass,cutoff,str(self.accounting.zone),
                {**self.learner.prior,**self.learner.parameters()},now=self.clock())
            async with self.lock:
                if self.stopping:
                    return
                self.accounting.merge_history(restored,cutoff)
                self.costs=self.accounting.view(self.clock())
                await self.accounting_store.async_save(self.accounting.dump())
                self.notify()
        except Exception:
            _LOGGER.exception('Recorder backfill unavailable; recording new electricity history normally')

    def notify(self):
        for callback in tuple(self.listeners):
            callback()

    async def async_enable(self, enabled):
        # Apply pause immediately, including between writes in an active batch.
        self.data['enabled'] = enabled
        self.data['release_dhw'] = not enabled
        async with self.lock:
            if not enabled:
                self.inline.clear()
                self.inline_active_until = None
                self.data['inline_request'] = self.inline.dump(self.inline_service)
                if self.degree_recovery.finish('Paused', self.clock()):
                    self.data['degree_minute_recovery'] = self.degree_recovery.event
            await self.store.async_save(dict(self.data))
        await self.async_tick()

    @property
    def inline_requests_allowed(self):
        return self.data['enabled'] and self.data['inline_requests_enabled'] and not self.stopping

    @property
    def inline_approval_pending(self):
        return bool(self.inline_service and self.inline_requests_allowed and self.inline.token
                    and self.inline.offer and self.clock() < self.inline.offer['windows'][0]['start'])

    async def async_enable_inline_requests(self, enabled):
        # Stop new grants while an existing controller cycle yields.
        if not enabled:
            self.data['inline_requests_enabled'] = False
        async with self.lock:
            self.data['inline_requests_enabled'] = enabled
            if not enabled:
                self.inline.clear()
                self.inline_active_until = None
            await self._save_inline_request()
            self.control['inline_approval'] = self._inline_status()
            self.notify()
        await self.async_tick()

    async def async_reset_learning(self):
        async with self.lock:
            self.learner = ThermalLearner(self.thermal_options)
            self.building = BuildingModel(str(self.accounting.zone))
            self.building.history_checked = True
            await self.learning_store.async_save({**self.learner.dump(), 'building': self.building.dump()})
            self.saved_learning_revision = 0
            self.offset_learner = OffsetLearner()
            await self.offset_store.async_save(self.offset_learner.dump())
            if self.predictor:
                self.predictor.last_refresh = None
        await self.async_tick()

    async def async_stop(self):
        self.stopping = True
        if self.building_history_task and not self.building_history_task.done():
            self.building_history_task.cancel()
            try:
                await self.building_history_task
            except asyncio.CancelledError:
                pass
        if self.air_history_task and not self.air_history_task.done():
            self.air_history_task.cancel()
            try:await self.air_history_task
            except asyncio.CancelledError:pass
        if self.history_task and not self.history_task.done():
            self.history_task.cancel()
            try:
                await self.history_task
            except asyncio.CancelledError:
                pass
        if self.unsubscribe:
            self.unsubscribe()
        if self.unsubscribe_inline:
            self.unsubscribe_inline()
        async with self.lock:
            await self.store.async_save(dict(self.data))
            await self.accounting_store.async_save(self.accounting.dump())

    async def async_tick(self, _now=None):
        if self.stopping or self.lock.locked():
            return
        async with self.lock:
            try:
                await self._cycle()
            except Exception:
                self.status = 'Controller error'
                _LOGGER.exception('NIBE controller cycle failed; no immediate retry')
            finally:
                self.notify()

    async def _cycle(self):
        now = self.clock()
        states = {s.entity_id: s for s in self.hass.states.async_all()}
        if self.hass.services.has_service('script', 'nibe_smart_control_cycle'):
            self.status = 'Legacy backend detected'
            return
        options = getattr(self.predictor, 'options', {}) if self.predictor else {}
        bounds = {k: options.get(k, DEFAULTS[k]) for k in ('room_min_c', 'room_target_c', 'room_max_c')}
        if self.degree_recovery.observe(states, now, self.data['enabled'], self.control.get('action'), bounds['room_max_c']):
            self.data['degree_minute_recovery'] = self.degree_recovery.event
            await self.store.async_save(dict(self.data))
            if self.predictor and not self.degree_recovery.active:
                self.predictor.last_refresh = None
        hold_inline_writes = await self._inline_tick(states, now)
        if now-self.last_sample >= 300:
            self.telemetry = {e: {'value': states[e].state if e in states else 'unknown',
                'unit': states[e].attributes.get('unit_of_measurement') if e in states else None,
                'reported_at': states[e].last_reported.isoformat() if e in states else None} for e in TELEMETRY}
            self.last_sample = now
        try:
            temporary_before = self.learner.temporary_heat.active
            saved_flow = self.offset_learner.air_limit.last_airflow
            recent_flow = saved_flow['flow'] if saved_flow and 0 <= now - saved_flow['time'] <= 7200 else None
            measured_heat = building_reading(states, now, recent_flow)
            self.learner.update(states, now, dt_util.now().hour,
                                observed_heat_kw=measured_heat.heat if measured_heat else None)
            building_revision = self.building.revision
            self.building.observe(measured_heat, self.learner.temporary_heat.learning_hold)
            if self.predictor and self.building.revision != building_revision:
                self.predictor.last_refresh = None
            if self.predictor and temporary_before != self.learner.temporary_heat.active:
                self.predictor.last_refresh = None
            revision=self.offset_learner.revision
            self.offset_learner.update(states,now,self.native_heat_kw,
                                       learn_emitter=not self.learner.temporary_heat.learning_hold)
            if revision!=self.offset_learner.revision:
                await self.offset_store.async_save(self.offset_learner.dump())
            if self.learner.revision != self.saved_learning_revision or self.building.revision != building_revision:
                await self.learning_store.async_save({**self.learner.dump(), 'building': self.building.dump()})
                self.saved_learning_revision = self.learner.revision
        except Exception:
            _LOGGER.exception('Adaptive learning update failed; retaining the last working model')
        await self._observe_morning_completion(states,now)
        if self.predictor and not hold_inline_writes:
            try:
                learned = self.learner.parameters()
                building = self.building.estimate(now, learned)
                self.predictor.adaptive_model = {**learned, 'building_heat_loss': building,'c1_direction':self.data['c1_direction'],'c1_changed':self.data['c1_changed'],'dhw_morning_pending':self.data['dhw_morning_pending'],'dhw_morning_completed':self._morning_completed(now)}
                self.predictor.learning = self.learner.diagnostics()
                self.predictor.offset_response = self.offset_learner.parameters()
                self.predictor.air_limit = self.offset_learner.air_limit
                self.predictor.inline_offer = self.inline.offer
                self.predictor.inline_used_until = self.inline.used_until
                self.predictor.command_not_before = max(now,float(self.data['last_cycle'])+902,float(self.data['last_attempt'])+902)
                self.forecast = await asyncio.wait_for(self.predictor.async_update(states, now), timeout=30)
                generated = self.forecast.get('generated_at')
                if generated is not None and generated != self.last_prediction:
                    self.accounting.forecast(self.forecast,now)
                    self.last_prediction = generated
                    record={k:self.forecast.get(k) for k in ('generated_at','status','message','initial_room','initial_water')}
                    steps=self.forecast.get('steps', [])
                    record['predictions']=[{k:s[k] for k in ('end','room','water','action','hz','inline_kw')} for s in steps]
                    record['observed']={e:states[e].state if e in states else None for e in
                        ('sensor.ovanvaning_temperature','sensor.nedervaning_temperature','sensor.vp_priority',
                         'sensor.vp_current_compressor_frequency','sensor.vp_power_internal_add_heat')}
                    self.prediction_log=(self.prediction_log+[record])[-192:]
                    await self.forecast_store.async_save({'records':self.prediction_log,'decisions':self.decision_log})
            except Exception:
                # Forecast/storage problems must not interrupt the running thermostat.
                self.forecast={'status':'Forecast unavailable','message':'See integration logs.','steps':[]}
                self.predictor.result = self.forecast
                self.predictor.retry_after = 120
                _LOGGER.exception('NIBE forecast evaluation failed')
        try:
            self.accounting.observe(states,now,{**self.learner.prior,**self.learner.parameters()},self.forecast)
            if now-self.last_accounting_save>=300:
                self.costs=self.accounting.view(now)
                await self.accounting_store.async_save(self.accounting.dump())
                self.last_accounting_save=now
        except Exception:
            _LOGGER.exception('Could not update local electricity history')
        # Source retrieval may await I/O: use current readings for live control.
        now = self.clock()
        states = {s.entity_id:s for s in self.hass.states.async_all()}
        # Entity registry/restored states can outlive the YAML package. The
        # script-specific service exists only while the old writer is loaded.
        if self.hass.services.has_service('script', 'nibe_smart_control_cycle'):
            self.status = 'Legacy backend detected'
            return
        if hold_inline_writes or await self._inline_tick(states, now):
            return
        await self._offer_inline(now)
        water = all(fresh(states.get(e), now) for e in (SUPPLY, REQUIRED, PRIORITY))
        short = water and states[PRIORITY].state == 'Heating' and number(states[SUPPLY].state) is not None and number(states[REQUIRED].state) is not None and float(states[SUPPLY].state) < float(states[REQUIRED].state)-2
        if short:
            if self.short_since is None:
                self.short_since = now
        else:
            self.short_since = None
        recovery_offset = None
        if not self.data['enabled']:
            native_dhw = states.get('select.vp_comfort_mode')
            if self.data['release_dhw'] and native_dhw and native_dhw.state in ('Normal','Lux'):
                self.data['release_dhw'] = False
                await self.store.async_save(dict(self.data))
            self.status = 'Paused'
            self.control = {'mode':'Paused','dhw':'Normal','dhw_action':'Restoring Normal' if self.data['release_dhw'] and restore_dhw(states) else 'Native/manual',
                            'reason':'Restoring Normal hot-water operation.' if self.data['release_dhw'] else 'Paused; hot water is under native/manual control.'}
            result = {'targets':self.targets, 'writes':restore_dhw(states) if self.data['release_dhw'] else []}
        else:
            chosen = adaptive_request(self.forecast,states,now,{**self.forecast.get('model',{}),'dhw_morning_pending':self.data['dhw_morning_pending'],'dhw_morning_completed':self._morning_completed(now)}) if self.forecast.get('steps') else None
            if chosen is not None and chosen['dhw_morning_override']!=self.data['dhw_morning_pending']:
                self.data['dhw_morning_pending']=chosen['dhw_morning_override']
                await self.store.async_save(dict(self.data))
            fallback_reason=self.forecast.get('message') or 'Prices/weather unavailable; using temperature control.'
            if chosen is None and self.forecast.get('steps'):
                fallback_reason='The current plan cannot be applied: it is stale, outside its command interval, or required live readings are unavailable.'
            self.control = {**bounds,**(chosen or {'mode':'Thermostat fallback', 'reason':fallback_reason})}
            if chosen is not None:
                chosen.update({**bounds,'c1_transition':{'direction':self.data['c1_direction'],'time':self.data['c1_changed']}})
            response = self.offset_learner.parameters()
            recovery_offset = self.degree_recovery.offset(states, now, bounds['room_max_c'], number(response.get('offset_gain')))
            result = calculate(states, now, dt_util.now().hour,
                self.short_since is not None and now-self.short_since >= 900, control=chosen,options=options,
                response=response, compressor_heat_kw=self.native_heat_kw,
                recovery_offset=recovery_offset, temporary_heat=self.learner.temporary_heat.profile(now))
            if result is None:
                result = {'targets':[], 'writes':restore_dhw(states)}
                self.status = 'Waiting for readings'
            else:
                self.status = 'Waiting for readings' if not result['targets'] else 'Write failed' if self.write_failed else 'Running'
            self.targets = result['targets']
            balance = result.get('capacity_balance')
            if self.degree_recovery.active:
                target_dm = self.degree_recovery.event['target_dm']
                self.control['reason'] = f'Rebuilding heating demand to {target_dm:g} degree minutes after a sudden reset.'
                self.control['degree_minute_recovery'] = self.degree_recovery.event
                if recovery_offset is not None:
                    self.control['offset_c1'] = recovery_offset
            elif result.get('temporary_heat_trim') and not self.control.get('locked'):
                self.control['offset_c1'] = result['offset_c1']
                self.control['reason'] = 'Keeping heat available to the cooler room.'
            elif balance and not self.control.get('locked'):
                self.control['capacity_balance'] = balance
                self.control['offset_c1'] = balance['offset']
                self.control['reason'] = 'Matching the primary target to available heat while downstairs recovers'
            elif chosen and chosen.get('confirm_capacity_balance'):
                self.control['offset_c1'] = result.get('offset_c1')
                self.control['reason'] = 'Rechecking the primary supply and compressor before balancing'
            self.control['fallback_release']=result.get('fallback_release',False)
            self.control['c1_commitment_until']=self.data['c1_changed']+2880. if self.data['c1_direction'] else None
        self.control['command_not_before']=max(now,float(self.data['last_cycle'])+902,float(self.data['last_attempt'])+902)
        if self.inline_service:
            self.control['inline_approval'] = self._inline_status()
        self.control['pending_writes']=[{'entity':e,'requested':v} for e,v in result['writes']]
        hold_until=number(self.control.get('hold_until')) or 0.
        if self.data['enabled'] and self.control.get('locked') and hold_until>now:
            # A C2-only write during the final minute of a modelled hold would
            # reserve another full budget window ahead of the next joint action.
            self.control['command_not_before']=max(self.control['command_not_before'],hold_until)
            self.control['pending_writes']=[]
            return
        # Unchanged settings do not consume a cloud-write interval. Existing
        # persisted gates remain honoured after an upgrade/reload.
        if not result['writes']:
            if self.write_failed:
                self.write_failed=False
                if self.status=='Write failed':
                    self.status='Running'
            # Keep hold decisions observable without reserving a native write.
            if not self.decision_log or now-self.decision_log[-1]['time']>=900 or self.decision_log[-1]['control'].get('mode')!=self.control.get('mode'):
                self._record_decision(now,[],states)
                if self.predictor:
                    await self.forecast_store.async_save({'records':self.prediction_log,'decisions':self.decision_log})
            return
        inline_window = self._next_inline_window(now)
        if self.data['enabled'] and inline_window and inline_window['start'] < now + WRITE_INTERVAL + 60:
            # Keep the batch available if a reply arrives just before the window.
            return
        if not self._write_window_open(now):
            return
        self.data['last_cycle'] = now
        await self.store.async_save(dict(self.data))
        failed = False
        attempts = []
        for entity, value in result['writes']:
            if self.stopping:
                break
            if not self.data['enabled'] and (entity != 'select.vp_comfort_mode' or value != 'Normal'):
                continue
            self.data['last_attempt'] = self.clock()
            # A failed durable reservation must prevent the cloud call.
            await self.store.async_save(dict(self.data))
            if self.stopping:
                break
            if not self.data['enabled'] and (entity != 'select.vp_comfort_mode' or value != 'Normal'):
                continue
            domain = entity.split('.')[0]
            try:
                attempts.append({'entity':entity,'requested':value,'success':False})
                await self.hass.services.async_call(domain,
                    'set_value' if domain == 'number' else 'select_option',
                    {'entity_id': entity, 'value' if domain == 'number' else 'option': value}, blocking=True)
                attempts[-1]['success'] = True
                if entity == C1:
                    before=number(states[entity].state)
                    if before is not None and abs(value-before)>.01:
                        if recovery_offset is None:
                            self.data['c1_direction'] = 1. if value > before else -1.
                            self.data['c1_changed'] = self.clock()
                        else:
                            self.data['c1_direction'] = self.data['c1_changed'] = 0.
            except Exception:
                self.status = 'Write failed'
                failed = True
                _LOGGER.exception('NIBE setting request failed for %s; attempt consumed', entity)
            finally:
                self.data['last_attempt'] = self.clock()
                await self.store.async_save(dict(self.data))

        self.write_failed = failed
        self.control['command_not_before']=max(self.clock(),float(self.data['last_cycle'])+902,float(self.data['last_attempt'])+902)
        self._record_decision(now,attempts,states)
        if self.predictor:
            try:
                await self.forecast_store.async_save({'records':self.prediction_log,'decisions':self.decision_log})
            except Exception:
                _LOGGER.exception('Could not save adaptive decision history')

    def _write_window_open(self, now):
        return now >= max(float(self.data['last_cycle']), float(self.data['last_attempt'])) + WRITE_INTERVAL

    async def _inline_response(self, event):
        await self.async_respond_inline(action=event.data.get('action'))

    async def async_respond_inline(self, *, action=None, approve_current=False):
        async with self.lock:
            if self.inline_approval_pending:
                now = self.clock()
                responded = self.inline.approve(now) if approve_current else self.inline.respond(action, now)
                if responded:
                    await self._save_inline_request()
                    self.control['inline_approval'] = self._inline_status()
                    self.notify()
                    return True
        return False

    async def _save_inline_request(self):
        self.data['inline_request'] = self.inline.dump(self.inline_service)
        await self.store.async_save(dict(self.data))

    def _latest_inline_plan(self, now):
        if 0 <= now - self.forecast.get('generated_at', 0) <= 1200:
            return self.forecast.get('inline_plan')
        return None

    def _next_inline_window(self, now):
        if not self.inline_requests_allowed:
            return None
        return self.inline.next_window(now, self._latest_inline_plan(now))

    def _inline_status(self):
        now = self.clock()
        offer = self.inline.offer
        current = self._latest_inline_plan(now)
        details = offer or current or {}
        if self.data['inline_restore']:
            active = self.inline_requests_allowed and self.inline_active_until is not None and now < self.inline_active_until
            return {**details, 'state': 'Permitted' if active else 'Returning to 0 kW',
                    'end': self.inline_active_until}
        if not self.data['inline_requests_enabled']:
            return {**details, 'state': 'Requests blocked'}
        if offer:
            next_window = self._next_inline_window(now)
            return {**offer, 'state': 'Approved' if self.inline.approved else 'Awaiting approval',
                    'start': next_window['start'] if next_window else None}
        if now < self.inline.closed_until:
            return {'state': 'Not approved', 'horizon_end': self.inline.closed_until}
        return {**details, 'state': 'Planned' if current else 'Off'}

    async def _offer_inline(self, now):
        if not self.inline_service or not self.inline_approval_entity or not self.inline_requests_allowed:
            return
        plan = self._latest_inline_plan(now)
        if self.inline.offer or not plan:
            return
        windows = [w for w in plan['windows'] if w['start'] >= max(now + MIN_LEAD, self.inline.closed_until)]
        zone = self.accounting.zone
        if not windows or not request_due(now, windows[0]['start'], zone):
            return
        if not self.hass.services.has_service('notify', self.inline_service):
            return
        notification = self.inline.notification({'windows': windows, 'horizon_end': plan['horizon_end']},
                                                zone, self.inline_approval_entity)
        await self._save_inline_request()
        if not self.inline_requests_allowed or not request_due(max(now, self.clock()), windows[0]['start'], zone):
            self.inline.clear()
            await self._save_inline_request()
            return
        try:
            await self.hass.services.async_call('notify', self.inline_service, notification, blocking=True)
        except Exception:
            self.inline.close()
            await self._save_inline_request()
            _LOGGER.exception('Could not request phone approval for inline heating')

    async def _set_inline_cap(self, option, window=None):
        """Use a dedicated batch and reserve it before touching the cloud."""
        now = self.clock()
        if not self._write_window_open(now) or self.stopping:
            return False
        if window and (not self.inline_requests_allowed or now >= window['start'] + START_GRACE):
            return False
        if window:
            # Persist consumption and restoration together before the cloud call.
            self.inline.used_until = window['end']
            self.data['inline_request'] = self.inline.dump(self.inline_service)
        self.data['last_cycle'] = self.data['last_attempt'] = now
        # Restorability must survive a crash or ambiguous response to the write.
        self.data['inline_restore'] = True
        self.data['inline_zero_requested'] = None
        await self.store.async_save(dict(self.data))
        try:
            if self.stopping or (window and (not self.inline_requests_allowed
                    or self.clock() >= window['start'] + START_GRACE)):
                return False
            await self.hass.services.async_call(
                'select', 'select_option', {'entity_id': CAP_ENTITY, 'option': option}, blocking=True)
            self.inline_active_until = window['end'] if window else None
            if window is None:
                self.data['inline_zero_requested'] = now
            return True
        except Exception:
            self.inline_active_until = None
            _LOGGER.exception('NIBE inline power cap write failed')
            return False
        finally:
            self.data['last_attempt'] = self.clock()
            await self.store.async_save(dict(self.data))

    async def _inline_tick(self, states, now):
        """Return True while heater operation reserves the cloud write batch."""
        if self.inline.expire(now):
            await self._save_inline_request()
        cap = states.get(CAP_ENTITY)
        off = power_option(cap, 0)
        if self.data['inline_restore'] and await self._confirmed_inline_off(cap, off, now):
            return False
        if self.data['inline_restore']:
            if self.inline_active_until is None or not self.inline_requests_allowed or now >= self.inline_active_until - 60:
                if off:
                    await self._set_inline_cap(off)
                self.control['inline_approval'] = self._inline_status()
                return True
            self.control['inline_approval'] = self._inline_status()
            return True
        if not self.inline_service:
            return False
        # With managed permission, external positive caps are returned to 0.
        if off and fresh(cap, now) and cap.state != off:
            await self._set_inline_cap(off)
            self.control['inline_approval'] = {'state': 'Returning to 0 kW'}
            return True
        window = self._next_inline_window(now)
        if not window or now < window['start'] or not self.inline.approved or not self.data['enabled']:
            return False
        priority = states.get(PRIORITY)
        dm = states.get('sensor.vp_degree_minutes_2')
        deficit = number(dm.state) if fresh(dm, now) else None
        temperatures = [number(states[e].state) if fresh(states.get(e), now) else None for e in (ROOM1, ROOM2)]
        upper = self.forecast.get('model', {}).get('room_max_c', 20.5)
        if (self._write_window_open(now) and supports_window(states, now, window['kw'])
                and cap.state == off and fresh(priority, now) and priority.state == 'Heating'
                and all(v is not None and 5 <= v < upper for v in temperatures)
                and deficit is not None and deficit <= self.offset_learner.aux_dm):
            await self._set_inline_cap(power_option(cap, window['kw']), window)
        self.control['inline_approval'] = self._inline_status()
        return True

    async def _confirmed_inline_off(self, cap, off, now):
        requested = number(self.data['inline_zero_requested'])
        if requested is None or not off or not fresh(cap, now) or cap.state != off:
            return False
        if cap.last_reported.timestamp() < requested:
            return False
        self.data['inline_restore'] = False
        self.data['inline_zero_requested'] = None
        self.inline_active_until = None
        await self.store.async_save(dict(self.data))
        return True

    async def async_prepare_unload(self):
        async with self.lock:
            if not self.data['inline_restore']:
                return True
            self.inline_active_until = None
            cap = self.hass.states.get(CAP_ENTITY)
            off = power_option(cap, 0)
            if await self._confirmed_inline_off(cap, off, self.clock()):
                return True
            if off:
                await self._set_inline_cap(off)
            return False

    def _morning_completed(self, now):
        today=datetime.fromtimestamp(now,self.accounting.zone).date().isoformat()
        return self.data.get('dhw_morning_completed_date')==today

    async def _observe_morning_completion(self, states, now):
        # Record a measured completion, never a forecasted one. A new local date
        # naturally starts a new goal; ordinary post-06:00 draw-off must not
        # retroactively mark this morning's already-completed goal as missed.
        if not self.data['enabled']:
            return
        local=datetime.fromtimestamp(now,self.accounting.zone)
        today=local.date().isoformat()
        if local.hour<6 or self.data.get('dhw_morning_completed_date')==today:
            return
        readings=[states.get(e) for e in ('sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6')]
        values=[number(s.state) if fresh(s,now) else None for s in readings]
        if any(v is None or not 10<=v<=80 for v in values):
            return
        ceiling=number(self.forecast.get('model',{}).get('tank_max_c'))
        if ceiling is None:
            ceiling=number(self.learner.parameters().get('tank_max_c'))
        if ceiling is not None and sum(values)/2>=ceiling-.5:
            self.data['dhw_morning_completed_date']=today
            await self.store.async_save(dict(self.data))
            if self.predictor:
                # Completion changes the morning constraint, so don't retain
                # an old forced-recovery plan until the usual price refresh.
                self.predictor.last_refresh=None

    def _record_decision(self, now, attempts, states):
        self.decision_log=(self.decision_log+[{'time':now,'control':dict(self.control),
            'targets':self.targets[:],'attempts':attempts,
            'rooms':[states[e].state if e in states else None for e in
                ('sensor.ovanvaning_temperature','sensor.nedervaning_temperature')]}])[-512:]
