"""Planning deadlines and cancellation reach executor search code."""
import asyncio
import unittest
from integration_test import load
import predictive_test as sources
work=load('work')

class BudgetTests(unittest.TestCase):
    def test_expiry_and_explicit_cancel(self):
        now=[0.]
        budget=work.PlanningBudget(12,clock=lambda:now[0])
        budget.check()
        now[0]=12
        self.assertRaisesRegex(RuntimeError,'budget',budget.check)
        budget=work.PlanningBudget()
        budget.cancelled.set()
        self.assertRaises(RuntimeError,budget.check)

class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_forecast_signals_worker(self):
        hass,states,_=sources.SourceTests().make()
        started=asyncio.Event();callbacks=[]
        async def executor(callback):
            callbacks.append(callback);started.set()
            await asyncio.Future()
        hass.async_add_executor_job=executor
        predictor=sources.f.Predictor(hass,{'weather_entity':'weather.home'})
        task=asyncio.create_task(predictor.async_update(states,sources.BASE))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        # If the executor thread resumes after cancellation, it stops immediately.
        with self.assertRaisesRegex(RuntimeError,'budget'):callbacks[0]()

if __name__=='__main__':unittest.main()
