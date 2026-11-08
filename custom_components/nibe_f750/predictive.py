"""Receding-horizon thermal scheduling for the adaptive supervisor."""
from datetime import datetime, timedelta
import math
from dataclasses import dataclass
from .dhw import charge

DEFAULTS = {'heat_loss_kw_per_k': .10, 'thermal_capacity_kwh_per_k': 9.,
            'compressor_heat_kw': 4.2, 'dhw_heat_kw': 3.6,
            'room_min_c': 19., 'room_max_c': 20.5, 'room_target_c': 20.,
            'tank_min_c': 42., 'tank_max_c': 52., 'tank_target_c': 48.,
            'tank_capacity_kwh_per_k': .209, 'dhw_draw_kw': .15}


def timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('Forecast timestamps require timezone offsets')
    return value.timestamp()


def numeric(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Missing numeric forecast value')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite forecast value')
    return result


def prices(rows, unit):
    unit = (unit or '').lower().replace(' ', '')
    scale = {'sek/kwh':1, 'sek/mwh':.001, 'öre/kwh':.01, 'ore/kwh':.01}.get(unit)
    if scale is None:
        raise ValueError('Price units must be SEK/kWh, SEK/MWh or öre/kWh')
    result = sorted([{'start':timestamp(r['start']), 'end':timestamp(r['end']),
                      'price':numeric(r.get('value', r.get('price')))*scale} for r in rows], key=lambda p:p['start'])
    for i, row in enumerate(result):
        if row['end'] <= row['start'] or (i and row['start'] < result[i-1]['end']):
            raise ValueError('Overlapping or invalid price intervals')
    return result


def timeline(price_rows, weather, now, unit='°C'):
    if unit not in ('°C','°F'):
        raise ValueError('Weather temperature units are missing')
    forecast = sorted([(timestamp(w['datetime']), numeric(w['temperature'])) for w in weather])
    if unit == '°F':
        forecast = [(t,(v-32)*5/9) for t,v in forecast]
    if any(forecast[i][0] == forecast[i-1][0] for i in range(1,len(forecast))):
        raise ValueError('Duplicate forecast timestamps')
    slots=[]
    cursor=now
    limit=min(now+86400, price_rows[-1]['end'] if price_rows else now, forecast[-1][0] if forecast else now)
    while cursor < limit:
        row=next((p for p in price_rows if p['start'] <= cursor < p['end']),None)
        if row is None:
            break
        end=min(limit,row['end'],(math.floor(cursor/900)+1)*900)
        mid=(cursor+end)/2
        pair=next(((a,b) for a,b in zip(forecast,forecast[1:]) if a[0] <= mid < b[0]),None)
        if pair is None or pair[1][0]-pair[0][0] > 10800:
            break
        a,b=pair
        slots.append({'start':cursor,'end':end,'dt':(end-cursor)/3600,
                      'price':row['price'],'outdoor':a[1]+(b[1]-a[1])*(mid-a[0])/(b[0]-a[0])})
        cursor=end
    return slots


def thermal_step(room, tank, outdoor, dt, heat, water_heat, model, draw=None):
    h,c=model['heat_loss_kw_per_k'],model['thermal_capacity_kwh_per_k']
    decay=math.exp(-h/c*dt)
    room=outdoor+(room-outdoor)*decay+(heat+model.get('internal_gain_kw',0))/h*(1-decay)
    demand=model['dhw_draw_kw'] if draw is None else draw
    tank += (water_heat-demand-.0015*(tank-20))*dt/model['tank_capacity_kwh_per_k']
    return room,tank


@dataclass(slots=True)
class Node:
    room: float
    water: float
    heat: float
    mode: str
    run: float
    off: float
    mode_time: float
    cost: float
    aux: float
    parent: object = None
    step: object = None
    charging: bool = False
    miss: float = 0.
    violation: float = 0.


