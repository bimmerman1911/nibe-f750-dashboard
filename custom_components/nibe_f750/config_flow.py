"""One-time UI setup. Uses the existing myUplink integration."""
from math import isfinite

import voluptuous as vol
from homeassistant import config_entries
from .controller import DOMAIN
from .local_weather import DEFAULT_CORRECTION
from .predictive import DEFAULTS, active_compressor_heat


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
        phones = {'': 'Off'}
        phones.update({name: name.removeprefix('mobile_app_').replace('_', ' ').title()
                       for name in self.hass.services.async_services().get('notify', {})
                       if name.startswith('mobile_app_')})
        saved_phone = self._entry.options.get('inline_notify_service', '')
        if saved_phone not in phones:
            phones[saved_phone] = saved_phone + ' (unavailable)'
        errors = {}
        if user_input is not None:
            errors = {key: 'invalid_weather_parameter' for key, default in DEFAULT_CORRECTION.items()
                      if not isfinite(user_input.get(key, default))}
            values={**DEFAULTS, **user_input}
            if not (values['room_min_c']<=values['room_target_c']<=values['room_max_c'] and values['tank_min_c']<=values['tank_target_c']<=values['tank_max_c']):
                return self.async_abort(reason='invalid_bounds')
            if not errors:
                options = dict(user_input)
                if 'compressor_heat_kw' in self._entry.options:
                    options['compressor_heat_kw'] = self._entry.options['compressor_heat_kw']
                return self.async_create_entry(title='', data=options)
        fields={vol.Optional('weather_entity', default=self._entry.options.get('weather_entity','')): str}
        correction_fields = {
            'temperature_offset': vol.Coerce(float),
            'daily_amplitude': vol.All(vol.Coerce(float), vol.Range(min=0)),
            'peak_hour': vol.All(vol.Coerce(float), vol.Range(min=0, max=24, max_included=False)),
        }
        for key, validator in correction_fields.items():
            fields[vol.Optional(key, default=self._entry.options.get(key, DEFAULT_CORRECTION[key]))] = validator
        fields[vol.Optional('inline_notify_service', default=saved_phone)] = vol.In(phones)
        fields[vol.Optional('inline_max_kw', default=self._entry.options.get('inline_max_kw', 6.5))] = vol.In(
            [n / 2 for n in range(1, 14)])
        fields[vol.Optional('active_compressor_heat_kw', default=active_compressor_heat(self._entry.options))] = vol.All(
            vol.Coerce(float), vol.Range(min=1, max=10))
        limits={'heat_loss_kw_per_k':(.01,1), 'thermal_capacity_kwh_per_k':(2,100),
                'dhw_heat_kw':(1,10),'compressor_max_supply_diff_c':(1,25),
                'room_min_c':(16,23),'room_target_c':(17,24),'room_max_c':(18,25),
                'tank_min_c':(35,50),'tank_target_c':(40,55),'tank_max_c':(46,60)}
        for key,(low,high) in limits.items():
            fields[vol.Optional(key,default=self._entry.options.get(key,DEFAULTS[key]))]=vol.All(vol.Coerce(float),vol.Range(min=low,max=high))
        return self.async_show_form(step_id='init', data_schema=vol.Schema(fields), errors=errors)
