"""Compare inline permission plans and track one phone approval per horizon."""
from datetime import datetime, time, timedelta
import math
from secrets import token_hex

from .dhw import next_deadline
from .economics import EPSILON, Recovery, plan_limits, selection_key
from .engine import fresh, number

CAP_ENTITY = 'select.vp_set_max_electrical_add'
STATUS_ENTITY = 'sensor.vp_int_elec_add_heat'
EVENT = 'mobile_app_notification_action'
PRICE_QUARTER = 900
WINDOW_SECONDS = 960
VISIBLE_HORIZON = 12 * 3600
OFFER_LEAD = 3600
MIN_LEAD = 300
START_GRACE = 90
WRITE_INTERVAL = 902


def request_due(now, start, zone):
    """Bring requests that would fall in quiet hours forward to 21:45."""
    local_now = datetime.fromtimestamp(now, zone)
    if local_now.hour >= 22 or local_now.hour < 6 or start - now < MIN_LEAD:
        return False
    due = start - OFFER_LEAD
    local_due = datetime.fromtimestamp(due, zone)
    if local_due.hour >= 22 or local_due.hour < 6:
        evening = local_due.date()
        if local_due.hour < 6:
            evening -= timedelta(days=1)
        due = datetime.combine(evening, time(21, 45), zone).timestamp()
    return now >= due


def power_option(state, kw):
    for option in getattr(state, 'attributes', {}).get('options', ()):
        if isinstance(option, str) and number(option.lower().removesuffix('kw').strip()) == kw:
            return option
    return None


def supports_window(states, now, kw):
    cap = states.get(CAP_ENTITY)
    status = states.get(STATUS_ENTITY)
    return (fresh(cap, now) and fresh(status, now) and status.state in ('Off', 'Blocked', 'Active')
            and bool(power_option(cap, 0) and power_option(cap, kw)))


def trial_slots(slots, windows):
    """Split at permission boundaries while retaining the original prices."""
    boundaries = sorted({point for window in windows for point in window})
    for slot in slots:
        cuts = [slot['start'], *(p for p in boundaries if slot['start'] < p < slot['end']), slot['end']]
        for start, end in zip(cuts, cuts[1:]):
            yield {**slot, 'start': start, 'end': end, 'dt': (end - start) / 3600,
                   'inline_allowed': any(a <= start < b for a, b in windows)}


def candidate_windows(slots, baseline, now, earliest, horizon_end, follow_up=False):
    """Order reachable quarters by duration-weighted price, before a shortfall."""
    model = baseline['model']
    shortfall_at = next((s['end'] for s in baseline['steps']
                         if min(s['room1'], s['room2']) < model['room_min_c']
                         or s['water'] < model['tank_min_c']), None)
    if shortfall_at is None and baseline['morning_shortfall'] > .05:
        shortfall_at = next_deadline(now, model['timezone'])
    if shortfall_at is None:
        return
    # If recovery is already needed, still consider upcoming opportunities.
    cutoff = horizon_end if follow_up else max(shortfall_at, now + 2 * 3600)
    first = math.ceil(max(now + MIN_LEAD, earliest) / PRICE_QUARTER) * PRICE_QUARTER
    last = min(cutoff, horizon_end - WINDOW_SECONDS)
    windows = []
    for start in range(first, int(last) + 1, PRICE_QUARTER):
        end = start + WINDOW_SECONDS
        energy_price = sum(s['price'] * max(0., min(end, s['end']) - max(start, s['start']))
                           for s in slots) / WINDOW_SECONDS
        windows.append((energy_price, start, end))
    for _, start, end in sorted(windows):
        yield start, end


def add_window(windows, candidate):
    """Group adjacent quarters and leave time to close and reopen separate runs."""
    combined = []
    for start, end in sorted([*windows, candidate]):
        if combined:
            last_start, last_end = combined[-1]
            if start < last_end:
                combined[-1] = (last_start, max(last_end, end))
                continue
            if start < last_end + WRITE_INTERVAL + START_GRACE:
                return None
        combined.append((start, end))
    return combined if combined != windows else None


def improves(before, after):
    violation, morning = before['constraint_violation_score'], before['morning_shortfall']
    after_violation, after_morning = after['constraint_violation_score'], after['morning_shortfall']
    # Preserve other reserves and ignore numerical differences between replays.
    return (after_violation < violation - 1e-5 and after_morning <= morning + .02
            or after_violation <= violation + 1e-6 and after_morning < morning - .05)


