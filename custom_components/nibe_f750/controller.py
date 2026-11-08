"""Persistent, serialized controller using HA's built-in myUplink setters."""
import asyncio
from datetime import timedelta
import logging
import time

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from .adaptive import ThermalLearner
from .offset import OffsetLearner
from .accounting import Accounting
from .supervisor import request as adaptive_request
from .engine import restore_dhw, calculate, fresh, number, SUPPLY, REQUIRED, PRIORITY, TELEMETRY

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
        self.history_task = None
        self.data = {'enabled': True, 'last_cycle': 0, 'last_attempt': 0, 'release_dhw':False}
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
        self.learner = ThermalLearner(getattr(predictor,'options',None))
        self.saved_learning_revision = 0
        self.offset_learner = OffsetLearner()
        self.offset_store = Store(hass,1,DOMAIN+'.offset_response')
        self.control = {'mode':'Thermostat fallback','reason':'Waiting for prices and weather.'}

    async def async_start(self):
        self.accounting.restore(await self.accounting_store.async_load())
        self.offset_learner.restore(await self.offset_store.async_load())
        learning = await self.learning_store.async_load()
        if learning and not self.learner.restore(learning):
            _LOGGER.warning('Invalid adaptive model data; restarting learning from initial parameters')
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
        if type(self.data['enabled']) is not bool or type(self.data['release_dhw']) is not bool or any(number(self.data[k]) is None for k in ('last_cycle', 'last_attempt')):
            raise ValueError('Invalid persisted controller state')
        self.unsubscribe = async_track_time_interval(self.hass, self.async_tick, timedelta(minutes=1))
        await self.async_tick()
        if (not self.accounting.history_checked and 'recorder' in getattr(getattr(self.hass,'config',None),'components',set())
            and hasattr(self.hass,'async_create_background_task')):
            cutoff=min([self.accounting.previous['time'] if self.accounting.previous else self.clock()]+[r.get('observed_start',t) for t,r in self.accounting.bins.items() if r.get('seconds')])
            self.history_task=self.hass.async_create_background_task(self.async_backfill_accounting(cutoff),'NIBE electricity history')

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
            await self.store.async_save(dict(self.data))
        await self.async_tick()

    async def async_reset_learning(self):
        async with self.lock:
            self.learner = ThermalLearner(getattr(self.predictor,'options',None))
            await self.learning_store.async_save(self.learner.dump())
            self.saved_learning_revision = 0
            self.offset_learner = OffsetLearner()
            await self.offset_store.async_save(self.offset_learner.dump())
            if self.predictor:
                self.predictor.last_refresh = None
        await self.async_tick()

    async def async_stop(self):
        self.stopping = True
        if self.history_task and not self.history_task.done():
            self.history_task.cancel()
            try:
                await self.history_task
            except asyncio.CancelledError:
                pass
        if self.unsubscribe:
            self.unsubscribe()
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
        if now-self.last_sample >= 300:
            self.telemetry = {e: {'value': states[e].state if e in states else 'unknown',
                'unit': states[e].attributes.get('unit_of_measurement') if e in states else None,
                'reported_at': states[e].last_reported.isoformat() if e in states else None} for e in TELEMETRY}
            self.last_sample = now
        try:
            self.learner.update(states,now,dt_util.now().hour)
            revision=self.offset_learner.revision
            self.offset_learner.update(states,now,self.learner.prior['compressor_heat_kw'])
            if revision!=self.offset_learner.revision:
                await self.offset_store.async_save(self.offset_learner.dump())
            if self.learner.revision != self.saved_learning_revision:
                await self.learning_store.async_save(self.learner.dump())
                self.saved_learning_revision = self.learner.revision
        except Exception:
            _LOGGER.exception('Adaptive learning update failed; retaining the last working model')
        if self.predictor:
            try:
                self.predictor.adaptive_model = self.learner.parameters()
                self.predictor.learning = self.learner.diagnostics()
                self.predictor.offset_response = self.offset_learner.parameters()
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
        water = all(fresh(states.get(e), now) for e in (SUPPLY, REQUIRED, PRIORITY))
        short = water and states[PRIORITY].state == 'Heating' and number(states[SUPPLY].state) is not None and number(states[REQUIRED].state) is not None and float(states[SUPPLY].state) < float(states[REQUIRED].state)-2
        if short:
            if self.short_since is None:
                self.short_since = now
        else:
            self.short_since = None
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
            chosen = adaptive_request(self.forecast,states,now,self.forecast.get('model',{})) if self.forecast.get('steps') else None
            self.control = chosen or {'mode':'Thermostat fallback', 'reason':self.forecast.get('message','Prices/weather unavailable; using temperature control.')}
            result = calculate(states, now, dt_util.now().hour,
                self.short_since is not None and now-self.short_since >= 900, control=chosen)
            if result is None:
                result = {'targets':[], 'writes':restore_dhw(states)}
                self.status = 'Waiting for readings'
            else:
                self.status = 'Write failed' if self.write_failed else 'Running'
            self.targets = result['targets']
        if now-float(self.data['last_cycle']) < 902 or now-float(self.data['last_attempt']) < 902:
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
            except Exception:
                self.status = 'Write failed'
                failed = True
                _LOGGER.exception('NIBE setting request failed for %s; attempt consumed', entity)
            finally:
                self.data['last_attempt'] = self.clock()
                await self.store.async_save(dict(self.data))

        self.write_failed = failed
        self.decision_log=(self.decision_log+[{'time':now,'control':dict(self.control),
            'targets':self.targets[:],'attempts':attempts,
            'rooms':[states[e].state if e in states else None for e in
                ('sensor.ovanvaning_temperature','sensor.nedervaning_temperature')]}])[-512:]
        if self.predictor:
            try:
                await self.forecast_store.async_save({'records':self.prediction_log,'decisions':self.decision_log})
            except Exception:
                _LOGGER.exception('Could not save adaptive decision history')
