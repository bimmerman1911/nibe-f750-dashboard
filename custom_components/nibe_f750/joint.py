"""Joint receding-horizon search over commands the integration can actually send.

All heat/power remain model estimates. Native firmware owns the actuators.
Commands respect write timing; price/weather intervals remain quarter-hourly.
"""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import math
from statistics import median
from time import monotonic
from .engine import ROOM1, ROOM2, C1, C2, SUPPLY, REQUIRED, DHW, fresh, number
from .offset import inputs, offset_levels
from .native import response_step, emitter_estimate, attainable_supply, primary_degree_minutes_step
from .adaptive import filtered_heat
from .predictive import DEFAULTS, thermal_step
from .dhw import policy, charge, next_deadline
from .timing import improve as improve_timing
from .work import ReservedBudget

COMMAND_SECONDS=960.
# SEK per squared degree-hour inside the uncertainty buffer. Actual configured
# limits remain lexicographic constraints; marginal buffer risk has finite cost.
COMFORT_RISK_PRICE=100.

@dataclass(frozen=True, slots=True)
class DeferHeat:
    until: float
    bridge: bool=False


def cheaper_windows(slots, now):
    """Find explicit later buying opportunities across all known intervals.

    Average prices over real durations (including partial quarters). Retain
    both an early meaningful price drop and the cheapest two-hour window;
    physics and comfort are checked by the complete command simulation.
    """
    if not slots:return []
    windows=[]
    for i,row in enumerate(slots):
        if row['start']<now+COMMAND_SECONDS:continue
        stop=min(row['start']+7200,slots[-1]['end'])
        duration=sum(max(0,min(s['end'],stop)-s['start']) for s in slots[i:] if s['start']<stop)
        if duration<3600:continue
        price=sum(s['price']*max(0,min(s['end'],stop)-s['start']) for s in slots[i:] if s['start']<stop)/duration
        windows.append((row['start'],price))
    if not windows:return []
    # A tiny price change is not a reason by itself to create a defer family.
    drop=max(.05,abs(slots[0]['price'])*.05)
    useful=[r for r in windows if r[1]<slots[0]['price']-drop]
    if not useful:return []
    first=useful[0];best=min(useful,key=lambda r:r[1])
    selected=[first]
    if best[0]-first[0]>=3600:selected.append(best)
    return [time for time,_ in selected]


@dataclass(slots=True)
class State:
    room: float
    water: float
    supply: float
    heat: float
    stored: float
    dm: float
    running: bool
    charging: bool
    pending: bool
    offset: float
    mode: str
    cost: float=0.
    penalty: float=0.
    aux: float=0.
    shortfall: float=0.
    parent: object=None
    command: object=None
    pieces: object=None
    completed_day: str=''
    violation: float=0.
    room_delta: float=0.
    comfort_risk: float=0.


def selection_key(result):
    """Price optimisation within configured comfort and morning reserves.

    In-band temperature preferences cannot buy extra expensive heat. Only
    necessary endpoint reserves carry value into the next horizon. Uncertainty
    buffer exposure has finite cost, so tiny differences cannot override price.
    """
    return (result['constraint_violation_score'],result['morning_shortfall'],
            result['selection_score'][1]+COMFORT_RISK_PRICE*result.get('comfort_risk',0.),result['inline_kwh'],
            result['objective_components']['control_penalties'])


