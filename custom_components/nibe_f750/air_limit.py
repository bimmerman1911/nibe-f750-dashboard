"""One-coefficient, observational evaporator-frequency envelope; no setters."""
from statistics import median
from .engine import fresh,number

FLOOR=-16.5  # Owner-observed starting assumption, not a universal firmware limit.
FLOW='sensor.vp_reference_air_speed_sensor'
INLET='sensor.vp_exhaust_air_bt20'
EVAP='sensor.vp_evaporator_bt16'
HZ='sensor.vp_current_compressor_frequency'
IDS=(FLOW,INLET,EVAP,HZ,'sensor.vp_priority','sensor.vp_degree_minutes_2',
     'sensor.vp_supply_line_bt61','sensor.vp_calculated_supply_climate_system_1')


def airflow(states,now):
    state=states.get(FLOW)
    value=number(state.state) if fresh(state,now) else None
    if value is None:return None
    unit=str(state.attributes.get('unit_of_measurement','')).lower().replace(' ','')
    if unit in ('l/s','lps'):value*=3.6
    elif unit not in ('m³/h','m3/h'):return None
    return value


def sample(states,now):
    def read(e):
        s=states.get(e);return number(s.state) if fresh(s,now) else None
    flow,tin,evap,hz,dm,supply,target=(read(e) for e in (FLOW,INLET,EVAP,HZ,IDS[5],IDS[6],IDS[7]))
    p=states.get('sensor.vp_priority')
    if not all(fresh(states.get(e),now) for e in IDS):return None
    if None in (flow,tin,evap,hz,dm,supply,target):return None
    unit=states[FLOW].attributes.get('unit_of_measurement','').lower().replace(' ','')
    if unit in ('l/s','lps'):flow*=3.6
    elif unit not in ('m³/h','m3/h'):return None
    for e in (INLET,EVAP):
        if states[e].attributes.get('unit_of_measurement') not in ('°C','C'):return None
    if not (50<=flow<=500 and 6<=tin<=40 and -30<=evap<=30 and 20<=hz<=150):return None
    if p.state!='Heating':return None
    if any(fresh(states.get(e),now) and any(w in states[e].state.lower() for w in ('defrost','avfrost')) for e in ('sensor.vp_status','sensor.vp_status_compressor')):return None
    hotgas=read('sensor.vp_hot_gas_bt14')
    if hotgas is not None and hotgas>=100:return None
    timestamp=min(states[e].last_reported.timestamp() for e in (FLOW,INLET,EVAP,HZ))
    return {'time':now,'reported':timestamp,'flow':flow,'tin':tin,'evap':evap,'hz':hz,
            'demand':dm<-100 and target-supply>=.5}


