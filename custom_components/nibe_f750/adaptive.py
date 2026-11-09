"""Online thermal identification from observed inputs; no external ML service."""
from datetime import datetime, timezone
import math
from .engine import ROOM1, ROOM2, PRIORITY, fresh, number
from .predictive import DEFAULTS

FREQUENCY = 'sensor.vp_current_compressor_frequency'
MAXIMUM = 'sensor.vp_max_compressor_frequency'
HEATER = 'sensor.vp_power_internal_add_heat'
TANK = ('sensor.vp_hot_water_top_bt7', 'sensor.vp_hot_water_charging_bt6')
LAGS = (0., .5, 1., 2., 4.)


def bounded(value, lo, hi):
    return max(lo, min(hi, value))


def filtered_heat(previous, command, hours, lag):
    if lag <= 0:
        return command, command
    decay = math.exp(-hours/lag)
    return command+(previous-command)*decay, command+(previous-command)*lag/hours*(1-decay)


class ThermalLearner:
    """Projected recursive least squares over measured 30-minute windows.

    dT = a*integral(Tout-Troom) + b*integral(delivered-heat proxy) + c*dt.
    Multiple lag hypotheses are scored on pre-update prediction error. Parameters
    describe effective response on the nominal heat-output basis, not metered COP.
    """
    def __init__(self, options=None):
        self.prior = {**DEFAULTS, **(options or {})}
        h, c = self.prior['heat_loss_kw_per_k'], self.prior['thermal_capacity_kwh_per_k']
        self.banks = [{'lag': lag, 'theta': [bounded(h/c,.0005,.15), bounded(1/c,.01,.5), 0.],
                       'p': [[.0002, 0., 0.], [0., .04, 0.], [0., 0., .02]],
                       'score': .1, 'heat': 0.} for lag in LAGS]
        self.count = 0
        self.heating_windows = 0
        self.cooling_windows = 0
        self.last_learning_at = None
        self.last_heating_at = None
        self.projection_windows = 0
        self.projection_last_window = False
        self.rejected = 0
        self.hours = 0.
        self.selected = 2
        self.draw = [.15]*24
        self.draw_counts = [0]*24
        self.draw_hours = [0.]*24
        self.dhw_fraction=.75
        self.dhw_start_c=self.prior['tank_target_c']
        self.dhw_start_observations=0
        self.dhw_stop_observations=0
        self.dhw_charge_windows=0
        self.dhw_capacity = bounded(self.prior['dhw_heat_kw'],1,10)
        self.tank_ceiling = bounded(self.prior['tank_max_c'],48,60)
        self.heat_range = [100., -100.]
        self.outdoor_range = [100., -100.]
        self.revision = 0
        self.previous = None
        self.window = None
        self.draw_window = None
        self.charge_window = None
        self.mode_since = None
        self.run_since = None
        self.comfort_since = None

    def dump(self):
        # Deliberately omit partial windows: never train across a restart/gap.
        return {'version': 1, 'banks': self.banks, 'count': self.count,
                'heating_windows':self.heating_windows, 'cooling_windows':self.cooling_windows,
                'last_learning_at':self.last_learning_at,'last_heating_at':self.last_heating_at,
                'projection_windows':self.projection_windows,'projection_last_window':self.projection_last_window,
                'rejected': self.rejected, 'hours': self.hours, 'selected': self.selected,
                'draw': self.draw, 'draw_counts': self.draw_counts,'draw_hours':self.draw_hours,
                'dhw_fraction':self.dhw_fraction,'dhw_start_c':self.dhw_start_c,'dhw_capacity': self.dhw_capacity, 'tank_ceiling': self.tank_ceiling,
                'dhw_start_observations':self.dhw_start_observations,
                'dhw_stop_observations':self.dhw_stop_observations,'dhw_charge_windows':self.dhw_charge_windows,
                'heat_range': self.heat_range, 'outdoor_range': self.outdoor_range}

    def restore(self, data):
        """Reject corrupt model data; this never touches the cloud-write store."""
        if not data or data.get('version') != 1:
            return False
        try:
            fraction=data.get('dhw_fraction',.75);start=data.get('dhw_start_c',self.prior['tank_target_c'])
            assert .2<=fraction<=1 and 20<=start<=65
            banks = data['banks']
            assert len(banks) == len(LAGS)
            for bank, lag in zip(banks, LAGS):
                assert bank['lag'] == lag and len(bank['theta']) == 3
                a,b,g = bank['theta']
                assert .0005 <= a <= .15 and .01 <= b <= .5 and -.2 <= g <= .4
                assert len(bank['p']) == 3 and all(len(row)==3 for row in bank['p'])
                assert all(math.isfinite(v) for row in bank['p'] for v in row)
                # Positive-definite symmetric covariance, verified by Cholesky.
                lower = [[0.]*3 for _ in range(3)]
                for i in range(3):
                    for j in range(i+1):
                        assert abs(bank['p'][i][j]-bank['p'][j][i]) < 1e-6
                        value = bank['p'][i][j]-sum(lower[i][k]*lower[j][k] for k in range(j))
                        lower[i][j] = math.sqrt(value) if i==j else value/lower[j][j]
                assert math.isfinite(bank['score']) and bank['score'] >= 0
                assert math.isfinite(bank['heat']) and 0 <= bank['heat'] <= 30
            assert len(data['draw']) == len(data['draw_counts']) == 24
            assert all(math.isfinite(v) and 0 <= v <= 8 for v in data['draw'])
            assert all(isinstance(v,int) and v >= 0 for v in data['draw_counts'])
            draw_hours=data.get('draw_hours',[0.]*24)
            assert len(draw_hours)==24 and all(math.isfinite(v) and v>=0 for v in draw_hours)
            assert isinstance(data['count'],int) and data['count'] >= 0
            for key in ('heating_windows','cooling_windows'):
                assert type(data.get(key,0)) is int and 0 <= data.get(key,0) <= data['count']
            assert type(data.get('projection_windows',0)) is int and 0<=data.get('projection_windows',0)<=data['count']
            assert type(data.get('projection_last_window',False)) is bool
            for key in ('dhw_start_observations','dhw_stop_observations','dhw_charge_windows'):
                assert type(data.get(key,0)) is int and data.get(key,0)>=0
            for key in ('last_learning_at','last_heating_at'):
                assert data.get(key) is None or (math.isfinite(data[key]) and data[key]>=0)
            assert isinstance(data['rejected'],int) and data['rejected'] >= 0
            for key in ('heat_range','outdoor_range'):
                assert len(data[key])==2 and all(math.isfinite(v) for v in data[key])
            assert isinstance(data['selected'],int) and 0 <= data['selected'] < len(LAGS)
            assert math.isfinite(data['hours']) and data['hours'] >= 0
            assert 1 <= data['dhw_capacity'] <= 10 and 46 <= data['tank_ceiling'] <= 65
            for key in ('banks','count','rejected','hours','selected','draw','draw_counts',
                        'dhw_capacity','tank_ceiling','heat_range','outdoor_range'):
                if key in data:
                    setattr(self,key,data[key])
            self.dhw_fraction=fraction;self.dhw_start_c=start
            self.heating_windows=data.get('heating_windows',0)
            self.cooling_windows=data.get('cooling_windows',0)
            for key in ('dhw_start_observations','dhw_stop_observations','dhw_charge_windows'):
                setattr(self,key,data.get(key,0))
            self.last_learning_at=data.get('last_learning_at')
            self.last_heating_at=data.get('last_heating_at')
            self.draw_hours=draw_hours
            self.projection_windows=data.get('projection_windows',0)
            self.projection_last_window=data.get('projection_last_window',False)
            return True
        except (KeyError, TypeError, ValueError, AssertionError, ZeroDivisionError):
            return False

    def observation(self, states, now, hour):
        def value(e):
            state = states.get(e)
            return number(state.state) if fresh(state,now) else None
        outside = value('sensor.vp_current_outd_temp_bt1')
        if outside is None:
            outside = value('sensor.vp_average_outdoor_temp_bt1')
        r1,r2,freq,maximum,heater = (value(e) for e in (ROOM1,ROOM2,FREQUENCY,MAXIMUM,HEATER))
        mode = states.get(PRIORITY)
        if (None in (r1,r2,freq,maximum,heater,outside) or not fresh(mode,now)
            or mode.state not in ('Heating','Hot water','Off') or not 5<=r1<=35 or not 5<=r2<=35
            or not -50<=outside<=50 or not 0<=freq<=150 or not 20<=maximum<=150 or not 0<=heater<=10):
            return None
        for e in ('sensor.vp_status','sensor.vp_status_compressor'):
            if fresh(states.get(e),now) and 'defrost' in states[e].state.lower():
                return None
        water = [value(e) for e in TANK]
        tank = sum(water)/2 if all(v is not None and 10<=v<=80 for v in water) else None
        heat = self.prior['compressor_heat_kw']*bounded(freq/maximum,0,1) + heater
        mode_name = mode.state
        comfort = states.get('select.vp_comfort_mode')
        return {'time':now,'hour':hour,'room':(r1+r2)/2,'outside':outside,
                'rooms':(r1,r2),
                'heat':heat if mode_name=='Heating' else 0., 'fraction':bounded(freq/maximum,0,1),
                'heater':heater,'mode':mode_name,'running':freq>0,'tank':tank,
                'comfort':comfort.state if comfort else None}

    def update(self, states, now, hour):
        current = self.observation(states,now,hour)
        previous = self.previous
        self.previous = current
        if current is None:
            self.mode_since = self.run_since = None
            self.comfort_since = None
            self.window = self.charge_window = self.draw_window = None
            self.rejected += 1
            return False
        if previous is None or not 30 <= now-previous['time'] <= 180:
            self.window = self.charge_window = self.draw_window = None
            for bank in self.banks:
                bank['heat'] = current['heat']
            self.mode_since = self.run_since = None
            self.comfort_since = current['time']
            return False
        if self.comfort_since is None or current['comfort'] != previous['comfort']:
            self.comfort_since=now
        if current['mode'] != previous['mode']:
            self.mode_since = now
        if current['running'] != previous['running']:
            self.run_since = now
        dt = (now-previous['time'])/3600
        if (any(abs(a-b)>.8 for a,b in zip(current['rooms'],previous['rooms']))
            or abs(current['outside']-previous['outside'])>3):
            self.window = self.charge_window = self.draw_window = None
            self.rejected += 1
            return False
        if self.window is None:
            self.window = {'start':previous['room'], 'hours':0., 'heat_energy':0.,
                           'heat_min':previous['heat'],'heat_max':previous['heat'],
                           'features':[[0.,0.,0.] for _ in self.banks]}
        gradient = ((previous['outside']-previous['room'])+(current['outside']-current['room']))/2
        heat = (previous['heat']+current['heat'])/2
        for i,bank in enumerate(self.banks):
            bank['heat'], average = filtered_heat(bank['heat'],heat,dt,bank['lag'])
            x = self.window['features'][i]
            x[0] += gradient*dt
            x[1] += average*dt
            x[2] += dt
        self.window['hours'] += dt
        self.window['heat_energy'] += heat*dt
        self.window['heat_min']=min(self.window['heat_min'],previous['heat'],current['heat'])
        self.window['heat_max']=max(self.window['heat_max'],previous['heat'],current['heat'])
        self._water(previous,current,dt)
        if self.window['hours'] < .5-1e-6:
            return False
        y = current['room']-self.window['start']
        if abs(y) <= 1.5:
            projected=False
            for bank,x in zip(self.banks,self.window['features']):
                projected=self._fit(bank,x,y) or projected
            self.count += 1
            self.projection_windows+=int(projected)
            self.projection_last_window=projected
            average_heat=self.window['heat_energy']/self.window['hours']
            self.heating_windows += int(average_heat>=.5)
            self.cooling_windows += int(average_heat<=.1)
            self.last_learning_at=now
            if average_heat>=.5:
                self.last_heating_at=now
            self.hours += self.window['hours']
            self.heat_range = [min(self.heat_range[0],self.window['heat_min']),max(self.heat_range[1],self.window['heat_max'])]
            self.outdoor_range = [min(self.outdoor_range[0],current['outside']),max(self.outdoor_range[1],current['outside'])]
            if self.count >= 12:
                candidate = min(range(len(self.banks)),key=lambda i:self.banks[i]['score'])
                if self.banks[candidate]['score'] < self.banks[self.selected]['score']*.9:
                    self.selected = candidate
            self.revision += 1
        else:
            self.rejected += 1
        self.window = None
        return True

    @staticmethod
    def _fit(bank,x,y):
        theta,p = bank['theta'],bank['p']
        error = y-sum(a*b for a,b in zip(theta,x))
        bank['score'] = .95*bank['score']+.05*abs(error)
        # Huber influence limits sensor/occupancy transients without fitting them.
        error = bounded(error,-.3,.3)
        px = [sum(row[j]*x[j] for j in range(3)) for row in p]
        forgetting = .999
        denominator = forgetting*.0025+sum(x[i]*px[i] for i in range(3))
        gain = [v/denominator for v in px]
        raw = [theta[i]+gain[i]*error for i in range(3)]
        ranges = ((.0005,.15),(.01,.5),(-.2,.4))
        for i,(lo,hi) in enumerate(ranges):
            step = abs(theta[i])*.1 if i<2 else .02
            theta[i] = bounded(bounded(raw[i],theta[i]-step,theta[i]+step),lo,hi)
        # The independent theta box alone permits H=15 kW/K and a 40 kW
        # constant gain. Keep broad domestic response bounds on the ratios too.
        before=theta[:]
        theta[0]=bounded(theta[0],max(.0005,.01*theta[1]),min(.15,theta[1]))
        theta[2]=bounded(theta[2],max(-.2,-3*theta[1]),min(.4,6*theta[1]))
        # Symmetric covariance update; positive measurement noise prevents collapse.
        bank['p'] = [[(p[i][j]-px[i]*px[j]/denominator)/forgetting for j in range(3)] for i in range(3)]
        return theta!=before

    def _flush_draw(self):
        w=self.draw_window
        self.draw_window=None
        if w is not None and w['hours']>=.25:
            rate=bounded(w['energy']/w['hours'],0,8)
            alpha=.2*min(1.,w['hours'])
            self.draw[w['hour']]=(1-alpha)*self.draw[w['hour']]+alpha*rate
            self.draw_counts[w['hour']]+=1
            self.draw_hours[w['hour']]+=w['hours']
            self.revision+=1

    def _water(self, prev, cur, dt):
        if prev['tank'] is None or cur['tank'] is None:
            self.charge_window=self.draw_window=None
            return
        delta=cur['tank']-prev['tank']
        # BT6/BT7 are an effective tank proxy. A large redistribution or sensor
        # jump cannot be attributed to a measured hot-water draw.
        if abs(delta)>8 or abs(delta)/dt>240:
            self.charge_window=self.draw_window=None
            return
        normal=prev['comfort']==cur['comfort']=='Normal'
        if cur['mode']=='Hot water' and cur['running'] and cur['comfort']=='Normal':
            alpha=1-math.exp(-dt/(100/60))
            self.dhw_fraction=bounded((1-alpha)*self.dhw_fraction+alpha*cur['fraction'],.2,1.)
            # Enabling Normal after Economy does not identify the native start
            # threshold: the controller may have intentionally depleted the tank.
            if (prev['mode']!='Hot water' and normal and self.comfort_since is not None
                and cur['time']-self.comfort_since>=900):
                self.dhw_start_c=bounded(.8*self.dhw_start_c+.2*prev['tank'],20,65)
                self.dhw_start_observations+=1
            self.revision+=1
        if prev['mode']!='Hot water' and cur['mode']!='Hot water':
            energy=-self.prior['tank_capacity_kwh_per_k']*delta-.0015*(prev['tank']-20)*dt
            if self.draw_window is not None and self.draw_window['hour']!=prev['hour']:
                self._flush_draw()
            if self.draw_window is None:
                self.draw_window={'hour':prev['hour'],'hours':0.,'energy':0.}
            self.draw_window['hours']+=dt
            self.draw_window['energy']+=energy
        else:
            # Never join two draw fragments across a charge, even in one hour.
            self._flush_draw()
        if (prev['mode']==cur['mode']=='Hot water' and normal and delta>=-.5
            and prev['running'] and cur['running']):
            if self.charge_window is None:
                self.charge_window={'start':prev['tank'],'hours':0.,'fraction':0.,'inline':0.}
            w=self.charge_window
            w['hours']+=dt
            w['fraction']+=(prev['fraction']+cur['fraction'])/2*dt
            w['inline']+=(prev['heater']+cur['heater'])/2*dt
            if w['hours']>=1/6 and w['fraction']>.05:
                estimate=(self.prior['tank_capacity_kwh_per_k']*(cur['tank']-w['start'])
                          +.0015*(cur['tank']-20)*w['hours']-w['inline'])/w['fraction']
                if 1<=estimate<=10:
                    self.dhw_capacity=.95*self.dhw_capacity+.05*estimate
                    self.dhw_charge_windows+=1
                    self.revision+=1
                self.charge_window=None
        else:
            self.charge_window=None
            # A controller-requested Economy transition is not a native full
            # charge. Learn the ceiling only when Normal remained enabled.
            if (prev['mode']=='Hot water' and cur['mode']!='Hot water' and normal
                and prev['running'] and prev['tank']>=47):
                self.tank_ceiling=bounded(.8*self.tank_ceiling+.2*prev['tank'],48,60)
                self.dhw_stop_observations+=1
                self.revision+=1

    def _bounded_parameters(self):
        a,b,g=self.banks[self.selected]['theta']
        valid=all(math.isfinite(v) for v in (a,b,g)) and b>0
        raw=(a/b,1/b,g/b) if valid else (self.prior['heat_loss_kw_per_k'],self.prior['thermal_capacity_kwh_per_k'],0.)
        result=tuple(bounded(v,lo,hi) for v,(lo,hi) in zip(raw,((.01,1.),(2.,100.),(-3.,6.))))
        return result,not valid or raw!=result

    def quality(self):
        heat_span=max(0.,self.heat_range[1]-self.heat_range[0])
        outdoor_span=max(0.,self.outdoor_range[1]-self.outdoor_range[0])
        excitation=min(1.,heat_span/1.5)*min(1.,outdoor_span/3.)
        confidence=min(1.,self.count/96)*min(1.,self.heating_windows/12)*excitation
        score=self.banks[self.selected]['score']
        _,projected=self._bounded_parameters()
        projected=projected or self.projection_last_window
        if projected:
            confidence*=.25
        # This is a conservative error allowance for planning, not a calibrated
        # statistical confidence interval or an accuracy guarantee.
        allowance=max(.35 if projected else .05,2*score+.15*(1-confidence))
        return {'model_confidence':round(confidence,3),'physical_projection_applied':projected,
                'projection_windows':self.projection_windows,
                'response_uncertainty_c':round(allowance,3),
                'heat_response_identified':self.heating_windows>=6 and heat_span>=1. and not projected,
                'heating_windows':self.heating_windows,'cooling_windows':self.cooling_windows,
                'last_learning_at':self.last_learning_at,'last_heating_at':self.last_heating_at,
                'dhw_profile_confidence':[round(min(1.,v/7),3) for v in self.draw_hours],
                'dhw_observed_hours':[round(v,3) for v in self.draw_hours],
                'dhw_start_observations':self.dhw_start_observations,
                'dhw_stop_observations':self.dhw_stop_observations,
                'dhw_charge_windows':self.dhw_charge_windows}

    def parameters(self):
        bank = self.banks[self.selected]
        (loss,capacity,gain),_=self._bounded_parameters()
        return {**self.quality(),'heat_loss_kw_per_k':loss, 'thermal_capacity_kwh_per_k':capacity,
                'internal_gain_kw':gain, 'heating_lag_hours':bank['lag'],
                'initial_heat_kw':bank['heat'], 'dhw_heat_kw':self.dhw_capacity,
                'dhw_fraction':self.dhw_fraction,'dhw_start_c':self.dhw_start_c,
                'dhw_profile':self.draw[:], 'tank_max_c':min(self.prior['tank_max_c'],self.tank_ceiling),
                'initial_run_minutes':30. if self.run_since is None else min(30.,(self.previous['time']-self.run_since)/60) if self.previous and self.previous['running'] else 0.,
                'initial_off_minutes':15. if self.run_since is None else min(15.,(self.previous['time']-self.run_since)/60) if self.previous and not self.previous['running'] else 0.,
                'initial_mode_minutes':15. if self.mode_since is None else min(15.,(self.previous['time']-self.mode_since)/60)}

    def diagnostics(self):
        varied = self.heat_range[1]-self.heat_range[0]>=1 and self.outdoor_range[1]-self.outdoor_range[0]>=2
        return {'state':'Adapting' if self.count>=48 and varied else 'Learning',
                'windows':self.count, 'observed_hours':round(self.hours,2),
                'response_error_c':round(self.banks[self.selected]['score'],3) if self.count else None,
                'rejected_samples':self.rejected, 'quality':self.quality(), 'model':self.parameters(),
                'draw_observations':self.draw_counts[:],
                'basis':'Effective response on estimated compressor heat; not metered COP.'}
