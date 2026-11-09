"""ARX time consistency and observed capacity/supply calibration."""
import unittest
from integration_test import load
native=load('native')

class TransitionTests(unittest.TestCase):
    def test_fifteen_minute_transition_reproduces_learned_map(self):
        theta=[.1,.04,.75,.1]
        expected=.1*2+.04*1+.75*2+.1
        self.assertAlmostEqual(native.response_step(2,2,-100,.25,theta,10),expected)

    def test_subdivision_does_not_multiply_the_fitted_response(self):
        theta=[.1,.04,.75,.1]
        quarter=native.response_step(2,2,-100,.25,theta,10)
        for count in (3,15):
            q=2
            for _ in range(count):q=native.response_step(q,2,-100,.25/count,theta,10)
            self.assertAlmostEqual(q,quarter)

    def test_saturation_and_zero_memory(self):
        self.assertEqual(native.response_step(4,20,-900,.25,[.35,.25,.75,0],4.2),4.2)
        self.assertEqual(native.response_step(2,-20,100,.25,[.35,.25,.75,0],4.2),0)
        self.assertEqual(native.response_step(2,1,-100,.1,[.1,.1,0,0],4.2),.2)
        self.assertRaises(ValueError,native.response_step,2,0,0,.25,[0,0,1,0],4.2)

class EmitterTests(unittest.TestCase):
    def test_reported_saturated_state_does_not_promise_requested_49c(self):
        sample={'mode':'Heating','heat':4.2*87/88,'fraction':87/88,'supply':34.6,'outside':-1.3,'time':1000}
        model={'compressor_heat_kw':4.2,'heat_loss_kw_per_k':.098,'internal_gain_kw':.207}
        result=native.emitter_estimate(sample,19.265,model)
        possible=native.attainable_supply(19.265,4.2,result['conductance_kw_per_k'])
        self.assertAlmostEqual(possible,19.265+(34.6-19.265)*88/87)
        self.assertLess(possible,36)
        self.assertEqual(result['confidence'],'Provisional')
        repeated=native.emitter_estimate(sample,19.265,model,result)
        self.assertEqual(repeated,result)

    def test_dhw_or_off_does_not_recalibrate_from_zero_space_heat(self):
        calibration={'conductance_kw_per_k':.27,'observations':4,'source':'Observed heating proxy','time':1000}
        model={'compressor_heat_kw':4.2}
        for mode in ('Hot water','Off'):
            got=native.emitter_estimate({'mode':mode,'heat':0,'supply':55,'outside':0},20,model,calibration)
            self.assertEqual(got,calibration)
        initial=native.emitter_estimate({'mode':'Off','heat':0,'supply':30,'outside':0},20,model)
        self.assertEqual(initial['confidence'],'Initial')

if __name__=='__main__':unittest.main()
