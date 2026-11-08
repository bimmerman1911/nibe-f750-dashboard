"""Identification, persistence and active supervisory-control regression tests."""
import copy
from datetime import datetime, timezone
import math
from types import SimpleNamespace
import unittest
from integration_test import load, Store, Fixture, runtime, engine

adaptive=load('adaptive')
supervisor=load('supervisor')
predictive=load('predictive')

BASE=1800000000.
def states_at(t,room=20.,outdoor=5.,q=2.1,tank=49.,mode='Heating'):
    values={engine.ROOM1:room+.1,engine.ROOM2:room-.1,engine.C1:0,engine.C2:0,
      adaptive.FREQUENCY:q/4.2*84,adaptive.MAXIMUM:84,adaptive.HEATER:0,
      engine.PRIORITY:mode,'sensor.vp_current_outd_temp_bt1':outdoor,
      'sensor.vp_degree_minutes_2':-120,engine.SUPPLY:36,engine.REQUIRED:34,engine.DHW:'Normal',
      adaptive.TANK[0]:tank,adaptive.TANK[1]:tank}
    return {e:SimpleNamespace(entity_id=e,state=str(v),attributes={'min':-10,'max':10,'options':['Normal','Economy']},
             last_reported=datetime.fromtimestamp(t,timezone.utc)) for e,v in values.items()}