def describe_plan(windows, prediction, kw, horizon_end):
    runs = []
    activity = []
    for start, end in windows:
        energy = cost = 0.
        draw = []
        for step in prediction['steps']:
            if step['inline_kw'] <= 0 or step['end'] <= start or step['start'] >= end:
                continue
            for part in step.get('activity', [step]):
                a, b = max(start, part['start']), min(end, part['end'])
                power = part['inline_kw']
                if a < b and power > 0:
                    kwh = power * (b - a) / 3600
                    energy += kwh
                    cost += kwh * step['price']
                    draw.append({'start': a, 'end': b, 'inline_kw': power, 'action': part.get('action', 'heat')})
        if energy >= .02:
            runs.append({'start': start, 'end': end, 'kw': kw,
                         'estimated_kwh': energy, 'estimated_cost': cost})
            activity.extend(draw)
    return {'windows': runs, 'horizon_end': horizon_end, 'activity': activity} if runs else None


def compare_windows(slots, baseline, now, earliest, kw, replay, budget, preferred=None):
    """Build a useful low-price plan, or recheck only previously offered windows."""
    model = baseline['model']
    significant = any(min(s['room1'], s['room2']) <= model['room_min_c'] - .1
                      or s['water'] <= model['tank_min_c'] - .1 for s in baseline['steps'])
    if not significant and baseline['morning_shortfall'] < .5:
        return None

    horizon_end = min(slots[-1]['end'], now + VISIBLE_HORIZON)
    # If the compressor already reaches the room and water targets, optional
    # resistance heat must compete against that recovery on cost. A faster
    # trial cannot create an earlier deadline and thereby require itself.
    limits = None
    if 'recovery' in baseline:
        recovery = Recovery.from_plan(baseline)
        if recovery.end_deficit_c <= EPSILON and recovery.morning_shortfall_c <= EPSILON:
            planned = baseline.get('planning', {}).get('recovery_limits')
            limits = Recovery(**planned) if planned else plan_limits((baseline,), model)

    def cheapest(candidates):
        goals = limits if limits is not None else plan_limits((plan for _, plan in candidates), model)
        return min(candidates, key=lambda candidate: (selection_key(candidate[1], goals), len(candidate[0])))

    if preferred is not None:
        windows = [(w['start'], w['end']) for w in preferred['windows']
                   if w['kw'] == kw and max(now, earliest) < w['start'] + START_GRACE
                   and w['end'] <= horizon_end]
        if not windows or budget.remaining() < .35:
            return None
        trial = replay(list(trial_slots(slots, windows)), kw)
        if improves(baseline, trial) and cheapest([((), baseline), (windows, trial)])[0]:
            return describe_plan(windows, trial, kw, preferred['horizon_end'])
        return None

    windows = []
    current = baseline
    attempted = set()
    evaluated = [((), baseline)]
    ranked_quarters = list(candidate_windows(slots, baseline, now, earliest, horizon_end, follow_up=True))

    def evaluate(candidate):
        attempted.add(tuple(candidate))
        trial = replay(list(trial_slots(slots, candidate)), kw)
        if trial['inline_kwh'] >= .02 and improves(baseline, trial):
            item = (candidate, trial)
            evaluated.append(item)
            return item
        return None

    # Bound the RPi work. Each addition is evaluated with all earlier choices
    # so successive quarters cover the remaining shortfall. Save time for
    # replacing a separated run with an adjacent cheaper quarter.
    while len(attempted) < 18 and budget.remaining() >= .35:
        children = []
        checks = 0
        ordered = list(candidate_windows(slots, current, now, earliest, horizon_end, follow_up=bool(windows)))
        adjacent = [w for w in ordered if any(w[0] < e and w[1] > s for s, e in windows)]
        if not windows and ordered:
            start, end = ordered[0]
            adjacent = [(start, end + extra * PRICE_QUARTER) for extra in (1, 3)
                        if end + extra * PRICE_QUARTER <= horizon_end]
            # Test later bargains on their own before committing to an early
            # run. The full replay checks any room or hot-water shortfall.
            ordered = list(dict.fromkeys([ordered[0], *ranked_quarters[:3], *ordered[1:]]))
        for candidate in dict.fromkeys([*ordered[:1], *adjacent[:2], *ordered[1:]]):
            budget.check_cancelled()
            if len(attempted) >= 18 or checks >= 6 or budget.remaining() < .35:
                break
            combined = add_window(windows, candidate)
            if combined is None or tuple(combined) in attempted:
                continue
            checks += 1
            result = evaluate(combined)
            if result and improves(current, result[1]):
                children.append(result)
        if not children:
            break
        windows, current = cheapest(children)
        if current['constraint_violation_score'] <= 1e-8 and current['morning_shortfall'] <= 1e-8:
            break

    # Greedy additions can strand a pricier separate run. Compare removing
    # each run and spending its time next to one of the remaining runs.
    windows, current = cheapest(evaluated)
    if not windows and len(evaluated) > 1:
        windows, current = cheapest(evaluated[1:])
    for removed in reversed(windows):
        surviving = [w for w in windows if w != removed]
        if not surviving:
            break
        options = [surviving]
        adjacent = [w for w in ranked_quarters if any(w[0] < e and w[1] > s for s, e in surviving)]
        for quarter in adjacent:
            grown = add_window(surviving, quarter)
            if grown:
                options.append(grown)
        for candidate in options:
            budget.check_cancelled()
            if len(attempted) >= 24 or budget.remaining() < .35:
                break
            if tuple(candidate) not in attempted:
                evaluate(candidate)
        if len(attempted) >= 24 or budget.remaining() < .35:
            break
    windows, current = cheapest(evaluated)
    return describe_plan(windows, current, kw, horizon_end) if windows else None


