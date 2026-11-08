"""Exercise the shipped policy and async controller with deterministic HA fakes."""
import asyncio
import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / 'custom_components/nibe_f750'

class Store:
    saved = None
    other = {}
    def __init__(self, *args):
        self.fail = False
        self.key = args[-1]
    async def async_load(self):
        return copy.deepcopy(Store.saved if self.key.endswith('.control') else Store.other.get(self.key))
    async def async_save(self, data):
        if self.fail:
            raise OSError('Disk unavailable')
        if self.key.endswith('.control'):
            Store.saved = copy.deepcopy(data)
        else:
            Store.other[self.key] = copy.deepcopy(data)

for name in ['homeassistant','homeassistant.helpers','homeassistant.helpers.event',
             'homeassistant.helpers.storage','homeassistant.util']:
    sys.modules.setdefault(name, ModuleType(name))
sys.modules['homeassistant.helpers.event'].async_track_time_interval = lambda *args: lambda: None
sys.modules['homeassistant.helpers.storage'].Store = Store
sys.modules['homeassistant.util'].dt = SimpleNamespace(now=lambda: SimpleNamespace(hour=12))
pkg = ModuleType('_nibe_test')
pkg.__path__ = [str(COMPONENT)]
sys.modules[pkg.__name__] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location('_nibe_test.'+name, COMPONENT/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

engine = load('engine')
runtime = load('controller')

class States:
    def __init__(self, fixture):
        self.fixture = fixture
        self.values = {engine.C1:'0', engine.C2:'0', engine.ROOM1:'20.5', engine.ROOM2:'18.2',
          engine.SUPPLY:'36', engine.REQUIRED:'34', engine.PRIORITY:'Heating', engine.PRICE:'.5',
          'sensor.vp_average_outdoor_temp_bt1':'5', 'sensor.vp_exhaust_air_bt20':'20', engine.DHW:'Economy'}
    def async_all(self):
        return [SimpleNamespace(entity_id=e,state=v, last_reported=datetime.fromtimestamp(self.fixture.time, timezone.utc),
          attributes={'min':-10,'max':10,'options':['Economy','Normal','Lux']}) for e,v in self.values.items()]

class Fixture:
    def __init__(self):
        self.time = 1800000000.
        self.states = States(self)
        self.calls = []
        self.fail = False
        self.legacy_writer = False
        self.services = SimpleNamespace(async_call=self.call, has_service=lambda domain, service: self.legacy_writer and (domain, service)==('script','nibe_smart_control_cycle'))
    async def call(self, domain, service, data, blocking):
        assert Store.saved['last_attempt'] == self.time
        self.calls.append((self.time, domain, service, data))
        self.time += .6
        if self.fail:
            raise RuntimeError('Cloud unavailable')
        # Do not acknowledge changes: keeps maximum requests pending for budget tests.

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Store.saved = None
        Store.other = {}
        self.hass = Fixture()
        self.controller = runtime.Controller(self.hass, clock=lambda: self.hass.time)

    async def test_default_start_and_rolling_budget(self):
        await self.controller.async_start()
        self.assertTrue(self.controller.data['enabled'])
        self.assertEqual(self.controller.status, 'Running')
        start = self.hass.time
        for minute in range(90):
            self.hass.time = start+minute*60
            await self.controller.async_tick()
        self.assertEqual(len(self.hass.calls), 18)
        for t, *_ in self.hass.calls:
            self.assertLessEqual(sum(t <= call[0] < t+900 for call in self.hass.calls), 3)

    async def test_pause_restores_and_reload_preserves_budget(self):
        await self.controller.async_start()
        await self.controller.async_enable(False)
        restored = runtime.Controller(self.hass, clock=lambda: self.hass.time)
        await restored.async_start()
        self.assertFalse(restored.data['enabled'])
        self.assertEqual(restored.status, 'Paused')
        await restored.async_enable(True)
        self.assertEqual(restored.status, 'Running')
        self.assertEqual(len(self.hass.calls), 3)

    async def test_failures_reserve_budget_and_persist(self):
        self.hass.fail = True
        with self.assertLogs(runtime._LOGGER, level='ERROR'):
            await self.controller.async_start()
        self.assertEqual(len(self.hass.calls), 3)
        last = self.hass.time
        await self.controller.async_tick()
        self.assertEqual(len(self.hass.calls), 3)
        reloaded = runtime.Controller(self.hass, clock=lambda: self.hass.time)
        await reloaded.async_start()
        self.assertEqual(reloaded.data['last_attempt'], last)
        self.assertEqual(len(self.hass.calls), 3)

    async def test_failed_storage_prevents_writes(self):
        self.controller.store.fail = True
        with self.assertLogs(runtime._LOGGER, level='ERROR'):
            await self.controller.async_start()
        self.assertEqual(self.hass.calls, [])
        self.assertEqual(self.controller.status, 'Controller error')

    async def test_legacy_backend_and_stop_block_dispatch(self):
        self.hass.legacy_writer = True
        self.hass.states.values['input_boolean.nibe_smart_control_enabled'] = 'off'
        await self.controller.async_start()
        self.hass.time += 1800
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, 'Legacy backend detected')
        self.assertEqual(self.hass.calls, [])
        await self.controller.async_stop()
        self.hass.states.values.pop('input_boolean.nibe_smart_control_enabled')
        await self.controller.async_tick()
        self.assertEqual(self.hass.calls, [])

    async def test_orphan_legacy_entities_do_not_block_control(self):
        for state in ('unavailable', 'off', 'on'):
            Store.saved = None
            Store.other = {}
            self.hass = Fixture()
            self.hass.states.values['input_boolean.nibe_smart_control_enabled'] = state
            self.hass.states.values['script.nibe_smart_control_cycle'] = state
            controller = runtime.Controller(self.hass, clock=lambda: self.hass.time)
            await controller.async_start()
            self.hass.time += 901
            await controller.async_tick()
            self.assertEqual(controller.status, 'Running')
            self.assertEqual(len(self.hass.calls), 3)

    async def test_report_timestamp_rounding_tolerates_tiny_skew(self):
        state = self.hass.states.async_all()[0]
        state.last_reported = datetime.fromtimestamp(self.hass.time+.000001, timezone.utc)
        self.assertTrue(engine.fresh(state, self.hass.time))
        state.last_reported = datetime.fromtimestamp(self.hass.time+60, timezone.utc)
        self.assertFalse(engine.fresh(state, self.hass.time))

    async def test_start_waits_only_for_missing_readings(self):
        self.hass.states.values[engine.ROOM1] = 'unavailable'
        await self.controller.async_start()
        self.assertEqual(self.controller.status, 'Waiting for readings')
        self.assertEqual([c[3] for c in self.hass.calls],[{'entity_id':engine.DHW,'option':'Normal'}])
        self.hass.states.values[engine.ROOM1] = '20.5'
        await self.controller.async_tick()
        self.assertEqual(len(self.hass.calls),1)
        self.hass.time += 903
        await self.controller.async_tick()
        self.assertEqual(len(self.hass.calls),4)

    async def test_policy_c1_priority_missing_readings_and_dhw(self):
        self.hass.states.values[engine.ROOM1] = '19.1'
        states = {s.entity_id:s for s in self.hass.states.async_all()}
        result = engine.calculate(states, self.hass.time, 12)
        self.assertNotIn(engine.C2, [e for e,v in result['writes']])
        self.assertEqual(result['targets'], [20,19])
        states[engine.ROOM1].state = 'unknown'
        self.assertIsNone(engine.calculate(states,self.hass.time,12))
        states[engine.ROOM1].state = '20'
        states[engine.PRIORITY].state = 'Hot water'
        self.assertNotIn(engine.C2,[e for e,v in engine.calculate(states,self.hass.time,12)['writes']])

    async def test_pause_during_reservation_stops_dispatch(self):
        original = self.controller.store.async_save
        async def save(data):
            await original(data)
            if data['last_attempt']:
                self.controller.data['enabled'] = False
        self.controller.store.async_save = save
        await self.controller.async_start()
        self.assertEqual([c[3] for c in self.hass.calls],[{'entity_id':engine.DHW,'option':'Normal'}])