class LearningTests(unittest.TestCase):
    def test_identification_improves_observed_response_and_survives_restart(self):
        learner=adaptive.ThermalLearner()
        room=20.
        stored=2.1
        prior_error=[]
        window_start=room
        gradient=energy=0.
        h,c,gain=.16,10.,.4
        for minute in range(14*24*60+1):
            hour=minute/60
            now=BASE+minute*60
            outside=5+3*math.sin(hour*math.pi/12)
            q=(0.,4.2,2.1,3.2)[int(hour//3)%4]
            state=states_at(now,room,outside,q)
            learner.update(state,now,int(hour)%24)
            next_stored, delivered=adaptive.filtered_heat(stored,q,1/60,2.)
            decay=math.exp(-h/c/60)
            next_room=outside+(room-outside)*decay+(delivered+gain)/h*(1-decay)
            gradient+=(outside-room)/60
            energy+=delivered/60
            if minute and minute%30==0:
                prior=.1/9*gradient+energy/9
                prior_error.append(abs((next_room-window_start)-prior))
                window_start=next_room;gradient=energy=0.
            room,stored=next_room,next_stored
        self.assertGreater(learner.count,600)
        self.assertLess(learner.banks[learner.selected]['score'],sum(prior_error[-100:])/100)
        self.assertNotAlmostEqual(learner.parameters()['heat_loss_kw_per_k'],.1,places=3)
        data=copy.deepcopy(learner.dump())
        restored=adaptive.ThermalLearner()
        self.assertTrue(restored.restore(data))
        self.assertEqual(restored.banks,learner.banks)
        self.assertEqual(restored.parameters()['heat_loss_kw_per_k'],learner.parameters()['heat_loss_kw_per_k'])
        self.assertEqual(restored.count,learner.count)
        self.assertIsNone(restored.previous)

    def test_gaps_outliers_and_corrupt_models_are_not_fitted(self):
        learner=adaptive.ThermalLearner()
        learner.update(states_at(BASE),BASE,12)
        bad=states_at(BASE+60)
        bad[engine.ROOM1].state='unknown'
        learner.update(bad,BASE+60,12)
        learner.update(states_at(BASE+3600),BASE+3600,13)
        self.assertEqual(learner.count,0)
        broken=learner.dump()
        broken['banks']=copy.deepcopy(broken['banks'])
        broken['banks'][0]['p'][0][0]=-1
        self.assertFalse(adaptive.ThermalLearner().restore(broken))

    def test_missing_inputs_after_mode_change_leave_a_usable_model(self):
        learner=adaptive.ThermalLearner()
        learner.update(states_at(BASE),BASE,12)
        learner.update(states_at(BASE+60,mode='Hot water'),BASE+60,12)
        broken=states_at(BASE+120)
        broken[adaptive.HEATER].state='unavailable'
        learner.update(broken,BASE+120,12)
        self.assertGreater(learner.parameters()['thermal_capacity_kwh_per_k'],0)
        self.assertEqual(learner.parameters()['initial_mode_minutes'],15)

    def test_water_draw_profile_adapts_to_observed_usage(self):
        learner=adaptive.ThermalLearner()
        for day in range(8):
            tank=50.
            for minute in range(122):
                now=BASE+(day*24*60+minute)*60
                hour=8+minute//60
                learner.update(states_at(now,20,5,0,tank,'Off'),now,hour)
                rate=.6 if hour==8 else 0.
                tank-=(rate+.0015*(tank-20))/60/.209
        self.assertGreater(learner.draw[8],.4)
        self.assertGreater(learner.draw_counts[8],3)
        self.assertLess(learner.draw[9],.1)

class MappingTests(unittest.TestCase):
    def forecast(self,action='heat'):
        return {'generated_at':BASE,'model':predictive.DEFAULTS,'steps':[
            {'start':BASE,'end':BASE+900,'action':'off','offset':-1,'room':20.,'water':49.},
            {'start':BASE+900,'end':BASE+1800,'action':action,'offset':1,'room':20.2,'water':49.}]}

    def test_live_interval_drives_targets_and_dhw(self):
        states=states_at(BASE+960,20.,q=2.1)
        value=supervisor.request(self.forecast(),states,BASE+960,predictive.DEFAULTS)
        self.assertEqual(value['target_c'],20)
        self.assertEqual(value['offset_c1'],1)
        before=supervisor.request(self.forecast(),states_at(BASE,20.),BASE,predictive.DEFAULTS)
        self.assertEqual(before['target_c'],20)
        self.assertEqual(before['offset_c1'],-1)
        dhw=supervisor.request(self.forecast('dhw'),states,BASE+960,predictive.DEFAULTS)
        self.assertEqual(dhw['dhw'],'Normal')
        self.assertEqual(value['mode'],'Adaptive')

    def test_cold_room_and_low_tank_override_coasting(self):
        states=states_at(BASE+60,19.1,tank=42.5)
        control=supervisor.request(self.forecast(),states,BASE+60,predictive.DEFAULTS)
        self.assertEqual(control['target_c'],20)
        self.assertEqual(control['dhw'],'Normal')
        result=engine.calculate(states,BASE+60,12,control=control)
        self.assertEqual(result['targets'][0],20)
        self.assertIsNone(supervisor.request(self.forecast(),states,BASE+1300,predictive.DEFAULTS))

    def test_imminent_charge_and_zero_charge_reserve_enable_normal(self):
        states=states_at(BASE,20.,tank=49.)
        # Charging starts in 15 minutes: enable now because writes have a cadence.
        control=supervisor.request(self.forecast('dhw'),states,BASE,predictive.DEFAULTS)
        self.assertEqual(control['dhw'],'Normal')
        forecast=self.forecast('off')
        states=states_at(BASE,20.,tank=45.)
        model={**predictive.DEFAULTS,'dhw_profile':[2.]*24}
        control=supervisor.request(forecast,states,BASE,model)
        self.assertEqual(control['dhw'],'Normal')

    def test_price_only_fallback_never_disables_dhw(self):
        states=states_at(BASE,20.)
        states[engine.PRICE]=SimpleNamespace(state='2',attributes={'average':1,'min':.5,'max':2})
        states['sensor.vp_average_outdoor_temp_bt1']=SimpleNamespace(state='5')
        states['sensor.vp_exhaust_air_bt20']=SimpleNamespace(state='20')
        states[engine.DHW].state='Economy'
        result=engine.calculate(states,BASE,12)
        self.assertIn((engine.DHW,'Normal'),result['writes'])
        states[engine.DHW].state='Lux'
        self.assertEqual(engine.restore_dhw(states),[])

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_planner_changes_actual_service_payloads_without_extra_gate(self):
        Store.saved=None;Store.other={}
        hass=Fixture()
        hass.time=BASE
        hass.states.values['sensor.vp_degree_minutes_2']='-120'
        hass.states.values.update({engine.ROOM1:'20',engine.ROOM2:'20',engine.C1:'0',engine.C2:'0',engine.DHW:'Normal'})
        class Predictor:
            options={}
            async def async_update(self,states,now):
                return {'status':'Adaptive schedule','generated_at':now,'initial_room':20.,'initial_water':49.,
                        'model':predictive.DEFAULTS,'steps':[{'start':now,'end':now+900,'action':'off',
                        'room':20.,'water':49.,'offset':-1,'hz':0.,'inline_kw':0.}]}
        # These tank entities are needed by the real mapper.
        hass.states.values.update({e:'49' for e in adaptive.TANK})
        controller=runtime.Controller(hass,clock=lambda:hass.time,predictor=Predictor())
        await controller.async_start()
        self.assertEqual(controller.control['mode'],'Adaptive')
        self.assertEqual(controller.targets,[20,20])
        calls={data['entity_id']:data for _,_,_,data in hass.calls}
        self.assertEqual(calls[engine.C1]['value'],-1)
        self.assertEqual(calls[engine.DHW]['option'],'Economy')
        count=len(hass.calls)
        await controller.async_tick()
        self.assertEqual(len(hass.calls),count)
        self.assertIn('nibe_f750.predictions',Store.other)

    async def test_real_forecasts_and_learned_model_reach_live_dispatch(self):
        from predictive_test import SourceTests
        source_hass,states,_=SourceTests().make()
        states[engine.ROOM1].state=states[engine.ROOM2].state='20'
        Store.saved=None;Store.other={}
        hass=Fixture();hass.time=BASE
        hass.states=SimpleNamespace(async_all=lambda:list(states.values()))
        hass.async_add_executor_job=source_hass.async_add_executor_job
        async def call(domain,service,data,**kwargs):
            if domain in ('weather','nordpool'):
                return await source_hass.services.async_call(domain,service,data,**kwargs)
            return await hass.call(domain,service,data,kwargs.get('blocking'))
        hass.services.async_call=call
        from _nibe_test.forecast import Predictor
        predictor=Predictor(hass,{'weather_entity':'weather.home'})
        controller=runtime.Controller(hass,clock=lambda:hass.time,predictor=predictor)
        controller.learner.selected=0
        controller.learner.banks[0]['theta']=[.012,.08,.02]
        controller.learner.count=10
        controller.learner.revision+=1
        await controller.async_start()
        self.assertEqual(controller.control['mode'],'Adaptive')
        self.assertAlmostEqual(controller.forecast['model']['heat_loss_kw_per_k'],.15)
        self.assertEqual(controller.forecast['learning']['windows'],10)
        self.assertIn('offset_c1',controller.control)
        self.assertEqual(controller.control['target_c'],20)
        self.assertTrue(all('offset' in s for s in controller.forecast['steps']))
        self.assertTrue(all(domain in ('number','select') for _,domain,_,_ in hass.calls))
        self.assertEqual(controller.decision_log[-1]['control']['mode'],'Adaptive')

    async def test_adaptive_targets_keep_the_rolling_native_write_budget(self):
        Store.saved=None;Store.other={}
        hass=Fixture();hass.time=BASE
        hass.states.values['sensor.vp_degree_minutes_2']='-120'
        hass.states.values.update({engine.ROOM1:'20',engine.ROOM2:'20',**{e:'49' for e in adaptive.TANK}})
        class Predictor:
            options={}
            async def async_update(self,states,now):
                return {'status':'Adaptive schedule','generated_at':now,'initial_room':20.,'initial_water':49.,
                        'model':predictive.DEFAULTS,'steps':[{'start':now,'end':now+900,'action':'off',
                        'room':20.,'water':49.,'offset':-1,'hz':0.,'inline_kw':0.}]}
        controller=runtime.Controller(hass,clock=lambda:hass.time,predictor=Predictor())
        await controller.async_start()
        start=hass.time
        for minute in range(65):
            hass.time=start+minute*60
            await controller.async_tick()
        self.assertEqual(controller.control['mode'],'Adaptive')
        self.assertGreater(len(hass.calls),0)
        for time,*_ in hass.calls:
            self.assertLessEqual(sum(time<=c[0]<time+900 for c in hass.calls),3)

    async def test_pause_restores_normal_at_next_permitted_cycle(self):
        Store.saved=None;Store.other={}
        hass=Fixture();hass.time=BASE
        controller=runtime.Controller(hass,clock=lambda:hass.time)
        await controller.async_start()
        count=len(hass.calls)
        await controller.async_enable(False)
        self.assertEqual(len(hass.calls),count)
        hass.time+=903
        await controller.async_tick()
        self.assertEqual(controller.status,'Paused')
        self.assertEqual(hass.calls[-1][3],{'entity_id':engine.DHW,'option':'Normal'})
        self.assertEqual(len(hass.calls),count+1)
        hass.states.values[engine.DHW]='Normal'
        hass.time+=1000
        await controller.async_tick()
        self.assertEqual(len(hass.calls),count+1)
        # After releasing deferral once, Pause permits later manual selection.
        hass.states.values[engine.DHW]='Economy'
        hass.time+=1000
        await controller.async_tick()
        self.assertEqual(len(hass.calls),count+1)

    async def test_learning_persists_and_forecast_failure_falls_back(self):
        Store.saved=None;Store.other={}
        hass=Fixture()
        class Predictor:
            options={}
            async def async_update(self,states,now):
                return {'status':'Waiting for forecast','message':'Forecast missing','steps':[]}
        controller=runtime.Controller(hass,clock=lambda:hass.time,predictor=Predictor())
        await controller.async_start()
        self.assertEqual(controller.control['mode'],'Thermostat fallback')
        controller.learner.count=25
        controller.learner.revision+=1
        await controller.async_tick()
        restored=runtime.Controller(hass,clock=lambda:hass.time,predictor=Predictor())
        await restored.async_start()
        self.assertEqual(restored.learner.count,25)
        self.assertEqual(restored.control['mode'],'Thermostat fallback')

if __name__=='__main__':
    unittest.main()