def plan(slots, states, now, model=None, response=None, min_hz=20., max_hz=84.,
         command_not_before=None, budget=None, emitter=None, width=18, incumbent=None):
    """Compare complete price-aware rollouts with the bounded beam search.

    Rollouts retain deliberate coasting paths that a prefix-ranked beam can
    discard before delayed heat/cost effects become visible. Every candidate
    uses the same native simulation, reserve policy and objective.
    """
    started=monotonic()
    results=[]
    keep=bool(incumbent and 0<=now-incumbent.get('generated_at',0)<=1200 and incumbent.get('commands'))
    windows=cheaper_windows(slots,now)
    strategies=(['previous'] if keep else [])+['flex']+[DeferHeat(t,bridge) for t in windows for bridge in (False,True)]+[-3., -10., 0.]
    for strategy in strategies:
        if budget:
            budget.check_cancelled()
            if results and budget.remaining()<3.:break
        result=_search(slots,states,now,model,response,min_hz,max_hz,
            command_not_before,budget,emitter,width=4,strategy=strategy,incumbent=incumbent if keep else None)
        results.append(result)
    base_search_complete=len(results)==len(strategies)
    # Try removing near-term heating while retaining the entire later plan.
    # Unlike an all-day defer template, this tests a local timing correction.
    seed=min(results,key=selection_key)
    lower=offset_levels(states[C1])[0]
    deadlines=sorted(set([now+1800,now+3600,now+7200]+windows[:1]))
    for until in deadlines:
        if budget:
            budget.check_cancelled()
            if budget.remaining()<4.:break
        commands=[{**c,'offset':lower} if not c.get('locked') and c['start']<until else dict(c) for c in seed['commands']]
        if commands==seed['commands']:continue
        candidate=_search(slots,states,now,model,response,min_hz,max_hz,
            command_not_before,budget,emitter,width=4,strategy='previous',
            incumbent={'commands':commands})
        candidate['planning']['strategy']='coast-patch until '+str(int(until))
        candidate['planning']['defer_until']=until
        results.append(candidate)
    if budget is None or budget.remaining()>=6.:
        results.append(_search(slots,states,now,model,response,min_hz,max_hz,
            command_not_before,ReservedBudget(budget,3.) if budget else None,emitter,width=width))
    base_search_complete=base_search_complete and (budget is None or any(r['planning']['strategy']=='beam' for r in results))
    best=min(results,key=selection_key)
    seed=best
    expanded=sum(r['planning']['expanded'] for r in results)
    def replay(commands):
        return _search(slots,states,now,model,response,min_hz,max_hz,
            command_not_before,budget,emitter,width=1,strategy='previous',incumbent={'commands':commands})
    alternatives=[r for r in results if r['planning']['strategy'] in ('price-aware previous','price-aware flex')]
    best=improve_timing(seed,slots,offset_levels(states[C1]),replay,selection_key,budget,alternatives=alternatives)
    if best is not seed:results.append(best)
    best['planning']['search_seconds']=round(monotonic()-started,3)
    best['planning']['total_expanded']=expanded+best['planning']['timing_comparison']['expanded']
    best['planning']['price_lookahead_hours']=(slots[-1]['end']-now)/3600
    best['planning']['defer_until_candidates']=windows
    best['planning']['candidate_schedules']=len(results)
    best['planning']['selected_strategy']=best['planning']['strategy']
    best['planning']['candidate_costs']=[{'strategy':r['planning']['strategy'],
        'cost':r['model_cost'],'violation':r['constraint_violation_score'],
        'objective':r['selection_score'][1],'ranked_objective':selection_key(r)[2],'morning_shortfall':r['morning_shortfall'],'comfort_risk':r['comfort_risk'],**r['objective_components'],'defer_until':r['planning'].get('defer_until')} for r in results]
    best['planning']['search_limited']=any(r['planning']['search_limited'] for r in results) or not base_search_complete or best['planning']['timing_comparison']['budget_limited']
    return best


