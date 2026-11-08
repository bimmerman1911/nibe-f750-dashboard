"""Recorded 15-minute power/cost history and a labelled thermostat counterfactual."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
from .engine import fresh, number, ROOM1, ROOM2, PRICE
from .predictive import DEFAULTS, thermal_step, prices
from .adaptive import filtered_heat


def power(hz, bt12):
    return hz*(.0161+.000208*(bt12-45))


class Accounting:
    def __init__(self, timezone_name='Europe/Stockholm'):
        self.zone=ZoneInfo(timezone_name)
        self.bins={}
        self.days={}
        self.previous=None
        self.reference=None
        self.revision=0
        self.history_checked=False

    def restore(self, data):
        if isinstance(data,dict) and data.get('version')==1:
            self.bins={int(k):v for k,v in data.get('bins',{}).items()}
            self.days=data.get('days',{})
            self.history_checked=data.get('history_checked',False)
        # Do not bridge unobserved downtime or claim a continuous reference run.
        self.previous=self.reference=None

    def dump(self):
        return {'version':1,'bins':{str(k):v for k,v in self.bins.items()},'days':self.days,'history_checked':self.history_checked}

    def forecast(self, result, now):
        for s in result.get('steps',[]):
            if any(not isinstance(s.get(k),(int,float)) or not math.isfinite(s[k]) for k in ('start','end','compressor_kw','inline_kw','price')):
                continue
            start=math.floor(s['start']/900)*900
            if start < now-43200 or start > now+86400:
                continue
            row=self.bins.setdefault(start,{})
            # Once an interval has begun, preserve its as-issued prediction.
            if start>now or 'predicted_kw' not in row:
                row.update(predicted_kw=s['compressor_kw']+s['inline_kw'],price=s['price'],
                           action=s['action'],issued_at=result.get('generated_at',now))
        self.revision+=1

    def observe(self, states, now, learned, forecast):
        def value(e):
            s=states.get(e)
            return number(s.state) if fresh(s,now) else None
        hz=value('sensor.vp_current_compressor_frequency')
        bt12=value('sensor.vp_condenser_bt12')
        inline=value('sensor.vp_power_internal_add_heat')
        kw=None
        if hz is not None and 0<=hz<=150 and inline is not None and inline>=0 and (hz==0 or (bt12 is not None and -30<=bt12<=100)):
            kw=(power(hz,bt12) if hz else 0)+inline
            if not 0<=kw<=20:
                kw=None
        price=value(PRICE)
        if price is not None:
            unit=states[PRICE].attributes.get('unit_of_measurement','').lower().replace(' ','')
            scale={'sek/kwh':1,'sek/mwh':.001,'öre/kwh':.01,'ore/kwh':.01}.get(unit)
            price=price*scale if scale is not None else None
        if price is None and 0<=now-forecast.get('generated_at',0)<=1200:
            slot=next((s for s in forecast.get('steps',[]) if s['start']<=now<s['end']),None)
            price=number(slot.get('price')) if slot else None
        try:
            attrs=states[PRICE].attributes if PRICE in states else {}
            published=prices(list(attrs.get('raw_today') or [])+list(attrs.get('raw_tomorrow') or []) if attrs.get('tomorrow_valid') is not False else list(attrs.get('raw_today') or []),attrs.get('unit_of_measurement')) if attrs.get('raw_today') else []
        except (ValueError,KeyError,TypeError):
            published=[]
        limit=states.get('select.vp_set_max_electrical_add')
        try:
            auxiliary=max(0.,min(6.5,float(limit.state.lower().replace('kw','').strip()))) if fresh(limit,now) else None
        except (ValueError,AttributeError):
            auxiliary=None
        blocked=states.get('sensor.vp_int_elec_add_heat')
        if blocked and blocked.state=='Blocked':
            auxiliary=0.
        r1,r2,outside,top,bottom,maximum=(value(e) for e in (ROOM1,ROOM2,'sensor.vp_current_outd_temp_bt1',
            'sensor.vp_hot_water_top_bt7','sensor.vp_hot_water_charging_bt6','sensor.vp_max_compressor_frequency'))
        minimum=value('sensor.vp_min_compressor_frequency') or 20.
        current={'time':now,'kw':kw,'price':price,'outside':outside,'room':(r1+r2)/2 if r1 is not None and r2 is not None else None,
                 'tank':(top+bottom)/2 if top is not None and bottom is not None else None,'max_hz':maximum,'min_hz':minimum,'auxiliary':auxiliary}
        prev=self.previous;self.previous=current
        if prev is None or not 0<now-prev['time']<=180:
            self.reference=None
            self._prune(now)
            return
        # Integrate held observations over measured time, splitting quarter-hours
        # (and therefore local midnight) exactly. Missing data is not zero load.
        cursor=prev['time']
        while cursor<now:
            end=min(now,(math.floor(cursor/900)+1)*900)
            seconds=end-cursor;dt=seconds/3600
            start=math.floor(cursor/900)*900
            row=self.bins.setdefault(start,{})
            known=next((p for p in published if p['start']<=cursor<p['end']),None)
            if known is None and 0<=now-forecast.get('generated_at',0)<=1200:
                known=next((p for p in forecast.get('steps',[]) if p['start']<=cursor<p['end']),None)
            tariff=number(known.get('price')) if known else prev['price']
            if tariff is not None:
                row['price']=tariff
            if prev['kw'] is not None:
                row['observed_start']=min(cursor,row.get('observed_start',cursor))
                row['energy']=row.get('energy',0)+prev['kw']*dt
                row['seconds']=row.get('seconds',0)+seconds
            baseline=self._baseline(prev,dt,learned,datetime.fromtimestamp(cursor,self.zone).hour)
            # Compare costs on identical covered intervals only.
            if prev['kw'] is not None and tariff is not None:
                date=datetime.fromtimestamp(cursor,self.zone).date().isoformat()
                day=self.days.setdefault(date,{'actual':0.,'baseline':0.,'seconds':0.,'baseline_seconds':0.})
                day['actual']+=prev['kw']*dt*tariff
                day['seconds']+=seconds
                if baseline is not None:
                    day['baseline']+=baseline*dt*tariff
                    day['baseline_seconds']+=seconds
            cursor=end
        self.revision+=1
        self._prune(now)

    def _baseline(self, sample, dt, learned, hour):
        if any(sample[k] is None for k in ('outside','room','tank','max_hz','auxiliary')):
            self.reference=None
            return None
        if not (5<=sample['room']<=35 and 10<=sample['tank']<=80 and -50<=sample['outside']<=50
                and 0<sample['min_hz']<=sample['max_hz']<=150):
            self.reference=None
            return None
        m={**DEFAULTS,**learned}
        if self.reference is None:
            self.reference={'room':sample['room'],'tank':sample['tank'],'heat':m.get('initial_heat_kw',0.),'charging':False}
        r=self.reference
        if r['tank']<m['tank_target_c']:
            r['charging']=True
        if r['tank']>=m['tank_max_c']-.1:
            r['charging']=False
        extra=0.
        if r['charging']:
            qh=0.;qw=min(m['dhw_heat_kw'],max(0.,(m['tank_max_c']-r['tank'])*m['tank_capacity_kwh_per_k']/dt))
            fraction=qw/m['dhw_heat_kw'];bt12=55
            if r['tank']<m['tank_min_c']:
                extra=min(sample['auxiliary'],max(0.,(m['tank_target_c']-r['tank'])*m['tank_capacity_kwh_per_k']-m['dhw_heat_kw']))
                qw+=extra
        else:
            # Ordinary fixed 20°C thermostat, with no price anticipation.
            load=m['heat_loss_kw_per_k']*(20-sample['outside'])-m.get('internal_gain_kw',0)+(20-r['room'])*m['thermal_capacity_kwh_per_k']/2
            qh=min(m['compressor_heat_kw'],max(0.,load)) if r['room']<20.2 else 0.
            if qh>0:
                qh=max(qh,m['compressor_heat_kw']*sample['min_hz']/sample['max_hz'])
            qw=0.;fraction=qh/m['compressor_heat_kw'];bt12=38
            if r['room']<19.8:
                extra=min(sample['auxiliary'],max(0.,load-m['compressor_heat_kw']))
                qh+=extra
        hz=sample['max_hz']*min(1.,fraction)
        r['heat'],delivered=filtered_heat(r['heat'],qh,dt,m.get('heating_lag_hours',0.))
        draw=m.get('dhw_profile',[m['dhw_draw_kw']]*24)[hour]
        r['room'],r['tank']=thermal_step(r['room'],r['tank'],sample['outside'],dt,delivered,qw,m,draw)
        return power(hz,bt12)+extra

    def _prune(self, now):
        self.bins={k:v for k,v in self.bins.items() if now-14*86400<=k<=now+86400}
        oldest=(datetime.fromtimestamp(now,self.zone).date()-timedelta(days=14)).isoformat()
        self.days={k:v for k,v in self.days.items() if k>=oldest}

    def merge_history(self, old, cutoff):
        for t, historical in old.bins.items():
            if t>cutoff:
                continue
            current=self.bins.get(t,{})
            merged={**historical,**current}
            if t<=cutoff and 'predicted_kw' in historical:
                for key in ('predicted_kw','issued_at','action'):
                    merged[key]=historical.get(key)
            for key in ('energy','seconds'):
                if key in historical or key in current:
                    merged[key]=historical.get(key,0)+current.get(key,0)
            self.bins[t]=merged
        for date,day in old.days.items():
            current=self.days.get(date,{'actual':0.,'baseline':0.,'seconds':0.,'baseline_seconds':0.})
            self.days[date]={key:current[key]+day[key] for key in current}
        self.history_checked=True
        self.revision+=1

    def view(self, now):
        today=datetime.fromtimestamp(now,self.zone).date()
        monday=today-timedelta(days=today.weekday())
        week=[]
        for i in range(7):
            date=monday+timedelta(days=i)
            data=self.days.get(date.isoformat()) if date<=today else None
            week.append({'date':date.isoformat(),'actual':data['actual'] if data else None,
                         'baseline':data['baseline'] if data and data.get('baseline_seconds',0)>=data['seconds']-1e-6 else None,'covered_hours':data['seconds']/3600 if data else 0.})
        history=[{'start':t,'end':t+900,'price':v.get('price'),'predicted_kw':v.get('predicted_kw'),
                  'actual_kw':v['energy']/(v['seconds']/3600) if v.get('seconds') else None,
                  'action':v.get('action'),'covered_seconds':v.get('seconds',0)}
                 for t,v in sorted(self.bins.items()) if now-44100<=t<=now+43200]
        return {'updated_at':now,'history':history,'week':week,'timezone':str(self.zone),'currency':'SEK',
                'basis':'Observed power/cost are estimates from compressor frequency/BT12 plus reported inline power. Baseline is a fixed-20°C/Normal-DHW thermal simulation, not a measured saving. Baseline is shown only for fully matched recorded cost intervals; missing history stays blank.'}
