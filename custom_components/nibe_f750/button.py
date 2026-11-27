"""Local learning and inline approval buttons."""
from datetime import datetime

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from .controller import DOMAIN
from .entity import ControllerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    entities = [ResetLearning(controller)]
    if controller.inline_service:
        entities.append(ApproveInlinePlan(controller))
    async_add_entities(entities)


class ResetLearning(ControllerEntity, ButtonEntity):
    _attr_icon = 'mdi:brain'

    def __init__(self, controller):
        super().__init__(controller, 'reset_learning', 'Reset NIBE learning')

    async def async_press(self):
        await self.controller.async_reset_learning()


class ApproveInlinePlan(ControllerEntity, ButtonEntity):
    _attr_icon = 'mdi:radiator'

    def __init__(self, controller):
        super().__init__(controller, 'approve_inline_plan', 'Approve NIBE inline plan')

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.controller.inline_approval_entity = self.entity_id
        self.async_on_remove(lambda: setattr(self.controller, 'inline_approval_entity', None))

    @property
    def available(self):
        return self.controller.inline_approval_pending

    @property
    def extra_state_attributes(self):
        if not self.available:
            return {}
        windows = self.controller.inline.offer['windows']
        zone = self.controller.accounting.zone

        def local(timestamp):
            return datetime.fromtimestamp(timestamp, zone).strftime('%a %H:%M')

        return {'approve_before': local(windows[0]['start']),
                'planned_windows': [f"{local(w['start'])}–{local(w['end'])} · up to {w['kw']:g} kW"
                                    for w in windows]}

    async def async_press(self):
        if not await self.controller.async_respond_inline(approve_current=True):
            raise HomeAssistantError('There is no inline heating plan awaiting approval.')