def plan(slots, room, tank, max_hz=84., model=None, beam=180, min_hz=20.):
    from .adaptive import filtered_heat
    m={**DEFAULTS, **(model or {})}
    for key in DEFAULTS:
        value=m[key]
        if not math.isfinite(float(value)) or (value < 0 if key=='dhw_draw_kw' else value <= 0):
            raise ValueError('Model assumptions must be finite and physically valid')
    for key in ('internal_gain_kw','heating_lag_hours','initial_heat_kw','auxiliary_step_kw'):
        if key in m and (not math.isfinite(float(m[key])) or (key!='internal_gain_kw' and m[key]<0)):
            raise ValueError('Invalid adaptive model parameter')
    profile=m.get('dhw_profile')
    if profile is not None and (len(profile)!=24 or any(not math.isfinite(v) or v<0 for v in profile)):
        raise ValueError('Invalid learned hot-water profile')
    if not (m['room_min_c'] <= m['room_target_c'] <= m['room_max_c'] and
            m['tank_min_c'] <= m['tank_target_c'] <= m['tank_max_c']):
        raise ValueError('Model targets are outside model bounds')
    if sum(s['dt'] for s in slots) < 6:
        return {'status':'Waiting for forecast', 'message':'At least six continuous hours of prices and weather are needed.', 'steps':[]}
    if not (5<=room<=35 and 10<=tank<=80 and 0<min_hz<=max_hz<=150):
        raise ValueError('Current model inputs are invalid')
    def solve(auxiliary,width,recovery=False):
        actions=[('off',0.,0.,0.,0.), ('heat',m['compressor_heat_kw']*max(.5,min_hz/max_hz),0.,max(min_hz,max_hz*.5),0.),
                 ('heat',m['compressor_heat_kw'],0.,max_hz,0.),('dhw',0.,m['dhw_heat_kw'],max_hz,0.)]
        limit=m.get('auxiliary_limit_kw',m.get('auxiliary_step_kw',1.))
        if auxiliary and limit>0:
            stages=sorted({min(limit,v) for v in (.5,1.,2.,3.,4.,5.,6.5)})
            for extra in stages:
                actions += [('heat',m['compressor_heat_kw']+extra,0.,max_hz,extra),
                            ('dhw',0.,m['dhw_heat_kw']+extra,max_hz,extra)]
        initial_mode=m.get('initial_mode','off')
        states=[Node(room,tank,m.get('initial_heat_kw',0.),initial_mode,m.get('initial_run_minutes',30.),m.get('initial_off_minutes',15.),m.get('initial_mode_minutes',15.),0.,0.)]
        for i,s in enumerate(slots):
            unique={}
            progress=(i+1)/len(slots)
            for prev in states:
                for mode,qh,qw,hz,inline in actions:
                    draw=profile[s.get('local_hour',0)] if profile is not None else m['dhw_draw_kw']
                    if mode=='dhw':
                        qw,fraction,inline,charging=charge(prev.water,True,prev.charging or (i==0 and initial_mode=='dhw'),s['dt'],m,inline,draw)
                        hz=max_hz*fraction
                    else:
                        charging=False
                    on=hz>0
                    previous_on=prev.step['hz']>0 if prev.step is not None else initial_mode!='off'
                    if on and not previous_on and prev.off<15-1e-6:
                        continue
                    if not on and previous_on and prev.run<30-1e-6 and not (prev.charging and prev.water>=m['tank_max_c']-.1):
                        continue
                    if mode!='off' and prev.mode!='off' and mode!=prev.mode and prev.mode_time<15-1e-6:
                        continue
                    stored,delivered=filtered_heat(prev.heat,qh,s['dt'],m.get('heating_lag_hours',0.))
                    draw=profile[s.get('local_hour',0)] if profile is not None else m['dhw_draw_kw']
                    nr,nw=thermal_step(prev.room,prev.water,s['outdoor'],s['dt'],delivered,qw,m,draw)
                    if not (min(room,16.) if recovery else min(room,m['room_min_c']))-1e-7<=nr<=max(room,m['room_max_c'])+1e-7:
                        continue
                    if not (min(tank,30.) if recovery else min(tank,m['tank_min_c']))-1e-7<=nw<=max(tank,m['tank_max_c'])+1e-7:
                        continue
                    bt12=m.get('dhw_supply_c',55) if mode=='dhw' else m.get('supply_c',38)
                    power=hz*(.0161+.000208*(bt12-45))
                    minutes=s['dt']*60
                    node=Node(nr,nw,stored,mode,
                        min(30.,prev.run+minutes) if on and previous_on else min(30.,minutes) if on else 0.,
                        0. if on else min(15.,prev.off+minutes),
                        min(15.,prev.mode_time+minutes) if mode==prev.mode else min(15.,minutes),
                        prev.cost+(power+inline)*s['dt']*s['price'],prev.aux+inline*s['dt'],prev,
                        {**s,'action':mode,'hz':hz,'inline_kw':inline,'room':nr,'water':nw,
                         'compressor_kw':power,'delivered_heat_kw':delivered,'dhw_mode':'Normal' if mode=='dhw' else 'Economy'},charging=charging,violation=prev.violation+s['dt']*(2000*max(0,m['room_min_c']-nr)**2+200*max(0,m['tank_min_c']-nw)**2),miss=prev.miss+(max(0,m['tank_max_c']-.5-nw) if s.get('dhw_deadline') else 0))
                    key=(round(nr*20),round(nw*4),round(stored*2),mode,round(node.run),round(node.off),round(node.mode_time),charging)
                    old=unique.get(key)
                    if old is None or ((node.miss,node.violation,node.aux,node.cost)<(old.miss,old.violation,old.aux,old.cost) if recovery else (node.miss,node.aux,node.cost)<(old.miss,old.aux,old.cost)):
                        unique[key]=node
            def rank(n):
                next_due=next((q['end'] for q in slots[i:] if q.get('dhw_deadline')),None)
                urgent=0 if next_due is None else 100*max(0,m['tank_max_c']-.5-n.water)**2/(1+(next_due-s['end'])/3600)**2
                deficit=max(0,m['room_target_c']-n.room)**2*40+max(0,m['tank_target_c']-n.water)**2*2
                return (n.violation+progress**4*deficit*100,n.miss,n.aux,n.cost+urgent) if recovery else (n.miss,n.aux,n.cost+progress**4*deficit+urgent)
            ordered=sorted(unique.values(),key=rank)
            buckets={}
            for n in ordered:
                buckets.setdefault((int(n.room*2),int(n.water/2),n.mode),n)
            states=list(buckets.values())[:width]
            ids={id(n) for n in states}
            states += [n for n in ordered if id(n) not in ids][:width-len(states)]
            if not states:
                return None
        feasible=states if recovery else [n for n in states if n.room>=m['room_target_c']-1e-7 and n.water>=m['tank_target_c']-1e-7]
        return min(feasible,key=lambda n:(n.violation+4000*max(0,m['room_target_c']-n.room)**2+400*max(0,m['tank_target_c']-n.water)**2,n.miss,n.aux,n.cost) if recovery else (n.miss,n.aux,n.cost)) if feasible else None
    best=solve(False,beam)
    if best is None:
        best=solve(False,beam*3)
    compressor_only=best is not None
    if best is None or best.miss>.1:
        supported=solve(True,beam)
        if supported is not None and (best is None or (supported.miss,supported.aux,supported.cost)<(best.miss,best.aux,best.cost)):
            best=supported
    recovery=False
    if best is None:
        recovery=True
        best=solve(False,beam,True)
        if m.get('auxiliary_limit_kw',m.get('auxiliary_step_kw',1.))>0:
            supported=solve(True,beam,True)
            def recovery_rank(n):
                return (n.violation+4000*max(0,m['room_target_c']-n.room)**2+400*max(0,m['tank_target_c']-n.water)**2,n.miss,n.aux,n.cost)
            if supported is not None and (best is None or recovery_rank(supported)<recovery_rank(best)):
                best=supported
    compressor_only=best is not None and best.aux<.01
    if best is None:
        return {'status':'No feasible schedule','message':'Using thermostat control: no schedule found within capacity and comfort limits.', 'steps':[]}
    steps=[]
    n=best
    while n.step is not None:
        steps.append(n.step);n=n.parent
    steps.reverse()
    action=steps[0]['action']
    description={'off':'Using stored heat','heat':'Building heating reserve','dhw':'Preparing hot water'}[action]
    if recovery:
        description='Recovery plan: restoring comfort with available capacity and heat delay'
    return {'status':'Adaptive schedule','message':description,'steps':steps,
            'recovery_plan':recovery,'constraint_violation_score':best.violation,'dhw_deadline_shortfall_c':best.miss,'model_cost':best.cost,'inline_kwh':best.aux,'compressor_only':compressor_only,
            'model':m,'horizon_end':slots[-1]['end'],
            'scope':'Active supervisory control through heating targets and DHW comfort mode.'}
