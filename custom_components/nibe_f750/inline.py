"""Compare inline permission windows and track phone approval for one run."""
from datetime import datetime
import math
from secrets import token_hex

from .engine import fresh, number

CAP_ENTITY = 'select.vp_set_max_electrical_add'
STATUS_ENTITY = 'sensor.vp_int_elec_add_heat'
EVENT = 'mobile_app_notification_action'
WINDOW_SECONDS = 960
OFFER_LEAD = 3600
MIN_LEAD = 300
START_GRACE = 90
WRITE_INTERVAL = 902


def power_option(state, kw):
    for option in getattr(state, 'attributes', {}).get('options', ()):
        if isinstance(option,str) and number(option.lower().removesuffix('kw').strip()) == kw:
            return option
    return None


def supports_window(states, now, kw):
    cap = states.get(CAP_ENTITY)
    status = states.get(STATUS_ENTITY)
    return (fresh(cap, now) and fresh(status, now) and status.state in ('Off', 'Blocked', 'Active')
            and bool(power_option(cap, 0) and power_option(cap, kw)))


def trial_slots(slots, start, end):
    """Split exactly at permission boundaries while retaining source prices."""
    for slot in slots:
        cuts = [slot['start'], *(x for x in (start, end) if slot['start'] < x < slot['end']), slot['end']]
        for a, b in zip(cuts, cuts[1:]):
            yield {**slot, 'start': a, 'end': b, 'dt': (b - a) / 3600,
                   'inline_allowed': start <= a < end}


def candidate_windows(slots, baseline, now, earliest, preferred=None):
    """Order reachable windows by duration-weighted price, before a shortfall."""
    if preferred:
        start, end = preferred['start'], preferred['end']
        if now < start + START_GRACE and earliest < start + START_GRACE and end <= slots[-1]['end']:
            yield start, end
        return
    model = baseline['model']
    shortfall_at = next((s['end'] for s in baseline['steps']
                         if min(s['room1'], s['room2']) < model['room_min_c']
                         or s['water'] < model['tank_min_c']), None)
    if shortfall_at is None and baseline['morning_shortfall'] > .05:
        from .dhw import next_deadline
        shortfall_at = next_deadline(now, model['timezone'])
    if shortfall_at is None:
        return
    # If recovery is already needed, still consider upcoming opportunities.
    cutoff = max(shortfall_at, now + 2 * 3600)
    first = math.ceil(max(now + MIN_LEAD, earliest) / 900) * 900
    last = min(cutoff, slots[-1]['end'] - WINDOW_SECONDS)
    windows = []
    for start in range(first, int(last) + 1, 900):
        end = start + WINDOW_SECONDS
        energy_price = sum(s['price'] * max(0., min(end, s['end']) - max(start, s['start']))
                           for s in slots) / WINDOW_SECONDS
        windows.append((energy_price, start, end))
    for _, start, end in sorted(windows):
        yield start, end


def compare_windows(slots, baseline, now, earliest, kw, replay, budget, preferred=None):
    """Offer a tested useful window, adding a later run only after replanning."""
    violation = baseline['constraint_violation_score']
    morning = baseline['morning_shortfall']
    model = baseline['model']
    significant = any(min(s['room1'], s['room2']) <= model['room_min_c'] - .1
                      or s['water'] <= model['tank_min_c'] - .1 for s in baseline['steps'])
    if not significant and morning < .5:
        return None
    best = None
    for index, (start, end) in enumerate(candidate_windows(slots, baseline, now, earliest, preferred)):
        budget.check_cancelled()
        if index >= 12 or budget.remaining() < .35:
            break
        trial = replay(list(trial_slots(slots, start, end)), kw)
        after = trial['constraint_violation_score']
        after_morning = trial['morning_shortfall']
        if trial['inline_kwh'] < .02:
            continue
        # Preserve other reserves. A trivial numerical difference between two
        # integrations of the same trajectory isn't a reason to offer a run.
        helps = (after < violation - 1e-5 and after_morning <= morning + .02
                 or after <= violation + 1e-6 and after_morning < morning - .05)
        if not helps:
            continue
        cost = sum(s['inline_kw'] * s['dt'] * s['price'] for s in trial['steps'])
        offer = {'start': start, 'end': end, 'kw': kw, 'estimated_kwh': trial['inline_kwh'],
                 'estimated_cost': cost, 'constraint_before': violation, 'constraint_after': after,
                 'morning_shortfall_before': morning, 'morning_shortfall_after': after_morning}
        if after <= 1e-5 and after_morning <= .05:
            return offer
        score = (after, after_morning, trial['model_cost'])
        if best is None or score < best[0]:
            best = score, offer
    return best[1] if best else None


class Approval:
    """A response authorizes only this exact window and must arrive before start."""
    def __init__(self):
        self.offer = None
        self.token = None
        self.approved = False
        self.closed_until = 0.

    def clear(self):
        self.offer = self.token = None
        self.approved = False

    def matches(self, candidate):
        return bool(self.offer and candidate and all(self.offer[k] == candidate[k] for k in ('start', 'end', 'kw')))

    def notification(self, candidate, zone):
        self.offer = candidate.copy()
        self.token = token_hex(16)
        start, end = (datetime.fromtimestamp(candidate[k], zone).strftime('%H:%M') for k in ('start', 'end'))
        return {
            'title': 'Approve inline heating?',
            'message': (f'{start}–{end}, up to {candidate["kw"]:g} kW. '
                        f'Estimated {candidate["estimated_cost"]:.2f} SEK of inline heat. '
                        f'Approve before {start}.'),
            'data': {'tag': 'nibe-inline-approval', 'actions': [
                {'action': f'NIBE_INLINE_APPROVE_{self.token}', 'title': 'Approve this window'},
                {'action': f'NIBE_INLINE_DECLINE_{self.token}', 'title': 'Decline'},
            ]},
        }

    def respond(self, action, now):
        if not self.token or now >= self.offer['start']:
            return False
        if action == f'NIBE_INLINE_APPROVE_{self.token}':
            self.approved = True
            self.token = None
        elif action == f'NIBE_INLINE_DECLINE_{self.token}':
            self.closed_until = self.offer['end']
            self.clear()
        else:
            return False
        return True
