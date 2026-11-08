"""One-time UI setup. Uses the existing myUplink integration."""
import voluptuous as vol
from homeassistant import config_entries
from .controller import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlow(config_entry)

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


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            from .predictive import DEFAULTS
            values={**DEFAULTS, **user_input}
            if not (values['room_min_c']<=values['room_target_c']<=values['room_max_c'] and values['tank_min_c']<=values['tank_target_c']<=values['tank_max_c']):
                return self.async_abort(reason='invalid_bounds')
            return self.async_create_entry(title='', data=user_input)
        from .predictive import DEFAULTS
        fields={vol.Optional('weather_entity', default=self._entry.options.get('weather_entity','')): str}
        limits={'heat_loss_kw_per_k':(.01,1), 'thermal_capacity_kwh_per_k':(2,100),
                'compressor_heat_kw':(1,10),'dhw_heat_kw':(1,10),
                'room_min_c':(16,23),'room_target_c':(17,24),'room_max_c':(18,25),
                'tank_min_c':(35,50),'tank_target_c':(40,55),'tank_max_c':(46,60)}
        for key,(low,high) in limits.items():
            fields[vol.Optional(key,default=self._entry.options.get(key,DEFAULTS[key]))]=vol.All(vol.Coerce(float),vol.Range(min=low,max=high))
        return self.async_show_form(step_id='init', data_schema=vol.Schema(fields))
