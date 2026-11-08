"""Learned native-actuator response and receding-horizon offset search.

Heat is a nominal thermal proxy, not a meter reading. Degree minutes remain
owned by NIBE; simulation never writes degree minutes or compressor frequency.
"""
import math
from .engine import C1, REQUIRED, SUPPLY, PRIORITY, fresh, number
from .adaptive import bounded, filtered_heat
from .predictive import thermal_step
from .dhw import policy, charge

DM='sensor.vp_degree_minutes_2'

class OffsetLearner:
    def __init__(self):
        self.bank={'theta':[.35,.25,.75,0.], 'p':[[1. if i==j else 0. for j in range(4)] for i in range(4)]}
        self.gain=2.5
        self.start_dm=-60.
        self.aux_dm=-700.
        self.count=0
        self.error=0.
        self.previous=None
        self.anchor=None
        self.revision=0

    def dump(self):
        return {'version':1,'bank':self.bank,'gain':self.gain,'count':self.count,'error':self.error,'start_dm':self.start_dm,'aux_dm':self.aux_dm}

    def restore(self,data):
        try:
            assert data['version']==1 and 1<=data['gain']<=5 and data['count']>=0
            theta=data['bank']['theta'];p=data['bank']['p']
            assert len(theta)==4 and len(p)==4 and all(len(r)==4 for r in p)
            assert all(math.isfinite(v) for v in theta+[v for r in p for v in r])
            assert all(lo<=v<=hi for v,(lo,hi) in zip(theta,((0,2),(0,2),(0,.98),(-2,2))))
            assert all(p[i][i]>0 for i in range(4)) and math.isfinite(data['error'])
            assert -1500<=data.get('start_dm',-60)<=-1 and -3000<=data.get('aux_dm',-700)<=-1
            self.start_dm=data.get('start_dm',-60);self.aux_dm=data.get('aux_dm',-700)
            self.bank=data['bank'];self.gain=data['gain'];self.count=data['count'];self.error=data['error']
            return True
        except (KeyError,TypeError,ValueError,AssertionError):
            return False

    def update(self,states,now,capacity):
        sample=inputs(states,now,capacity)
        prev=self.previous;self.previous=sample
        if sample is None or prev is None or not 0<now-prev['time']<=180:
            self.anchor=None
            return
        if sample['mode']=='Heating' and prev['mode'] in ('Heating','Off'):
            if sample['compressor_on'] and not prev['compressor_on'] and -1500<=sample['dm']<-1:
                self.start_dm=.85*self.start_dm+.15*sample['dm'];self.revision+=1
            if sample['inline']>.1 and prev['inline']<=.1 and -3000<=sample['dm']<-1:
                self.aux_dm=.85*self.aux_dm+.15*sample['dm'];self.revision+=1
        # Identify curve shift only across isolated offset changes in stable weather.
        delta=sample['offset']-prev['offset']
        if abs(delta)>=.5 and abs(sample['outside']-prev['outside'])<.2:
            slope=(sample['required']-prev['required'])/delta
            if 1<=slope<=5:
                self.gain=.9*self.gain+.1*slope;self.revision+=1
        if sample['mode']!='Heating' or prev['mode']!='Heating':
            self.anchor=None
            return
        # Fit stable-setting windows; a direct jump starts a fresh window.
        if abs(delta)>1e-6:
            self.anchor=sample
            return
        if self.anchor is None:
            self.anchor=sample
            return
        a=self.anchor
        if now-a['time']<900:
            return
        self.anchor=sample
        if now-a['time']>1080:
            return
        x=[a['required']-a['supply'],-a['dm']/100,a['heat'],1.]
        theta,p=self.bank['theta'],self.bank['p']
        error=sample['heat']-sum(v*w for v,w in zip(theta,x))
        self.error=.95*self.error+.05*abs(error)
        px=[sum(r[j]*x[j] for j in range(4)) for r in p]
        denominator=.1+sum(x[i]*px[i] for i in range(4))
        if denominator<=0:
            return
        for i,(lo,hi) in enumerate(((0,2),(0,2),(0,.98),(-2,2))):
            theta[i]=bounded(theta[i]+px[i]/denominator*bounded(error,-1,1),lo,hi)
        self.bank['p']=[[(p[i][j]-px[i]*px[j]/denominator)/.999 for j in range(4)] for i in range(4)]
        self.count+=1;self.revision+=1

    def parameters(self):
        return {'theta':self.bank['theta'][:],'offset_gain':self.gain,'start_dm':self.start_dm,'aux_dm':self.aux_dm,'windows':self.count,'error_kw':self.error}