class Approval:
    """A phone reply authorizes a fixed set of windows up to its original horizon."""
    def __init__(self):
        self.offer = None
        self.token = None
        self.approved = False
        self.used_until = 0.
        self.closed_until = 0.

    def clear(self):
        self.offer = self.token = None
        self.approved = False
        self.used_until = 0.

    def close(self):
        self.closed_until = self.offer['horizon_end']
        self.clear()

    def expire(self, now):
        if self.offer and now >= self.offer['horizon_end']:
            self.clear()
            return True
        if self.offer and not self.approved and now >= self.offer['windows'][0]['start']:
            self.close()
            return True
        return False

    def next_window(self, now, forecast):
        """Return the next offered window the latest evaluation still needs."""
        if not self.offer or not forecast:
            return None
        planned = {(w['start'], w['end'], w['kw']) for w in forecast['windows']}
        return next((w for w in self.offer['windows']
                     if self.used_until <= w['start'] and now < w['start'] + START_GRACE
                     and (w['start'], w['end'], w['kw']) in planned), None)

    def notification(self, plan, zone, approval_entity=None):
        self.offer = plan
        self.token = token_hex(16)
        windows = plan['windows']
        def when(timestamp):
            return datetime.fromtimestamp(timestamp, zone).strftime('%a %H:%M')
        times = ', '.join(f"{when(w['start'])}–{when(w['end'])}" for w in windows)
        total = sum(w['estimated_cost'] for w in windows)
        instructions = 'Press and hold for actions'
        destinations = {}
        if approval_entity:
            destination = f'/?more-info-entity-id={approval_entity}'
            destinations = {'url': destination, 'clickAction': destination}
            instructions = 'Press and hold for actions or tap to review'
        return {
            'title': 'Approve inline heating plan?',
            'message': (f"{times}. Up to {windows[0]['kw']:g} kW, estimated {total:.2f} SEK total. "
                        f"Reply before {when(windows[0]['start'])}. Plan through {when(plan['horizon_end'])}. {instructions}."),
            'data': {'tag': 'nibe-inline-approval', **destinations, 'actions': [
                {'action': f'NIBE_INLINE_APPROVE_{self.token}', 'title': 'Approve plan', 'authenticationRequired': True},
                {'action': f'NIBE_INLINE_DECLINE_{self.token}', 'title': 'Decline'},
            ]},
        }

    def approve(self, now):
        return self.respond(f'NIBE_INLINE_APPROVE_{self.token}', now)

    def respond(self, action, now):
        if not self.token or now >= self.offer['windows'][0]['start']:
            return False
        if action == f'NIBE_INLINE_APPROVE_{self.token}':
            self.approved = True
            self.token = None
        elif action == f'NIBE_INLINE_DECLINE_{self.token}':
            self.close()
        else:
            return False
        return True

    def dump(self, service):
        return {'service': service, 'offer': self.offer, 'token': self.token,
                'approved': self.approved, 'used_until': self.used_until,
                'closed_until': self.closed_until}

    def restore(self, saved, service, now):
        """Restore pending decisions without sending a second phone request."""
        if not isinstance(saved, dict) or saved.get('service') != service:
            return
        self.closed_until = number(saved.get('closed_until')) or 0.
        offer = saved.get('offer')
        if not offer:
            return
        if not isinstance(offer, dict) or not isinstance(offer.get('windows'), list) or not offer['windows']:
            return
        horizon_end = number(offer.get('horizon_end'))
        if horizon_end is None or not now < horizon_end <= now + VISIBLE_HORIZON:
            return
        last_end = 0.
        for window in offer['windows']:
            if not isinstance(window, dict):
                return
            start, end, kw = (number(window.get(k)) for k in ('start', 'end', 'kw'))
            if (None in (start, end, kw) or (start, end, kw) != (window['start'], window['end'], window['kw'])
                    or not last_end <= start < end <= horizon_end or not 0 < kw <= 6.5):
                return
            last_end = end
        token = saved.get('token')
        approved = saved.get('approved') is True
        if not approved and not (isinstance(token, str) and len(token) == 32):
            return
        self.offer = offer
        self.approved = approved
        self.token = None if approved else token
        self.used_until = number(saved.get('used_until')) or 0.
