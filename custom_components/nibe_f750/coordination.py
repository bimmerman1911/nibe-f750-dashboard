"""Shared primary command commitment and power-dependent room response."""

COMMIT_SECONDS=2880.  # Three existing command periods; not a cloud-write timer.


def committed_offset(proposed,current,direction,changed,now,emergency=False):
    delta=proposed-current
    if not emergency and direction*delta<0 and 0<=now-changed<COMMIT_SECONDS:
        return current
    return proposed


def differential_rate(response,heat,capacity):
    cold=response.get('coasting_rate',0.)
    reference=max(.5,response.get('heating_kw',capacity))
    fraction=max(0.,min(1.,heat/reference))
    return cold+(response.get('heating_rate',0.)-cold)*fraction


def sustaining_supply_target(supply, degree_minutes, compressor_heat, theta):
    """Estimate a target that preserves current production at this deficit.

    Solve the native response's steady-output equation for supply error.
    Allow 1°C for supply drift plus at least 2°C positive error. As long as
    the supply stays within that allowance, degree minutes remain negative
    and the fitted output cannot decay from its current value.
    """
    supply_weight, deficit_weight, carry, bias = theta
    required_error = compressor_heat * (1 - carry) + deficit_weight * degree_minutes / 100 - bias
    if supply_weight <= 0 and required_error > 0:
        return None
    fitted_error = required_error / supply_weight if supply_weight > 0 else 0.
    return supply + 1 + max(2., fitted_error)
