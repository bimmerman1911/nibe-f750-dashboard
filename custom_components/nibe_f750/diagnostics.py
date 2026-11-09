"""Local model diagnostics, downloadable through HA's integration UI."""
from .controller import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    controller = hass.data[DOMAIN][entry.entry_id]
    return {'status':controller.status, 'control':controller.control,
            'learning':controller.learner.diagnostics(),
            'offset_response':controller.offset_learner.dump(),
            'targets':controller.targets, 'write_timestamps':{
                k:controller.data[k] for k in ('last_cycle','last_attempt')},
            'planning':controller.forecast.get('planning',{}),
            'emitter_calibration':controller.forecast.get('emitter',{}),
            'command_preview':controller.forecast.get('commands',[])[:8],
            'morning_completed_date':controller.data.get('dhw_morning_completed_date'),
            'forecast_model':controller.forecast.get('model',{}),
            'forecast_summary':{k:controller.forecast.get(k) for k in
                ('status','message','generated_at','horizon_end','initial_room','initial_water','model_cost','inline_kwh','recovery_plan','constraint_violation_score','dhw_deadline_shortfall_c','planner','dhw_auxiliary_uncertain')},
            'model_state':controller.learner.dump(),
            'recent_decisions':controller.decision_log[-32:],
            'current_inputs':controller.telemetry}
