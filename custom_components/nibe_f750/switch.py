"""Enable/pause the single persistent controller."""
from homeassistant.components.switch import SwitchEntity
from .controller import DOMAIN
from .entity import ControllerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ControlSwitch(hass.data[DOMAIN][entry.entry_id])])


class ControlSwitch(ControllerEntity, SwitchEntity):
    def __init__(self, controller):
        super().__init__(controller, 'enabled', 'NIBE Smart Control')

    @property
    def is_on(self):
        return self.controller.data['enabled']

    @property
    def extra_state_attributes(self):
        return {'controller_domain': DOMAIN, 'status': self.controller.status, 'targets': self.controller.targets,
                'last_cycle': self.controller.data['last_cycle'],
                'last_attempt': self.controller.data['last_attempt']}

    async def async_turn_on(self, **kwargs):
        await self.controller.async_enable(True)

    async def async_turn_off(self, **kwargs):
        await self.controller.async_enable(False)
