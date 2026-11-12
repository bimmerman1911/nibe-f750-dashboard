"""Cooperative cancellation for pure-Python executor planning."""
from threading import Event
from time import monotonic

class PlanningBudget:
    def __init__(self,seconds=12.,clock=monotonic):
        self.clock=clock
        self.deadline=clock()+seconds
        self.cancelled=Event()

    def remaining(self):
        return max(0.,self.deadline-self.clock())

    def check_cancelled(self):
        # A reduced-search completion may outlive the soft computation budget,
        # but must still stop when the enclosing async forecast is cancelled.
        if self.cancelled.is_set():
            raise RuntimeError('Planning computation budget cancelled.')

    def check(self):
        if self.cancelled.is_set() or self.clock()>=self.deadline:
            raise RuntimeError('Planning computation budget reached; using temperature control until the next retry.')


class ReservedBudget:
    """Share cancellation while reserving parent time for complete replays."""
    def __init__(self,parent,seconds):
        self.parent=parent;self.seconds=seconds
    def remaining(self):return max(0.,self.parent.remaining()-self.seconds)
    def check_cancelled(self):self.parent.check_cancelled()
    def check(self):
        self.parent.check_cancelled()
        if self.remaining()<=0:raise RuntimeError('Reserved planning budget reached')
