"""Native heat-response transitions on the estimated thermal-input basis.

These helpers predict native behaviour. They never issue pump commands and do
not infer metered thermal power or COP from a frequency-based heat proxy.
"""
import math


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def response_step(heat, supply_error, degree_minutes, hours, theta, capacity):
    """Advance the learned *15-minute* ARX map over an arbitrary interval.

    For frozen supply error and degree minutes, q15 = c*q + u. The equivalent
    first-order transition has equilibrium u/(1-c) and decay c**(dt/0.25).
    Applying that transition in 1/5/15-minute subdivisions therefore has the
    same result before physical saturation. No extra, unlearned lag is added.
    """
    if (len(theta)!=4 or not all(_finite(v) for v in [heat,supply_error,degree_minutes,hours,capacity,*theta])
        or hours<0 or capacity<=0 or not 0<=theta[2]<1):
        raise ValueError('Invalid native response model or interval')
    if hours==0:
        return min(capacity,max(0.,heat))
    a,b,c,bias=theta
    u=a*supply_error+b*(-degree_minutes/100)+bias
    if c==0:
        predicted=u
    else:
        equilibrium=u/(1-c)
        predicted=equilibrium+(heat-equilibrium)*c**(hours/.25)
    return min(capacity,max(0.,predicted))


def emitter_estimate(sample, room, model, previous=None):
    """Calibrate effective emitter conductance from available heating readings.

    A near-capacity heating observation provides q/(Tsupply-Troom), using the
    same nominal-heat basis as the house model. This anchors attainable supply
    to observed operation instead of assuming the requested temperature can be
    reached. A lone snapshot is explicitly provisional: water warming and heat
    stored in pipes/emitters can bias this estimate. Normal-mode/DHW/off samples
    never replace a valid heating calibration.

    The returned small dictionary can be persisted by the caller and passed
    back as ``previous``. Calibration and covariance learning are separate.
    """
    prior=previous if isinstance(previous,dict) else {}
    old=prior.get('conductance_kw_per_k')
    valid_old=_finite(old) and .04<=old<=2.
    supply=sample.get('supply');heat=sample.get('heat');outside=sample.get('outside')
    capacity=model.get('compressor_heat_kw',4.2)
    if not (_finite(room) and _finite(capacity) and capacity>0):
        raise ValueError('Invalid emitter room/capacity input')
    delta=supply-room if _finite(supply) else None
    fraction=sample.get('fraction')
    near_capacity=(_finite(fraction) and fraction>=.9) if fraction is not None else (_finite(heat) and heat>=capacity*.9)
    usable=(sample.get('mode')=='Heating' and near_capacity and _finite(heat) and .2<=heat<=30
            and delta is not None and delta>=5 and 15<=supply<=80)
    if usable:
        measured=min(2.,max(.04,heat/delta))
        timestamp=sample.get('time')
        # Repeating a cached snapshot must not inflate the observation count.
        repeated=timestamp is not None and timestamp==prior.get('time') and valid_old
        if repeated:
            return dict(prior)
        raw_count=prior.get('observations',0)
        count=raw_count if valid_old and isinstance(raw_count,int) and not isinstance(raw_count,bool) and raw_count>=0 else 0
        fitted=.85*old+.15*measured if valid_old and count>0 else measured
        return {'conductance_kw_per_k':fitted,'observations':count+1,
                'source':'Observed heating proxy','confidence':'Provisional' if count<3 else 'Observed',
                'reference_supply_c':supply,'reference_heat_kw':heat,'time':timestamp}
    if valid_old:
        return dict(prior)
    # Startup prior only. It is not evidence of current attainable supply.
    h=model.get('heat_loss_kw_per_k',.1)
    gain=model.get('internal_gain_kw',0.)
    load=max(.1,h*(room-outside)-gain) if _finite(outside) and _finite(h) and _finite(gain) else capacity*.5
    conductance=min(2.,max(.04,load/max(5.,delta or 5.)))
    return {'conductance_kw_per_k':conductance,'observations':0,'source':'Initial emitter estimate','confidence':'Initial'}


def attainable_supply(room, heat_capacity, conductance):
    """Steady-state supply on the calibrated proxy basis; not a hard setpoint cap."""
    if not all(_finite(v) for v in (room,heat_capacity,conductance)) or heat_capacity<0 or conductance<=0:
        raise ValueError('Invalid attainable-supply inputs')
    return room+heat_capacity/conductance
