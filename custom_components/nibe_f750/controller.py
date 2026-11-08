"""Persistent, serialized controller using HA's built-in myUplink setters."""
import asyncio
from datetime import timedelta
import logging
import time

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from .engine import calculate, fresh, number, SUPPLY, REQUIRED, PRIORITY, TELEMETRY

_LOGGER = logging.getLogger(__name__)
DOMAIN = 'nibe_f750'


class Controller:
    def __init__(self, hass, clock=time.time, predictor=None):
        self.hass = hass
        self.clock = clock
        self.store = Store(hass, 1, DOMAIN + '.control')
        self.forecast_store = Store(hass, 1, DOMAIN + '.predictions')
        self.data = {'enabled': True, 'last_cycle': 0, 'last_attempt': 0}
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

    async def async_start(self):
        if self.predictor:
            history = await self.forecast_store.async_load() or {}
            self.prediction_log = history.get('records', [])[-192:]
        restored = await self.store.async_load()
        if restored:
            self.data.update({k: restored[k] for k in self.data if k in restored})
        # Reject corrupt persistent gates rather than silently resetting a budget.
        if type(self.data['enabled']) is not bool or any(number(self.data[k]) is None for k in ('last_cycle', 'last_attempt')):
            raise ValueError('Invalid persisted controller state')
        self.unsubscribe = async_track_time_interval(self.hass, self.async_tick, timedelta(minutes=1))
        await self.async_tick()

    def notify(self):
        for callback in tuple(self.listeners):
            callback()

    async def async_enable(self, enabled):
        # Apply pause immediately, including between writes in an active batch.
        self.data['enabled'] = enabled
        async with self.lock:
            await self.store.async_save(dict(self.data))
        await self.async_tick()

    async def async_stop(self):
        self.stopping = True
        if self.unsubscribe:
            self.unsubscribe()
        async with self.lock:
            await self.store.async_save(dict(self.data))

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
        if self.predictor:
            try:
                self.forecast = await asyncio.wait_for(self.predictor.async_update(states, now), timeout=30)
                generated = self.forecast.get('generated_at')
                if generated is not None and generated != self.last_prediction:
                    self.last_prediction = generated
                    record={k:self.forecast.get(k) for k in ('generated_at','status','message','initial_room','initial_water')}
                    steps=self.forecast.get('steps', [])
                    record['predictions']=[{k:s[k] for k in ('end','room','water','action','hz','inline_kw')} for s in steps]
                    record['observed']={e:states[e].state if e in states else None for e in
                        ('sensor.ovanvaning_temperature','sensor.nedervaning_temperature','sensor.vp_priority',
                         'sensor.vp_current_compressor_frequency','sensor.vp_power_internal_add_heat')}
                    self.prediction_log=(self.prediction_log+[record])[-192:]
                    await self.forecast_store.async_save({'records':self.prediction_log})
            except Exception:
                # Forecast/storage problems must not interrupt the running thermostat.
                self.forecast={'status':'Forecast unavailable','message':'See integration logs.','steps':[]}
                _LOGGER.exception('NIBE forecast evaluation failed')
        # Entity registry/restored states can outlive the YAML package. The
        # script-specific service exists only while the old writer is loaded.
        if self.hass.services.has_service('script', 'nibe_smart_control_cycle'):
            self.status = 'Legacy backend detected'
            return
        if not self.data['enabled']:
            self.status = 'Paused'
            return
        water = all(fresh(states.get(e), now) for e in (SUPPLY, REQUIRED, PRIORITY))
        short = water and states[PRIORITY].state == 'Heating' and number(states[SUPPLY].state) is not None and number(states[REQUIRED].state) is not None and float(states[SUPPLY].state) < float(states[REQUIRED].state)-2
        if short:
            if self.short_since is None:
                self.short_since = now
        else:
            self.short_since = None
        result = calculate(states, now, dt_util.now().hour,
            self.short_since is not None and now-self.short_since >= 900)
        if result is None:
            self.status = 'Waiting for readings'
            return
        self.targets = result['targets']
        self.status = 'Write failed' if self.write_failed else 'Running'
        if now-float(self.data['last_cycle']) < 902 or now-float(self.data['last_attempt']) < 902:
            return
        self.data['last_cycle'] = now
        await self.store.async_save(dict(self.data))
        failed = False
        for entity, value in result['writes']:
            if self.stopping or not self.data['enabled']:
                break
            self.data['last_attempt'] = self.clock()
            # A failed durable reservation must prevent the cloud call.
            await self.store.async_save(dict(self.data))
            if self.stopping or not self.data['enabled']:
                break
            domain = entity.split('.')[0]
            try:
                await self.hass.services.async_call(domain,
                    'set_value' if domain == 'number' else 'select_option',
                    {'entity_id': entity, 'value' if domain == 'number' else 'option': value}, blocking=True)
            except Exception:
                self.status = 'Write failed'
                failed = True
                _LOGGER.exception('NIBE setting request failed for %s; attempt consumed', entity)
            finally:
                self.data['last_attempt'] = self.clock()
                await self.store.async_save(dict(self.data))

        self.write_failed = failed
