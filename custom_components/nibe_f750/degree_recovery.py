"""Detect sudden losses of space-heating demand and recover via the C1 offset."""
from .engine import C1, PRIORITY, REQUIRED, ROOM1, ROOM2, SUPPLY, fresh, number, offset_levels
from .offset import DM

FREQUENCY = 'sensor.vp_current_compressor_frequency'
SAMPLE_GAP = 6 * 60
RECOVERY_LIMIT = 2 * 3600


def reading(states, entity, now):
    state = states.get(entity)
    return number(state.state) if fresh(state, now) else None


def heating_available(states, now):
    priority = states.get(PRIORITY)
    if not fresh(priority, now) or priority.state not in ('Heating', 'Off'):
        return False
    return not any(fresh(status, now) and any(s in status.state.lower() for s in ('defrost', 'avfrost'))
                   for status in (states.get('sensor.vp_status'), states.get('sensor.vp_status_compressor')))


class DegreeMinuteRecovery:
    def __init__(self):
        self.previous = None
        self.event = None

    @property
    def active(self):
        return self.event is not None and self.event['status'] == 'Recovering'

    def restore(self, saved):
        if not isinstance(saved, dict) or not isinstance(saved.get('status'), str):
            return
        started, target, observed = (number(saved.get(k)) for k in ('started_at', 'target_dm', 'reset_dm'))
        if None not in (started, target, observed) and -3000 <= target <= -120 and abs(observed) <= 20:
            self.event = {**saved, 'started_at': started, 'target_dm': target, 'reset_dm': observed}

    def finish(self, status, now):
        self.previous = None
        if not self.active:
            return False
        self.event = {**self.event, 'status': status, 'ended_at': now}
        return True

    def observe(self, states, now, enabled, action, room_max):
        if not enabled:
            return self.finish('Paused', now)
        dm = reading(states, DM, now)
        rooms = [reading(states, e, now) for e in (ROOM1, ROOM2)]
        if self.active:
            if dm is not None and -3000 <= dm <= self.event['target_dm']:
                return self.finish('Restored', now)
            if any(room is not None and room >= room_max for room in rooms):
                return self.finish('Room limit reached', now)
            if not 0 <= now - self.event['started_at'] < RECOVERY_LIMIT:
                return self.finish('Timed out', now)
            return False

        supply = reading(states, SUPPLY, now)
        target = reading(states, REQUIRED, now)
        hz = reading(states, FREQUENCY, now)
        if (None in (dm, supply, target, hz) or not -3000 <= dm <= 1000
                or not 5 <= supply <= 90 or not 5 <= target <= 80
                or not heating_available(states, now)):
            self.previous = None
            return False
        running = states[PRIORITY].state == 'Heating' and hz > 0
        at = (getattr(states[DM], 'last_changed', None) or states[DM].last_reported).timestamp()
        previous = self.previous
        if previous is None or at > previous['time']:
            self.previous = {'time': at, 'dm': dm, 'supply': supply, 'target': target, 'running': running}
        if not previous or not previous['running'] or action == 'off':
            return False
        elapsed = at - previous['time']
        if not 0 < elapsed <= SAMPLE_GAP or not -3000 <= previous['dm'] <= -120 or abs(dm) > 20:
            return False
        # Bound the fastest plausible ordinary recovery using both ends of the
        # interval. A margin tolerates staggered myUplink reports.
        overshoot = max(previous['supply'], supply) - min(previous['target'], target)
        if dm - previous['dm'] <= max(0., overshoot) * elapsed / 60 + 25:
            return False
        self.event = {'status': 'Recovering', 'started_at': now, 'target_dm': previous['dm'], 'reset_dm': dm}
        if any(room is not None and room >= room_max for room in rooms):
            self.finish('Room limit reached', now)
        return True

    def offset(self, states, now, room_max, gain):
        """Rebuild the deficit using the existing actuator and native bounds."""
        if not self.active:
            return None
        current = reading(states, C1, now)
        if current is None:
            return None
        dm = reading(states, DM, now)
        supply = reading(states, SUPPLY, now)
        target = reading(states, REQUIRED, now)
        rooms = [reading(states, e, now) for e in (ROOM1, ROOM2)]
        if (None in (dm, supply, target, *rooms) or not 5 <= supply <= 90 or not 5 <= target <= 80
                or not all(5 <= room < room_max for room in rooms) or not heating_available(states, now)
                or dm <= self.event['target_dm']):
            return current
        # Aim to rebuild the missing demand over roughly an hour if the native
        # curve has enough headroom. Keep the offset steady as the gap closes.
        gap = min(12., max(3., (dm - self.event['target_dm']) / 60))
        gain = gain if gain is not None and 0 < gain <= 10 else 2.5
        levels = offset_levels(states[C1])
        return next((level for level in levels
                     if level >= current and target + gain * (level - current) >= supply + gap),
                    max(current, levels[-1]) if levels else current)