class AirLimit:
    def __init__(self):
        self.samples=[];self.observations=[];self.sustained=None;self.last_airflow=None;self.revision=0
    def dump(self):
        return {'version':1,'observations':self.observations[:],'sustained':self.sustained,'last_airflow':self.last_airflow}
    def restore(self,data):
        try:
            if not data:return False
            assert data['version']==1 and isinstance(data['observations'],list) and len(data['observations'])<=9
            for r in data['observations']:
                assert isinstance(r,dict)
                assert all(number(r.get(k)) is not None for k in ('time','k','flow','tin','hz'))
                assert r['time']>=0
                assert 0<r['k']<=.2 and 50<=r['flow']<=500 and 6<=r['tin']<=40 and 20<=r['hz']<=150
            sustained=data.get('sustained')
            if sustained is not None:
                assert isinstance(sustained,dict)
                assert all(number(sustained.get(k)) is not None for k in ('time','flow','tin','hz'))
                assert 50<=sustained['flow']<=500 and 6<=sustained['tin']<=40 and 20<=sustained['hz']<=150
            cached=data.get('last_airflow')
            if cached is not None:
                assert isinstance(cached,dict) and number(cached.get('time')) is not None and number(cached.get('flow')) is not None
                assert cached['time']>=0 and 50<=cached['flow']<=500
            else:
                # Upgrade older stores using the latest qualified flow evidence.
                history=data['observations']+([sustained] if sustained else [])
                if history:
                    latest=max(history,key=lambda r:r['time']);cached={'time':latest['time'],'flow':latest['flow']}
            self.last_airflow=dict(cached) if cached else None
            self.observations=[dict(r) for r in data['observations']];self.sustained=sustained
            return True
        except (KeyError,TypeError,ValueError,AssertionError):return False
    def update(self,states,now):
        flow=airflow(states,now)
        if flow is not None and 50<=flow<=500:
            stamp=states[FLOW].last_reported.timestamp()
            if self.last_airflow is None or stamp>self.last_airflow['time']:
                self.last_airflow={'time':stamp,'flow':flow};self.revision+=1
        s=sample(states,now)
        if s is None:self.samples=[];return
        if self.samples and s['reported']<=self.samples[-1]['reported']:return
        if self.samples and not 0<s['time']-self.samples[-1]['time']<=180:self.samples=[]
        self.samples.append(s)
        rows=self.samples
        if rows[-1]['time']-rows[0]['time']<600:return
        self.samples=[s]
        span=lambda k:max(r[k] for r in rows)-min(r[k] for r in rows)
        stable=span('hz')<=5 and span('flow')<=min(r['flow'] for r in rows)*.05 and span('tin')<=1.
        if not stable:return
        flow=median(r['flow'] for r in rows);tin=median(r['tin'] for r in rows);hz=median(r['hz'] for r in rows)
        if all(r['demand'] for r in rows) and (self.sustained is None or now-self.sustained['time']>86400 or hz>self.sustained['hz']):
            self.sustained={'time':now,'flow':flow,'tin':tin,'hz':hz};self.revision+=1
        # A plateau alone is not proof of evaporator limitation. Demand must
        # remain unsatisfied, and the coil must stay close to the assumed floor.
        limited=all(r['demand'] and abs(r['evap']-FLOOR)<=.75 for r in rows) and span('evap')<=.6
        if limited:
            k=hz/(flow*(tin-FLOOR))
            if 0<k<=.2:
                self.observations=(self.observations+[{'time':now,'k':k,'flow':flow,'tin':tin,'hz':hz}])[-9:]
                self.revision+=1
    def estimate(self,states,now,reported,minimum):
        def value(e):
            s=states.get(e);return number(s.state) if fresh(s,now) else None
        flow=airflow(states,now);tin=value(INLET)
        flow_source='Live airflow';flow_age=0.
        # A numeric low/zero flow is evidence against the constant-fan assumption.
        explicit_low=flow is not None and flow<50
        if flow is None and self.last_airflow and now>=self.last_airflow['time']:
            flow=self.last_airflow['flow'];flow_source='Last valid airflow';flow_age=now-self.last_airflow['time']
        if states.get(INLET) and states[INLET].attributes.get('unit_of_measurement') not in ('°C','C'):tin=None
        recent=[r for r in self.observations if 0<=now-r['time']<=14*86400]
        usable=flow is not None and tin is not None and 50<=flow<=500 and 6<=tin<=40
        k=median(r['k'] for r in recent) if recent else None
        if usable and k is not None:
            cap=min(reported,.95*k*flow*(tin-(FLOOR+.5)))
            source='Calibrated evaporator limit'
        else:
            # A sustained speed is evidence of achievable operation, not its
            # maximum. Use it provisionally rather than assuming 120 Hz.
            r=self.sustained
            if not explicit_low and r and 0<=now-r['time']<=14*86400:
                scale=min(1.,flow/r['flow']) if flow is not None and 50<=flow<=500 else 1.
                if tin is not None and 6<=tin<=40:scale*=min(1.,(tin-FLOOR)/(r['tin']-FLOOR))
                cap=min(reported,r['hz']*scale)
                source='Provisional sustained observation'
            else:
                cap=None;source='Awaiting qualified capacity evidence'
        return {'source':source,'calibrated':source=='Calibrated evaporator limit','coefficient':k,
                'observations':len(recent),'floor_assumption_c':FLOOR,'floor_margin_c':.5,
                'frequency_margin':.95,'airflow_m3h':flow,'inlet_c':tin,
                'airflow_source':flow_source if flow is not None else 'Unavailable','airflow_age_seconds':flow_age if flow is not None else None,
                'reported_max_hz':reported,'effective_max_hz':max(0.,cap) if cap is not None else None}


def replay(recorded,start,end):
    """Use recorded changes only while a recent event establishes coverage."""
    from datetime import datetime,timezone
    from types import SimpleNamespace
    learner=AirLimit();events=[]
    for entity,rows in recorded.items():
        for s in rows:events.append((max(start,s.last_updated.timestamp()),entity,s))
    events.sort(key=lambda row:row[0]);i=0;current={};last=None
    for cursor in range(int(start),int(end)+1,60):
        while i<len(events) and events[i][0]<=cursor:
            stamp,e,s=events[i];current[e]=s;last=stamp;i+=1
        if last is not None and cursor-last<=180:
            snapshot={e:SimpleNamespace(state=s.state,attributes=s.attributes,last_reported=datetime.fromtimestamp(cursor,timezone.utc)) for e,s in current.items()}
            learner.update(snapshot,cursor)
        else:learner.samples=[]
    return learner.dump()


async def backfill(hass,now):
    from datetime import datetime,timezone
    from functools import partial
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import get_significant_states
    entities=list(IDS)+['sensor.vp_status','sensor.vp_status_compressor','sensor.vp_hot_gas_bt14']
    start=now-48*3600
    recorded=await get_instance(hass).async_add_executor_job(partial(get_significant_states,hass,
        datetime.fromtimestamp(start,timezone.utc),datetime.fromtimestamp(now,timezone.utc),
        entity_ids=entities,include_start_time_state=True,significant_changes_only=False,minimal_response=False,no_attributes=False))
    return await hass.async_add_executor_job(replay,recorded,start,now)