def _search(slots, states, now, model=None, response=None, min_hz=20., max_hz=84.,
         command_not_before=None, budget=None, emitter=None, width=18, strategy=None, incumbent=None):
    m={**DEFAULTS,**(model or {})};response=response or {}
    def numeric(key, low, high):
        try:value=float(m[key])
        except (KeyError,TypeError,ValueError):raise ValueError('Invalid model parameter: '+key)
        if not math.isfinite(value) or not low<=value<=high:raise ValueError('Invalid model parameter: '+key)
        m[key]=value
    for key,lo,hi in (('heat_loss_kw_per_k',.001,15),('thermal_capacity_kwh_per_k',1,200),
                      ('compressor_heat_kw',.1,20),('dhw_heat_kw',.1,20),('tank_capacity_kwh_per_k',.01,5),
                      ('room_min_c',5,35),('room_target_c',5,35),('room_max_c',5,35),
                      ('tank_min_c',10,80),('tank_target_c',10,80),('tank_max_c',20,80)):
        numeric(key,lo,hi)
    for key,default,lo,hi in (('internal_gain_kw',0,-10,20),('heating_lag_hours',1,0,12),
                            ('initial_heat_kw',0,0,30),('auxiliary_limit_kw',0,0,10),
                            ('dhw_fraction',.75,.05,1),('dhw_start_c',m['tank_target_c'],10,80),
                            ('dhw_supply_c',55,10,100),('response_uncertainty_c',.2,0,5)):
        m.setdefault(key,default);numeric(key,lo,hi)
    sample=inputs(states,now,m['compressor_heat_kw'])
    if sample is None:
        raise ValueError('Fresh degree minutes, supply and compressor readings are required for joint planning')
    if not slots or slots[0]['start']>now+1 or slots[-1]['end']<=now:
        raise ValueError('No continuous known-price and weather interval is available')
    if not 0<min_hz<=max_hz<=150:
        raise ValueError('Invalid compressor frequency limits')
    def read(e):
        s=states.get(e)
        v=number(s.state) if fresh(s,now) else None
        if v is None:raise ValueError('Fresh room, tank and comfort-mode readings are required')
        return v
    rooms=[read(ROOM1),read(ROOM2)]
    room=sum(rooms)/2
    water=(read('sensor.vp_hot_water_top_bt7')+read('sensor.vp_hot_water_charging_bt6'))/2
    native_mode=states.get(DHW)
    if not fresh(native_mode,now) or native_mode.state not in ('Normal','Economy','Lux'):
        raise ValueError('Native DHW comfort mode is unavailable')
    if not all(5<=r<=35 for r in rooms) or not 10<=water<=80:
        raise ValueError('Room or tank reading is outside the physical model range')
    if not m['room_min_c']<=m['room_target_c']<=m['room_max_c']:
        raise ValueError('Configured comfort bounds are inconsistent')
    requested_tank_target=m['tank_target_c']
    native_goal_limited=requested_tank_target>m['tank_max_c'] or m['tank_min_c']>m['tank_max_c']
    m['tank_target_c']=min(requested_tank_target,m['tank_max_c'])
    levels=offset_levels(states[C1])
    if not levels:raise ValueError('Native offset limits are unavailable')
    previous_end=now
    if slots[-1]['end']>now+86400+1:raise ValueError('Planning horizon exceeds 24 hours')
    for s in slots:
        if not all(isinstance(s.get(k),(int,float)) and math.isfinite(s[k]) for k in ('start','end','price','outdoor')) or abs(s['start']-previous_end)>1e-3 or s['end']<=s['start']:
            raise ValueError('Invalid or discontinuous planning timeline')
        previous_end=s['end']
    reference_hz=m.get('frequency_reference_hz',max_hz)
    if not isinstance(reference_hz,(int,float)) or not math.isfinite(reference_hz) or not max_hz<=reference_hz<=150:raise ValueError('Invalid frequency reference')
    cap=m['compressor_heat_kw']*max_hz/reference_hz
    m['dhw_fraction']=min(m['dhw_fraction'],max_hz/reference_hz)
    aux_limit=max(0,m.get('auxiliary_limit_kw',0.))
    calibration=emitter_estimate({**sample,'time':sample.get('measurement_time',sample['time'])},room,m,emitter)
    conductance=calibration['conductance_kw_per_k']
    theta=response.get('theta',[.35,.25,.75,0.])
    gain=response.get('offset_gain',2.5)
    if not isinstance(gain,(int,float)) or not math.isfinite(gain) or not 0<gain<=10:raise ValueError('Invalid native offset gain')
    uncertainty=min(.25,max(.05,m.get('response_uncertainty_c',.2)*.5),max(0,(m['room_max_c']-m['room_min_c'])/4))
    gap=min(rooms)-room;warm_gap=max(rooms)-room
    room_response=m.get('room_response',{})
    rates=[room_response.get(k,0.) for k in ('coasting_rate','heating_rate')]
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>.3 for v in rates):raise ValueError('Invalid differential room response')
    def cold_room(n):
        return n.room+min(rooms[0]-room+n.room_delta,rooms[1]-room-n.room_delta)
    profile=m.get('dhw_profile',[m['dhw_draw_kw']]*24)
    if len(profile)!=24 or any(not math.isfinite(v) or v<0 for v in profile):raise ValueError('Invalid hourly DHW profile')
    zone=ZoneInfo(m.get('timezone','Europe/Stockholm'))
    end=slots[-1]['end']
    earliest=max(now,command_not_before or now)
    # A future gate is observed on the next minute tick; plan conservatively.
    if earliest>now+1:earliest=min(end,now+math.ceil((earliest-now)/60.)*60.)
    first=State(room,water,sample['supply'],sample['heat'],m.get('initial_heat_kw',sample['heat']),
                sample['dm'],sample['compressor_on'],sample['mode']=='Hot water' and sample['compressor_on'],
                m.get('dhw_morning_pending',False),sample['offset'],native_mode.state)
    if m.get('dhw_morning_completed'):
        first.completed_day=datetime.fromtimestamp(now,zone).date().isoformat()
    beam=[first];cursor=now;slot_index=0;expanded=0;limited=False
    # Endpoint energy has an economic value, not a fixed 20°C equality/penalty.
    tail_price=max(0.,median([s['price'] for s in slots[-max(1,min(24,len(slots))):]]))
    reference_power=max(.1,max_hz*(.0161+.000208*(38-45)))
    heat_price=tail_price/max(1.5,cap/reference_power)
    def terminal(n):
        load=max(0,m['heat_loss_kw_per_k']*(n.room-slots[-1]['outdoor'])-m.get('internal_gain_kw',0.))
        in_transit=max(0,n.stored-load)*m.get('heating_lag_hours',0.)
        deficit=max(0,(m['room_min_c']+uncertainty-cold_room(n))*m['thermal_capacity_kwh_per_k']-in_transit)
        water_deficit=max(0,m['tank_min_c']+2-n.water)*m['tank_capacity_kwh_per_k']
        return heat_price*(deficit+water_deficit)
    while cursor<end-1e-6:
        if budget:
            if hasattr(budget,'remaining') and budget.remaining()<3.:limited=True
            budget.check_cancelled() if limited else budget.check()
        holding=cursor<earliest-1e-6
        stop=min(end,earliest if holding else cursor+COMMAND_SECONDS)
        while slot_index<len(slots)-1 and slots[slot_index]['end']<=cursor+1e-6:slot_index+=1
        chunks=[];j=slot_index;t=cursor
        while t<stop-1e-6:
            s=slots[j];until=min(stop,s['end'])
            if until<=t:raise ValueError('Invalid or discontinuous planning timeline')
            chunks.append({**s,'start':t,'end':until,'local_hour':datetime.fromtimestamp(t,zone).hour})
            t=until
            if t<stop-1e-6:j+=1
        candidates=[]
        due=next_deadline(stop-1e-4,str(zone))
        hours_to_due=max(0.,(due-stop)/3600)
        mean_draw=sum(profile[datetime.fromtimestamp(stop+(i+.5)*900,zone).hour] for i in range(max(1,math.ceil(hours_to_due*4))))/max(1,math.ceil(hours_to_due*4))
        def deadline_risk(n):
            if due>end+1e-5:return 0.
            full=m['tank_max_c']-.5
            if hours_to_due<=1e-6:return max(0,full-n.water)
            cooling=mean_draw+.0015*max(0,n.water-20)
            threshold=min(m['tank_max_c']-.5,m.get('dhw_start_c',m['tank_target_c']))
            wait=0. if n.charging and n.water<m['tank_max_c']-.1 else max(0,n.water-threshold)*m['tank_capacity_kwh_per_k']/max(.01,cooling)
            cooled=n.water-cooling*min(wait,hours_to_due)/m['tank_capacity_kwh_per_k']
            achievable=min(m['tank_max_c'],cooled+max(0,m['dhw_heat_kw']*m.get('dhw_fraction',.75)-cooling)*max(0,hours_to_due-wait)/m['tank_capacity_kwh_per_k'])
            return max(0,full-achievable)
        for previous in beam[:1] if limited else beam:
            if budget:
                if hasattr(budget,'remaining') and budget.remaining()<3.:limited=True
                budget.check_cancelled() if limited else budget.check()
            reserve=policy(previous.water,previous.charging,False,cursor,
                           {**m,'dhw_morning_pending':previous.pending,'dhw_morning_completed':previous.completed_day==datetime.fromtimestamp(cursor,zone).date().isoformat()},allow_pause=True)
            modes=[previous.mode] if holding else ['Economy','Normal']
            # Forced reserve/charge completion collapses equivalent choices.
            if not holding and reserve['dhw']=='Normal':modes=['Normal']
            offsets=[previous.offset] if holding else levels
            if limited and not holding:
                cheap=chunks[0]['price']<=median([s['price'] for s in slots[slot_index:]])
                preferred=m['room_target_c'] if cheap else m['room_min_c']+uncertainty+.3
                load=m['heat_loss_kw_per_k']*(preferred-chunks[0]['outdoor'])-m.get('internal_gain_kw',0.)
                need=max(0.,min(cap,load+(preferred-cold_room(previous))*m['thermal_capacity_kwh_per_k']/2))
                desired_supply=previous.room+need/conductance+1.5
                wanted=sample['offset']+(desired_supply-sample['required']+1.2*(chunks[0]['outdoor']-sample['outside']))/gain
                offsets=[min(levels,key=lambda v:abs(v-wanted))]
                if reserve['dhw']=='Normal':modes=['Normal']
                else:modes=['Normal' if cheap and previous.water<=m.get('dhw_start_c',m['tank_target_c']) else 'Economy']
            if strategy is not None and not holding:
                # Compare the current price to known later prices, never a
                # hard-coded clock window. Restore heat ahead of a predicted
                # comfort shortfall, including heat already in transit.
                cheap=chunks[0]['price']<=median([s['price'] for s in slots[slot_index:]])
                future=sorted(s['price'] for s in slots[slot_index:])
                low,high=future[len(future)//5],future[min(len(future)-1,4*len(future)//5)]
                value=max(0.,min(1.,(high-chunks[0]['price'])/max(.1,high-low)))
                floor=min(m['room_target_c'],m['room_min_c']+uncertainty+.15)
                target=floor+(m['room_target_c']-floor)*value
                cheap=value>=.5
                delay=max(.5,m.get('heating_lag_hours',1.))
                load=max(0.,m['heat_loss_kw_per_k']*(cold_room(previous)-chunks[0]['outdoor'])-m.get('internal_gain_kw',0.))
                projected=cold_room(previous)+(previous.stored-load)*delay/m['thermal_capacity_kwh_per_k']
                need=max(0.,min(cap,load+(target-projected)*m['thermal_capacity_kwh_per_k']/delay))
                desired=previous.room+need/conductance
                wanted=sample['offset']+(desired-sample['required']+1.2*(chunks[0]['outdoor']-sample['outside']))/gain
                if not cheap and isinstance(strategy,(int,float)) and projected>m['room_min_c']+uncertainty:
                    wanted=strategy
                offsets=[min(levels,key=lambda v:abs(v-wanted))]
                if isinstance(strategy,DeferHeat):
                    # Before the cheaper window, either coast strictly or
                    # supply only a modelled comfort bridge. They are separate
                    # complete alternatives; neither bypasses actual limits.
                    target=m['room_target_c'] if cursor>=strategy.until else min(m['room_target_c'],m['room_min_c']+uncertainty+.1)
                    need=max(0.,min(cap,load+(target-projected)*m['thermal_capacity_kwh_per_k']/delay))
                    desired=previous.room+need/conductance
                    wanted=sample['offset']+(desired-sample['required']+1.2*(chunks[0]['outdoor']-sample['outside']))/gain
                    offsets=[min(levels,key=lambda v:abs(v-wanted))] if cursor>=strategy.until or strategy.bridge else [levels[0]]
                if strategy=='previous':
                    old=next((c for c in incumbent['commands'] if c['start']<=cursor<c['end']),None)
                    if old and number(old.get('offset')) is not None and old.get('dhw_mode') in ('Economy','Normal'):
                        offsets=[min(levels,key=lambda v:abs(v-float(old['offset']))) ]
                        modes=['Normal' if reserve['dhw']=='Normal' else old['dhw_mode']]
            for offset in offsets:
                for mode in modes:
                    expanded+=1
                    r,w,supply,heat,stored,dm=(getattr(previous,k) for k in ('room','water','supply','heat','stored','dm'))
                    running=previous.running;charging=previous.charging;completed_day=previous.completed_day
                    room_delta=previous.room_delta;comfort_risk=previous.comfort_risk
                    pending=reserve['dhw_morning_override'] if not holding else previous.pending
                    cost=previous.cost;penalty=previous.penalty;auxiliary_energy=previous.aux
                    miss=previous.shortfall;pieces=[];violation=previous.violation
                    for chunk in chunks:
                        dt=(chunk['end']-chunk['start'])/3600
                        n=max(1,math.ceil(dt*12));h=dt/n
                        energy=extra_energy=0.;water_minutes=0.;min_room=r;activity=[]
                        required=max(15.,min(60.,sample['required']+gain*(offset-sample['offset'])
                                            -1.2*(chunk['outdoor']-sample['outside'])))
                        for k in range(n):
                            draw=profile[chunk['local_hour']]
                            observed_aux=min(aux_limit,sample['inline']) if sample['mode']=='Hot water' else 0.
                            qw,fraction,water_aux,charging=charge(w,mode!='Economy',charging,h,m,observed_aux,draw)
                            dhw=fraction>0
                            heat=response_step(heat,required-supply,dm,h,theta,cap+aux_limit)
                            if dm>=0:running=False
                            elif dm<=response.get('start_dm',-60):running=True
                            compressor=0. if dhw or not running else max(cap*min_hz/max_hz,min(cap,heat))
                            extra=0. if dhw or dm>response.get('aux_dm',-700) else min(aux_limit,max(0,heat-cap))
                            q=compressor+extra
                            if not dhw:dm=primary_degree_minutes_step(dm,supply,required,h)
                            equilibrium=r+q/conductance
                            supply=max(15.,min(80.,supply+(equilibrium-supply)*(1-math.exp(-h/.5))))
                            stored,delivered=filtered_heat(stored,q,h,m.get('heating_lag_hours',1.))
                            r,w=thermal_step(r,w,chunk['outdoor'],h,delivered,qw,m,draw)
                            hz=reference_hz*fraction if dhw else max_hz*compressor/cap
                            bt12=m.get('dhw_supply_c',55.) if dhw else supply+1.5
                            power=max(0,hz*(.0161+.000208*(bt12-45)))
                            energy+=(power+extra+water_aux)*h;extra_energy+=(extra+water_aux)*h
                            water_minutes+=h*60 if dhw else 0
                            activity_start=chunk['start']+k*h*3600
                            activity_end=chunk['start']+(k+1)*h*3600
                            activity_mode='dhw' if dhw else 'heat' if power+extra>.02 else 'off'
                            inline=extra+water_aux
                            if activity and activity[-1][2]==activity_mode and bool(activity[-1][3])==bool(inline):
                                a,b,mode_old,kw=activity[-1]
                                activity[-1]=(a,activity_end,mode_old,(kw*(b-a)+inline*(activity_end-activity_start))/(activity_end-a))
                            else:activity.append((activity_start,activity_end,activity_mode,inline))
                            rate=rates[0]+(rates[1]-rates[0])*min(1.,q/.5)
                            target_delta=2.*rate
                            room_delta=target_delta+(room_delta-target_delta)*math.exp(-h/2.)
                            room1=r+rooms[0]-room+room_delta;room2=r+rooms[1]-room-room_delta
                            cold=min(room1,room2);warm=max(room1,room2);min_room=min(min_room,cold)
                            below=max(0,m['room_min_c']+uncertainty-cold)
                            above=max(0,warm-m['room_max_c']+uncertainty)
                            tank_below=max(0,m['tank_min_c']+1-w)
                            # Soft uncertainty buffer; actual configured bounds are
                            # protected separately by the violation objective.
                            comfort_risk+=h*(max(0,below-.02)**2+max(0,above-.02)**2)
                            violation+=h*(max(0,m['room_min_c']-cold)**2+max(0,warm-m['room_max_c'])**2+.1*max(0,m['tank_min_c']-w)**2)
                            penalty+=h*(1200*(below*below+above*above)+150*tank_below*tank_below
                                        +.05*(r-m['room_target_c'])**2+40*(extra+water_aux))
                            # At saturation, do not reward requesting temperatures
                            # far beyond measured emitter capacity indefinitely.
                            if compressor>=cap*.95:
                                excess=max(0,required-attainable_supply(r,cap,conductance)-3)
                                penalty+=h*.03*excess*excess
                            moment=chunk['start']+(k+1)*h*3600
                            if w>=m['tank_max_c']-.5:
                                pending=False
                                local=datetime.fromtimestamp(moment,zone)
                                if local.hour>=6:completed_day=local.date().isoformat()
                            crossed_deadline=next_deadline(moment-h*3600, str(zone))
                            if moment-h*3600<crossed_deadline<=moment+1e-5:
                                short=max(0,m['tank_max_c']-.5-w)
                                miss+=short;penalty+=300*short*short
                        cost+=energy*chunk['price'];auxiliary_energy+=extra_energy
                        pieces.append({**chunk,'activity':activity,'offset':offset,'dhw_mode':mode,
                            'dhw_reason':reserve['dhw_reason'] if reserve['dhw']=='Normal' or mode=='Economy' else 'Scheduled DHW period',
                            'action':'dhw' if water_minutes else 'heat' if energy>.02*dt else 'off',
                            'room':r,'room1':room1,'room2':room2,'water':w,
                            'compressor_kw':(energy-extra_energy)/dt,'inline_kw':extra_energy/dt,
                            'hz':hz,'degree_minutes':dm,'required_supply':required,
                            'supply':supply,'coldest_room':min_room})
                    if not holding and strategy!='previous' and mode=='Normal' and reserve['dhw']=='Economy' and not any(q['action']=='dhw' for q in pieces):
                        continue
                    if not holding:
                        penalty+=.015*abs(offset-previous.offset)+(.025 if mode!=previous.mode else 0)
                    command={'economic_pause':bool(mode=='Economy' and reserve.get('dhw_economic_pause')), 'start':cursor,'end':stop,'offset':offset,'dhw_mode':mode,
                             'locked':holding,'action':'dhw' if any(q['action']=='dhw' for q in pieces) else 'heat' if any(q['action']=='heat' for q in pieces) else 'off','reason':(reserve['dhw_reason'] if reserve['dhw']=='Normal' else 'Scheduled DHW period') if mode=='Normal' else 'Price and stored-heat optimisation'}
                    candidates.append(State(r,w,supply,heat,stored,dm,running,charging,pending,offset,mode,
                        cost,penalty,auxiliary_energy,miss,previous,command,pieces,completed_day=completed_day,violation=violation,room_delta=room_delta,comfort_risk=comfort_risk))
        rank=lambda n:(n.violation,n.shortfall+deadline_risk(n),n.cost+terminal(n)+COMFORT_RISK_PRICE*n.comfort_risk,n.aux,n.penalty)
        candidates.sort(key=rank)
        diverse={}
        for n in candidates:
            key=(round(n.room*10),round(n.water*2),round(n.dm/150),round(n.supply/3),round(n.stored),round(n.heat),n.mode,n.running,n.charging,n.pending,n.offset,round(n.room_delta*20))
            diverse.setdefault(key,n)
        pool=list(diverse.values())
        # Preserve storage and degree-minute frontiers. Running/charging state
        # and pending commands are not interchangeable physical trajectories.
        selected=[]
        for mode in ('Economy','Normal'):
            group=[n for n in pool if n.mode==mode]
            if group:
                selected.append(group[0])
                for frontier in (max(group,key=lambda n:n.room+n.stored*.03),min(group,key=lambda n:n.room+n.stored*.03),max(group,key=lambda n:n.dm),min(group,key=lambda n:n.dm)):
                    if all(frontier is not q for q in selected):selected.append(frontier)
        for n in pool:
            if len(selected)>=width:break
            if all(n is not q for q in selected):selected.append(n)
        beam=sorted(selected,key=rank)
        if not beam:raise ValueError('No bounded joint plan found')
        cursor=stop
    best=min(beam,key=lambda n:(n.violation,n.shortfall,n.cost+terminal(n)+COMFORT_RISK_PRICE*n.comfort_risk,n.aux,n.penalty))
    commands=[];pieces=[];node=best
    while node.parent is not None:
        commands.append(node.command);pieces.extend(reversed(node.pieces));node=node.parent
    commands.reverse();pieces.reverse()
    # Merge split command segments back into original price/weather intervals.
    output=[]
    for s in slots:
        matches=[q for q in pieces if s['start']<=q['start']<s['end']]
        if not matches:continue
        duration=sum(q['end']-q['start'] for q in matches)
        last=matches[-1]
        output.append({**s,**{k:last[k] for k in ('offset','dhw_mode','dhw_reason','room','room1','room2','water','hz','degree_minutes','required_supply','supply')},
            'compressor_kw':sum(q['compressor_kw']*(q['end']-q['start']) for q in matches)/duration,
            'inline_kw':sum(q['inline_kw']*(q['end']-q['start']) for q in matches)/duration,
            'activity':[{'start':a,'end':b,'action':mode,'inline_kw':kw} for q in matches for a,b,mode,kw in q['activity']],
            'action':'dhw' if any(q['action']=='dhw' for q in matches) else 'heat' if any(q['action']=='heat' for q in matches) else 'off'})
    recovery=any(min(s['room1'],s['room2'])<m['room_min_c'] or max(s['room1'],s['room2'])>m['room_max_c'] or s['water']<m['tank_min_c'] for s in output)
    current=next((c for c in commands if c['start']<=max(now,earliest)<c['end']),commands[0])
    reason=('Recovering comfort and reserves' if recovery else 'Preparing hot water in a planned charging window' if current['dhw_mode']=='Normal'
            else 'Balancing electricity price, stored heat and indoor comfort')
    return {'status':'Adaptive schedule','planner':'joint','message':reason,'steps':output,'commands':commands,
        'model':m,'initial_room':room,'initial_water':water,'horizon_end':end,'model_cost':best.cost,
        'inline_kwh':best.aux,'compressor_only':best.aux<.01,'dhw_auxiliary_uncertain':aux_limit>0,'recovery_plan':recovery,'constraint_violation_score':best.violation,
        'dhw_deadline_shortfall_c':best.shortfall,'emitter':calibration,
        'planning':{'defer_until':strategy.until if isinstance(strategy,DeferHeat) else None,'strategy':'beam' if strategy is None else ('defer-bridge' if strategy.bridge else 'defer')+' until '+str(int(strategy.until)) if isinstance(strategy,DeferHeat) else 'price-aware '+str(strategy),'expanded':expanded,'command_period_seconds':COMMAND_SECONDS,'command_not_before':earliest,
            'initial_state':{**sample,'rooms':rooms,'water':water,'dhw_mode':native_mode.state,'offset_grid':levels},
            'actuator_roles':{'degree_minutes':{'offset':C1,'target':REQUIRED,'supply':SUPPLY},
                'secondary':{'offset':C2,'target':'sensor.vp_calculated_supply_climate_system_2','role':'mixing-valve target; indirect load on primary circuit'}},
            'search_limited':limited,'comfort_margin_c':uncertainty,'known_hours':(end-now)/3600,'frequency_limit':m.get('air_limit'),'available_compressor_heat_kw':cap,'frequency_reference_hz':reference_hz,'short_horizon':end-now<21600,
            'native_tank_goal_limited':native_goal_limited,'requested_tank_target_c':requested_tank_target,'terminal_heat_value_sek_per_kwh':heat_price,'heat_basis':'Frequency-based nominal heat; not metered'},
        'selection_score':[best.violation,best.cost+terminal(best)],
        'morning_shortfall':best.shortfall,'comfort_risk':best.comfort_risk,
        'objective_components':{'electricity':best.cost,'control_penalties':best.penalty,'terminal_reserve':terminal(best),'uncertainty_cost':COMFORT_RISK_PRICE*best.comfort_risk},
        'offset_response':response}
