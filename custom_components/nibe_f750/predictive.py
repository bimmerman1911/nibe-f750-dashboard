"""Price/weather planning model. Recommendations never dispatch pump commands."""
from datetime import datetime, timedelta
import math

DEFAULTS = {'heat_loss_kw_per_k': .10, 'thermal_capacity_kwh_per_k': 9.,
            'compressor_heat_kw': 4.2, 'dhw_heat_kw': 3.6,
            'room_min_c': 19., 'room_max_c': 20.5, 'room_target_c': 20.,
            'tank_min_c': 42., 'tank_max_c': 55., 'tank_target_c': 48.,
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


def thermal_step(room, tank, outdoor, dt, heat, water_heat, model):
    h,c=model['heat_loss_kw_per_k'],model['thermal_capacity_kwh_per_k']
    decay=math.exp(-h/c*dt)
    room=outdoor+(room-outdoor)*decay+heat/h*(1-decay)
    tank += (water_heat-model['dhw_draw_kw']-.0015*(tank-20))*dt/model['tank_capacity_kwh_per_k']
    return room,tank


def plan(slots, room, tank, max_hz=84., model=None, beam=140, min_hz=20.):
    m={**DEFAULTS, **(model or {})}
    if any(not math.isfinite(float(v)) or float(v)<=0 for v in m.values()):
        raise ValueError('Model assumptions must be positive finite numbers')
    if not (m['room_min_c'] <= m['room_target_c'] <= m['room_max_c'] and
            m['tank_min_c'] <= m['tank_target_c'] <= m['tank_max_c']):
        raise ValueError('Model targets are outside model bounds')
    if sum(s['dt'] for s in slots) < 6:
        return {'status':'Waiting for forecast', 'message':'At least six continuous hours of prices and weather are needed.', 'steps':[]}
    if not (5<=room<=35 and 10<=tank<=80 and 0<min_hz<=max_hz<=150):
        raise ValueError('Current model inputs are invalid')
    def solve(auxiliary):
        actions=[('off',0.,0.,0.,0.), ('heat',m['compressor_heat_kw']*max(.5,min_hz/max_hz),0.,max(min_hz,max_hz*.5),0.),
                 ('heat',m['compressor_heat_kw'],0.,max_hz,0.),('dhw',0.,m['dhw_heat_kw'],max_hz,0.)]
        if auxiliary:
            actions += [('heat',m['compressor_heat_kw']+1,0.,max_hz,1.),('dhw',0.,m['dhw_heat_kw']+1,max_hz,1.)]
        states=[(room,tank,0.,0.,None,None)]
        for i,s in enumerate(slots):
            unique={}
            progress=(i+1)/len(slots)
            for r,w,cost,aux,parent,step in states:
                for mode,qh,qw,hz,inline in actions:
                    nr,nw=thermal_step(r,w,s['outdoor'],s['dt'],qh,qw,m)
                    # If already outside bounds, permit recovery without worsening it.
                    if not min(room,m['room_min_c'])-1e-7<=nr<=max(room,m['room_max_c'])+1e-7:
                        continue
                    if not min(tank,m['tank_min_c'])-1e-7<=nw<=max(tank,m['tank_max_c'])+1e-7:
                        continue
                    bt12=55 if mode=='dhw' else 38
                    power=hz*(.0161+.000208*(bt12-45))
                    newcost=cost+(power+inline)*s['dt']*s['price']
                    newaux=aux+inline*s['dt']
                    node=(nr,nw,newcost,newaux,(r,w,cost,aux,parent,step),
                          {**s,'action':mode,'hz':hz,'inline_kw':inline,'room':nr,'water':nw,
                           'compressor_kw':power})
                    key=(round(nr*20),round(nw*4),mode)
                    old=unique.get(key)
                    if old is None or (newaux,newcost)<(old[3],old[2]):
                        unique[key]=node
            def rank(n):
                deficit=max(0,m['room_target_c']-n[0])**2*40+max(0,m['tank_target_c']-n[1])**2*2
                return (n[3], n[2]+progress**4*deficit)
            ordered=sorted(unique.values(), key=rank)
            # Preserve tank/room storage diversity before cost-only candidates.
            buckets={}
            for n in ordered:
                buckets.setdefault((int(n[0]*2),int(n[1]/2),n[5]['action']),n)
            states=list(buckets.values())[:beam]
            ids={id(n) for n in states}
            states += [n for n in ordered if id(n) not in ids][:beam-len(states)]
            if not states:
                return None
        feasible=[n for n in states if n[0]>=m['room_target_c'] and n[1]>=m['tank_target_c']]
        return min(feasible,key=lambda n:(n[3],n[2])) if feasible else None
    best=solve(False)
    compressor_only=best is not None
    best=best or solve(True)
    if best is None:
        return {'status':'Model cannot meet targets','message':'No schedule found within the assumed capacity and temperature limits.', 'steps':[]}
    steps=[]
    n=best
    while n[5] is not None:
        steps.append(n[5]);n=n[4]
    steps.reverse()
    action=steps[0]['action']
    recommendation={'off':'Use stored heat now','heat':'Build heating reserve','dhw':'Prepare hot water'}[action]
    if steps[0]['inline_kw']:
        recommendation='Extra heat in the model candidate'
    return {'status':'Recommendation available','message':recommendation,'steps':steps,
            'model_cost':best[2],'inline_kwh':best[3],'compressor_only':compressor_only,
            'model':m,'horizon_end':slots[-1]['end'],
            'scope':'Prediction and recommendation; current thermostat remains in control.',
            'assumptions':'Uncalibrated heat loss, storage and capacity; illustrative DHW draw allowance.'}