def inputs(states,now,capacity):
    ids=(C1,REQUIRED,SUPPLY,DM,'sensor.vp_current_compressor_frequency',
         'sensor.vp_max_compressor_frequency','sensor.vp_power_internal_add_heat','sensor.vp_current_outd_temp_bt1')
    values=[number(states[e].state) if fresh(states.get(e),now) else None for e in ids]
    mode=states.get(PRIORITY)
    if None in values or not fresh(mode,now):
        return None
    offset,required,supply,dm,hz,maximum,inline,outside=values
    if not (0<maximum<=150 and 0<=hz<=150 and -3000<=dm<=1000 and 5<=required<=80 and 5<=supply<=90 and 0<=inline<=10):
        return None
    if any('defrost' in states[e].state.lower() for e in ('sensor.vp_status','sensor.vp_status_compressor') if e in states):
        return None
    return {'time':now,'offset':offset,'required':required,'supply':supply,'dm':dm,
            'heat':capacity*min(1,hz/maximum)+inline if mode.state=='Heating' else 0.,
            'outside':outside,'mode':mode.state,'compressor_on':hz>0,'inline':inline}


def offset_levels(control):
    """All values on the native entity's min/step grid, not a slew limit."""
    lower,upper=(number(control.attributes.get(k)) for k in ('min','max'))
    step=number(control.attributes.get('step',1.))
    if lower is None or upper is None or step is None or step<=0 or lower>upper:
        return []
    count=math.floor((upper-lower)/step+1e-8)+1
    # Invalid metadata must not allocate an unbounded search space.
    if count>2048:
        return []
    return [round(lower+i*step,10) for i in range(count)]


