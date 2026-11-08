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
    def __init__(self, hass, clock=time.time):
        self.hass = hass
        self.clock = clock
        self.store = Store(hass, 1, DOMAIN + '.control')
        self.data = {'enabled': True, 'last_cycle': 0, 'last_attempt': 0}
        self.status = 'Starting'
        self.targets = []
        self.telemetry = {}
        self.short_since = None
        self.started = clock()
        self.lock = asyncio.Lock()
        self.listeners = set()
        self.stopping = False
        self.unsubscribe = None
        self.last_sample = 0
        self.write_failed = False

    async def async_start(self):
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
        # Entity registry/restored states can outlive the YAML package. The
        # script-specific service exists only while the old writer is loaded.
        if self.hass.services.has_service('script', 'nibe_smart_control_cycle'):
            self.status = 'Legacy backend detected'
            return
        if not self.data['enabled']:
            self.status = 'Paused'
            return
        if now-self.started < 900:
            self.status = 'Starting'
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
