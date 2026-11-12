"""NIBE F750 controller and bundled dashboard cards."""
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import Platform
from .controller import Controller, DOMAIN
from .forecast import Predictor

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]
URL = '/nibe-f750/nibe-f750-card.js?v=0.27.0'


async def async_setup_entry(hass, entry):
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get('frontend_registered'):
        await hass.http.async_register_static_paths([StaticPathConfig(
            '/nibe-f750/nibe-f750-card.js', str(Path(__file__).parent / 'frontend' / 'nibe-f750-card.js'), False)])
        data['frontend_registered'] = True
    lovelace = hass.data.get('lovelace')
    resources = getattr(lovelace, 'resources', None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get('resources')
    if resources is not None and hasattr(resources, 'async_create_item'):
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        existing = list(resources.async_items())
        own = next((r for r in existing if r['url'].split('?')[0] == URL.split('?')[0]), None)
        if own:
            await resources.async_update_item(own['id'], {'url': URL, 'res_type': 'module'})
        else:
            await resources.async_create_item({'url': URL, 'res_type': 'module'})
        for item in existing:
            path = item['url'].split('?')[0]
            if path in ('/local/nibe-f750-card.js', '/local/nibe-f750-smart-card.js',
                        '/hacsfiles/nibe-f750-dashboard/nibe-f750-card.js'):
                await resources.async_delete_item(item['id'])
    else:
        # Frontend modules also load automatically for YAML-mode dashboards.
        from homeassistant.components import frontend
        frontend.add_extra_js_url(hass, URL)
    controller = Controller(hass, predictor=Predictor(hass, entry.options))
    data[entry.entry_id] = controller
    try:
        await controller.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as err:
        await controller.async_stop()
        data.pop(entry.entry_id, None)
        raise ConfigEntryNotReady(str(err)) from err
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    controller = hass.data[DOMAIN][entry.entry_id]
    controller.stopping = True
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await controller.async_stop()
        del hass.data[DOMAIN][entry.entry_id]
        return True
    controller.stopping = False
    return False