class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_registers_frontend_and_unloads(self):
        # Contract-shaped fakes exercise the actual integration entrypoints.
        for name in ['homeassistant.components', 'homeassistant.components.http',
                     'homeassistant.exceptions', 'homeassistant.const']:
            sys.modules.setdefault(name, ModuleType(name))
        sys.modules['homeassistant.components.http'].StaticPathConfig = lambda *args: args
        sys.modules['homeassistant.exceptions'].ConfigEntryNotReady = RuntimeError
        sys.modules['homeassistant.const'].Platform = SimpleNamespace(SENSOR='sensor', SWITCH='switch', BUTTON='button')
        module = ModuleType('_nibe_test.setup')
        module.__package__ = '_nibe_test'
        module.__file__ = str(COMPONENT/'__init__.py')
        exec(compile((COMPONENT/'__init__.py').read_text(), module.__file__, 'exec'), module.__dict__)
        class Resources:
            loaded = False
            def __init__(self):
                self.items = [{'id':'old', 'url':'/hacsfiles/nibe-f750-dashboard/nibe-f750-card.js'}]
            async def async_load(self):
                self.loaded = True
            def async_items(self):
                return self.items
            async def async_create_item(self, data):
                self.items.append({'id':'new', **data})
            async def async_update_item(self, id, data):
                next(i for i in self.items if i['id']==id).update(data)
            async def async_delete_item(self, id):
                self.items = [i for i in self.items if i['id']!=id]
        Store.saved = None
        Store.other = {}
        hass = Fixture()
        module.Controller=lambda hass,predictor:runtime.Controller(hass,clock=lambda:hass.time,predictor=predictor)
        resources = Resources()
        hass.data = {'lovelace':SimpleNamespace(resources=resources)}
        paths = []
        async def register(config):
            paths.extend(config)
        async def forward(entry, platforms):
            self.assertEqual(platforms, ['sensor','switch','button'])
        async def unload(entry, platforms):
            return True
        hass.http = SimpleNamespace(async_register_static_paths=register)
        hass.config_entries = SimpleNamespace(async_forward_entry_setups=forward, async_unload_platforms=unload)
        entry = SimpleNamespace(entry_id='one',options={},async_on_unload=lambda cb:None,add_update_listener=lambda cb:lambda:None)
        self.assertTrue(await module.async_setup_entry(hass, entry))
        self.assertEqual(len(paths),1)
        self.assertEqual(resources.items, [{'id':'new','url':module.URL,'res_type':'module'}])
        self.assertTrue(await module.async_unload_entry(hass, entry))
        self.assertTrue(await module.async_setup_entry(hass, entry))
        self.assertEqual(len(paths),1)  # Reload must not register the route twice.
        self.assertEqual(len(resources.items),1)
        self.assertTrue(await module.async_unload_entry(hass, entry))

if __name__ == '__main__':
    unittest.main()
