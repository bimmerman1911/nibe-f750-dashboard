"""DHW mode policy, native charging estimate and local morning deadline."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def next_deadline(now, zone):
    local=datetime.fromtimestamp(now,ZoneInfo(zone))
    deadline=local.replace(hour=6,minute=0,second=0,microsecond=0)
    if deadline.timestamp()<=now:
        deadline=(local+timedelta(days=1)).replace(hour=6,minute=0,second=0,microsecond=0)
    return deadline.timestamp()


def policy(tank, charging, scheduled, now, model, *, allow_pause=False):
    """Normal only for the current reservation or a documented reserve override."""
    zone=model.get('timezone','Europe/Stockholm')
    full=model['tank_max_c']-.5
    deadline=next_deadline(now,zone)
    profile=model.get('dhw_profile',[model.get('dhw_draw_kw',.15)]*24)
    # Protect reserve until another cloud update can complete (normal 16-min cycle).
    draw=max(profile[datetime.fromtimestamp(now+i*60,ZoneInfo(zone)).hour] for i in range(0,21,5))
    loss=.0015*max(0,tank-20)
    deferred=tank-(draw+loss)/3/model.get('tank_capacity_kwh_per_k',.209)
    capacity=model['dhw_heat_kw']*model.get('dhw_fraction',.75)
    # Conservative capacity plus one write interval and 15 min timing margin.
    required=max(0,full-tank)*model.get('tank_capacity_kwh_per_k',.209)
    recovered=0.;lead=.5
    # Work backwards from 06:00 using the hours that actually precede it,
    # rather than treating the day's peak shower demand as a constant load.
    for quarter in range(96):
        hour=datetime.fromtimestamp(deadline-(quarter+.5)*900,ZoneInfo(zone)).hour
        recovered+=(.7*capacity-profile[hour]-loss)*.25
        lead=.5+(quarter+1)*.25
        if recovered>=required:
            break
    completed=bool(model.get('dhw_morning_completed',False))
    pending=model.get('dhw_morning_pending',False) and not completed
    morning=tank<full and (deadline-now<=lead*3600 or pending)
    # At/after 06:00, retain recovery if the target was missed; don't abandon it
    # just because the deadline advanced to tomorrow.
    local=datetime.fromtimestamp(now,ZoneInfo(zone))
    overdue=6<=local.hour<8 and tank<full and not completed
    low=tank<model['tank_min_c']+2 or deferred<model['tank_min_c']+2
    start=min(model['tank_max_c']-.5,model.get('dhw_start_c',model['tank_target_c']))
    # An explicitly planned Economy pause may interrupt a reserve top-up only
    # while a later Normal command can still start charging. Never strand a
    # partly warm tank above its native start threshold before the morning goal.
    economic_pause=bool(allow_pause and not scheduled and charging and not (morning or overdue or low)
                        and tank>=model['tank_min_c']+2.5 and tank<=start-.3)
    finish=charging and tank<full and not economic_pause
    reason='06:00 full-charge reserve' if morning or overdue else 'Low hot-water reserve' if low else 'Finishing necessary charge' if finish else 'Scheduled DHW period' if scheduled else 'Planned pause with restartable hot-water reserve' if economic_pause else 'Charging deferred'
    normal=scheduled or morning or overdue or low or finish
    return {'dhw':'Normal' if normal else 'Economy','dhw_reason':reason,
            'dhw_action':'Charge enabled' if normal else 'Deferred','dhw_deadline':deadline,
            'dhw_full_c':full,'dhw_morning_override':morning or overdue,'dhw_economic_pause':economic_pause}


def charge(tank, enabled, charging, dt, model, inline=0., draw=None):
    """Normal permits native hysteresis charging; it does not force full speed."""
    stop=model['tank_max_c']
    start=min(stop-.5,model.get('dhw_start_c',model['tank_target_c']))
    active=enabled and tank<stop-.1 and (charging or tank<=start)
    if not active:
        return 0.,0.,0.,False
    fraction=model.get('dhw_fraction',.75)
    q=model['dhw_heat_kw']*fraction
    demand=model.get('dhw_draw_kw',.15) if draw is None else draw
    needed=max(0.,(stop-tank)*model.get('tank_capacity_kwh_per_k',.209)/dt+demand+.0015*(tank-20))
    extra=min(inline,max(0.,needed-q))
    delivered=min(q,needed)
    return delivered+extra,fraction*delivered/q,extra,True
