"""Entities share a local controller and never poll NIBE themselves."""
from homeassistant.helpers.entity import Entity, DeviceInfo
from .controller import DOMAIN


class ControllerEntity(Entity):
    _attr_should_poll = False

    def __init__(self, controller, key, name):
        self.controller = controller
        self._attr_unique_id = DOMAIN + '_' + key
        self._attr_name = name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, DOMAIN)},
            name='NIBE F750 Smart Control', manufacturer='Community', model='myUplink controller')

    async def async_added_to_hass(self):
        self.controller.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.controller.listeners.discard(self.async_write_ha_state))
