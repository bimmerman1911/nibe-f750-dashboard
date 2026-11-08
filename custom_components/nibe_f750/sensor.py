"""Controller status and Recorder telemetry."""
from datetime import datetime, timezone
from homeassistant.components.sensor import SensorEntity
from .controller import DOMAIN
from .entity import ControllerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ControlSensor(controller, False), ControlSensor(controller, True), ForecastSensor(controller), ModelSensor(controller), CostSensor(controller)])


class ControlSensor(ControllerEntity, SensorEntity):
    def __init__(self, controller, telemetry):
        self.telemetry = telemetry
        super().__init__(controller, 'telemetry' if telemetry else 'status',
            'NIBE control telemetry' if telemetry else 'NIBE Smart Control status')

    @property
    def native_value(self):
        if self.telemetry:
            return datetime.fromtimestamp(self.controller.last_sample, timezone.utc).isoformat()
        return self.controller.status

    @property
    def extra_state_attributes(self):
        if self.telemetry:
            return {'readings': self.controller.telemetry}
        return {'targets': self.controller.targets, 'last_cycle': self.controller.data['last_cycle'],
                'last_attempt': self.controller.data['last_attempt']}


class ForecastSensor(ControllerEntity, SensorEntity):
    def __init__(self, controller):
        super().__init__(controller, 'forecast', 'NIBE heating forecast')

    @property
    def native_value(self):
        return self.controller.forecast.get('status','Waiting for forecast')

    @property
    def extra_state_attributes(self):
        return {'controller_domain': DOMAIN, 'forecast': self.controller.forecast,
                'record_count':len(self.controller.prediction_log)}


class ModelSensor(ControllerEntity, SensorEntity):
    def __init__(self, controller):
        super().__init__(controller, 'model', 'NIBE adaptive model')

    @property
    def native_value(self):
        return self.controller.learner.diagnostics()['state']

    @property
    def extra_state_attributes(self):
        return {'controller_domain': DOMAIN, **self.controller.learner.diagnostics()}


class CostSensor(ControllerEntity, SensorEntity):
    def __init__(self, controller):
        super().__init__(controller, 'electricity_history', 'NIBE electricity history')

    @property
    def native_value(self):
        return 'Recording' if self.controller.costs else 'Starting'

    @property
    def extra_state_attributes(self):
        return {'controller_domain':DOMAIN,'electricity':self.controller.costs}
