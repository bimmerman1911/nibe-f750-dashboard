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