def plan_offsets(result,states,now,response,min_hz,max_hz,budget=None):
    """Beam-search offset sequences against a simulated native heat response.

    The thermal scheduler supplies prices/weather and hot-water reservation.
    Space heating is re-simulated from offsets, supply error and degree minutes.
    """
    m=result.get('model',{});slots=result.get('steps',[])
    sample=inputs(states,now,m.get('compressor_heat_kw',4.2))
    if not sample or not slots:
        return None
    control=states[C1]
    levels=offset_levels(control)
    if not levels or not levels[0]<=sample['offset']<=levels[-1]:
        return None
    gain=response.get('offset_gain',2.5);theta=response.get('theta',[.35,.25,.75,0.])
    cap=m['compressor_heat_kw'];lo=m['room_min_c'];hi=m['room_max_c'];target=m['room_target_c']
    room=result['initial_room'];water=result['initial_water']
    room_ids=('sensor.ovanvaning_temperature','sensor.nedervaning_temperature')
    spread=max(abs(float(states[e].state)-room) for e in room_ids)
    base_load=max(.1,m['heat_loss_kw_per_k']*(room-sample['outside'])-m.get('internal_gain_kw',0))
    # Effective emitter conductance: prevents instantaneous water/room response.
    conductance=bounded(base_load/max(5,sample['supply']-room),.05,1.)
    initial={'room':room,'water':water,'dm':sample['dm'],'supply':sample['supply'],
             'heat':sample['heat'],'stored':m.get('initial_heat_kw',sample['heat']),
             'morning_pending':m.get('dhw_morning_pending',False),'charging':sample['mode']=='Hot water' and sample['compressor_on'],'running':sample['heat']>0,'offset':sample['offset'],'cost':0.,'penalty':0.,'path':[]}
    beam=[initial]
    for slot in slots:
        if budget is not None:
            budget.check()
        dt=(slot['end']-slot['start'])/3600
        candidates=[]
        for prev in beam:
            if budget is not None:
                budget.check()
            for offset in levels:
                change=offset-prev['offset']
                required=sample['required']+gain*(offset-sample['offset'])-1.2*(slot['outdoor']-sample['outside'])
                required=bounded(required,15,60)
                r,w,dm,supply,heat,stored=(prev[k] for k in ('room','water','dm','supply','heat','stored'))
                energy=aux_energy=0.
                any_dhw=False
                decision=policy(w,prev['charging'],slot.get('dhw_mode')=='Normal' if 'dhw_mode' in slot else slot['action']=='dhw',slot['start'],{**m,'dhw_morning_pending':prev['morning_pending']})
                charging=prev['charging']
                normal=decision['dhw']=='Normal'
                running=prev['running']
                # Five-minute substeps retain backlog and delayed response without
                # the former one-minute workload on small HA hosts.
                n=max(1,math.ceil(dt*12));h=dt/n
                for _ in range(n):
                    draw=m.get('dhw_profile',[m['dhw_draw_kw']]*24)[slot.get('local_hour',0)]
                    water_heat,water_fraction,water_inline,charging=charge(w,normal,charging,h,m,slot['inline_kw'],draw)
                    dhw=water_fraction>0
                    any_dhw=any_dhw or dhw
                    demand=max(0.,sum(a*b for a,b in zip(theta,[required-supply,-dm/100,heat,1.])))
                    demand=min(cap+m.get('auxiliary_limit_kw',0),demand)
                    heat+=(demand-heat)*(1-math.exp(-h/.25))
                    if dm>=0:
                        running=False
                    elif dm<=response.get('start_dm',-60):
                        running=True
                    compressor=0. if dhw or not running else min(cap,heat)
                    if compressor>0:
                        compressor=max(compressor,cap*min_hz/max_hz)
                    # Auxiliary is a prediction of native operation, never a command.
                    auxiliary=0. if dhw or dm>response.get('aux_dm',-700) else min(m.get('auxiliary_limit_kw',0),max(0,heat-cap))
                    q=compressor+auxiliary
                    if not dhw:
                        dm=bounded(dm+(supply-required)*h*60,-3000,1000)
                    equilibrium=r+q/conductance
                    supply=bounded(supply+bounded((equilibrium-supply)*(1-math.exp(-h/.5)),-120*h,120*h),15,80)
                    stored,delivered=filtered_heat(stored,q,h,m.get('heating_lag_hours',1))
                    draw=m.get('dhw_profile',[m['dhw_draw_kw']]*24)[slot.get('local_hour',0)]
                    r,w=thermal_step(r,w,slot['outdoor'],h,delivered,water_heat,m,draw)
                    hz=max_hz*water_fraction if dhw else max_hz*compressor/cap
                    bt12=m.get('dhw_supply_c',55) if dhw else supply
                    extra=water_inline if dhw else auxiliary
                    energy+=(hz*(.0161+.000208*(bt12-45))+extra)*h
                    aux_energy+=extra*h
                violation=max(0,lo+spread-r)**2+max(0,r+spread-hi)**2
                penalty=prev['penalty']+2000*violation*dt+100*aux_energy+.025*abs(change)
                cost=prev['cost']+energy*slot['price']
                point={**slot,'room':r,'water':w,'offset':offset,'degree_minutes':dm,
                       'dhw_mode':decision['dhw'],'dhw_reason':decision['dhw_reason'],'action':'dhw' if any_dhw else 'heat' if energy> .02*dt else 'off',
                       'compressor_kw':(energy-aux_energy)/dt,'inline_kw':aux_energy/dt,'hz':hz}
                candidates.append({'room':r,'water':w,'dm':dm,'supply':supply,'heat':heat,'stored':stored,
                                   'morning_pending':decision['dhw_morning_override'],'charging':charging,'running':running,'offset':offset,'cost':cost,'penalty':penalty,'path':prev['path']+[point]})
        if not candidates:
            return None
        rank=lambda p:p['cost']+p['penalty']+20*max(0,target-p['room'])**2
        unique={}
        for p in sorted(candidates,key=rank):
            key=(round(p['offset'],2),round(p['room']*20),round(p['dm']/50),round(p['heat']*2),p['charging'])
            unique.setdefault(key,p)
        beam=list(unique.values())[:12]
    best=min(beam,key=lambda p:p['cost']+p['penalty']+200*max(0,target-p['room'])**2)
    return {**result,'steps':best['path'],'model_cost':best['cost'],
            'inline_kwh':sum(s['inline_kw']*(s['end']-s['start'])/3600 for s in best['path']),
            'compressor_only':all(s['inline_kw']<.01 for s in best['path']),
            'dhw_deadline_shortfall_c':sum(max(0,m['tank_max_c']-.5-s['water']) for s in best['path'] if s.get('dhw_deadline')),
            'offset_response':response,'control_basis':'Offset optimisation with degree-minute and supply response',
            'message':'Recovery plan: restoring heating and hot-water reserves with available capacity' if result.get('recovery_plan') else 'Offsets planned from prices, weather and learned heat response'}
