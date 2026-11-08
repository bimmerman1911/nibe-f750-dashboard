"""Optional learning reset; never sends a NIBE setting request."""
from homeassistant.components.button import ButtonEntity
from .controller import DOMAIN
from .entity import ControllerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ResetLearning(hass.data[DOMAIN][entry.entry_id])])


class ResetLearning(ControllerEntity, ButtonEntity):
    _attr_icon = 'mdi:brain'

    def __init__(self, controller):
        super().__init__(controller, 'reset_learning', 'Reset NIBE learning')

    async def async_press(self):
        await self.controller.async_reset_learning()
