"""Switches for Smart Control and inline heating requests."""
from homeassistant.components.switch import SwitchEntity
from .controller import DOMAIN
from .entity import ControllerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    entities = [ControlSwitch(controller)]
    if controller.inline_service:
        entities.append(InlineRequestsSwitch(controller))
    async_add_entities(entities)


class ControlSwitch(ControllerEntity, SwitchEntity):
    def __init__(self, controller):
        super().__init__(controller, 'enabled', 'NIBE Smart Control')

    @property
    def is_on(self):
        return self.controller.data['enabled']

    @property
    def extra_state_attributes(self):
        return {'controller_domain': DOMAIN, 'status': self.controller.status, 'targets': self.controller.targets,'control': self.controller.control,
                'learning':self.controller.learner.diagnostics(),
                'last_cycle': self.controller.data['last_cycle'],
                'last_attempt': self.controller.data['last_attempt']}

    async def async_turn_on(self, **kwargs):
        await self.controller.async_enable(True)

    async def async_turn_off(self, **kwargs):
        await self.controller.async_enable(False)


class InlineRequestsSwitch(ControllerEntity, SwitchEntity):
    _attr_icon = 'mdi:radiator'

    def __init__(self, controller):
        super().__init__(controller, 'inline_requests', 'NIBE Inline Heater Requests')

    @property
    def is_on(self):
        return self.controller.data['inline_requests_enabled']

    @property
    def extra_state_attributes(self):
        return {'nibe_inline_requests': True}

    async def async_turn_on(self, **kwargs):
        await self.controller.async_enable_inline_requests(True)

    async def async_turn_off(self, **kwargs):
        await self.controller.async_enable_inline_requests(False)
