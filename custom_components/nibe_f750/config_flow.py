"""One-time UI setup. Uses the existing myUplink integration."""
import voluptuous as vol
from homeassistant import config_entries
from .controller import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            if not self.hass.config_entries.async_entries('myuplink'):
                errors['base'] = 'myuplink_required'
            else:
                return self.async_create_entry(title='NIBE F750 Smart Control', data={})
        return self.async_show_form(step_id='user', data_schema=vol.Schema({}), errors=errors)
