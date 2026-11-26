"""Compare electricity costs at equivalent comfort and recovery."""
from dataclasses import dataclass
from math import sqrt

EPSILON = 1e-8
RECOVERY_TIME_MARGIN_H = .5
MORNING_MARGIN_C = .1


@dataclass(frozen=True, slots=True)
class Recovery:
    rms_deficit_c: float
    worst_deficit_c: float
    end_deficit_c: float
    last_deficit_hours: float
    morning_shortfall_c: float

    @classmethod
    def measured(cls, violation, hours, worst, end, last_deficit, morning):
        return cls(sqrt(max(0., violation) / max(hours, EPSILON)), worst, end, last_deficit, morning)

    @classmethod
    def from_plan(cls, plan):
        recovery = plan.get('recovery')
        if recovery is not None:
            return cls(**recovery)
        # Plans supplied without a trajectory summary retain strict scoring.
        return cls.measured(plan['constraint_violation_score'], 1., 0., 0., 0., plan['morning_shortfall'])

    def misses(self, limits):
        comfort = (max(0., self.rms_deficit_c - limits.rms_deficit_c)
                   + max(0., self.worst_deficit_c - limits.worst_deficit_c)
                   + max(0., self.end_deficit_c - limits.end_deficit_c))
        # Time beyond the recovery deadline is a separate requirement while
        # still keeping cost at the same position in all comparison keys.
        late = max(0., self.last_deficit_hours - limits.last_deficit_hours)
        return (comfort, late), max(0., self.morning_shortfall_c - limits.morning_shortfall_c)


def recovery_limits(candidates, uncertainty):
    """Set a comparable recovery deadline from evaluated trajectories.

    Exact limits apply when feasible. Where capacity is insufficient, require
    comparable depth, duration and morning reserve before comparing cost.
    """
    candidates = list(candidates)
    margin = min(.10, max(.03, uncertainty / 2))
    best_rms = min(c.rms_deficit_c for c in candidates)
    if best_rms <= EPSILON:
        rms_limit = EPSILON
        worst_limit = EPSILON
        end_limit = EPSILON
        deadline = 0.
        candidates = [c for c in candidates if c.rms_deficit_c <= rms_limit]
    else:
        rms_limit = best_rms + margin
        candidates = [c for c in candidates if c.rms_deficit_c <= rms_limit]
        worst_limit = min(c.worst_deficit_c for c in candidates) + margin
        candidates = [c for c in candidates if c.worst_deficit_c <= worst_limit]
        end_limit = min(c.end_deficit_c for c in candidates) + margin
        candidates = [c for c in candidates if c.end_deficit_c <= end_limit]
        deadline = min(c.last_deficit_hours for c in candidates) + RECOVERY_TIME_MARGIN_H
        candidates = [c for c in candidates if c.last_deficit_hours <= deadline]
    morning = min(c.morning_shortfall_c for c in candidates)
    morning_limit = EPSILON if morning <= EPSILON else morning + MORNING_MARGIN_C
    return Recovery(rms_limit, worst_limit, end_limit, deadline, morning_limit)


def selection_key(plan, limits=None):
    """Rank feasible or comparable recoveries by electricity and terminal cost."""
    recovery = Recovery.from_plan(plan)
    constraint, morning = (recovery.misses(limits) if limits else
                           ((recovery.rms_deficit_c, recovery.last_deficit_hours), recovery.morning_shortfall_c))
    cost = plan['selection_score'][1] if 'selection_score' in plan else plan['model_cost']
    return (constraint, morning, cost, plan.get('comfort_risk', 0.), plan['inline_kwh'],
            plan.get('objective_components', {}).get('control_penalties', 0.))


def plan_limits(plans, model):
    return recovery_limits((Recovery.from_plan(plan) for plan in plans), model.get('response_uncertainty_c', .1))
