"""Cooperative cancellation for pure-Python executor planning."""
from threading import Event
from time import monotonic

class PlanningBudget:
    def __init__(self,seconds=12.,clock=monotonic):
        self.clock=clock
        self.deadline=clock()+seconds
        self.cancelled=Event()

    def check(self):
        if self.cancelled.is_set() or self.clock()>=self.deadline:
            raise RuntimeError('Planning computation budget reached; using temperature control until the next retry.')
