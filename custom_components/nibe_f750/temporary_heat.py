"""Distinguish short-lived room warming from the heat pump's learned response."""
from dataclasses import dataclass
import math

SOURCE_HOURS = .5
ROOM_HOURS = 1.5
EVENT_SECONDS = 7200
NO_HEAT = ((0., 0.), (0., 0.))


def forecast_warmth(profile, hours):
    """Let both the temporary heat source and its local warmth fade."""
    retained = math.exp(-hours / ROOM_HOURS)
    source = math.exp(-hours / SOURCE_HOURS)
    accumulated = (retained - source) / (1 / SOURCE_HOURS - 1 / ROOM_HOURS)
    return tuple(excess * retained + rate * accumulated for excess, rate in profile)


def cooler_room_needs_heat(temperatures, profile, minimum):
    """A room benefiting from temporary heat cannot stand in for the other."""
    warm1, warm2 = (excess >= .15 for excess, _ in profile)
    return ((warm1 and not warm2 and temperatures[1] <= minimum + .35)
            or (warm2 and not warm1 and temperatures[0] <= minimum + .35))


def limit_offset_drop(proposed, current, supply, target, gain, max_diff, levels):
    """Trim heating without dropping the target through the native stop limit."""
    if proposed >= current:
        return proposed
    safe_target = supply - min(2., max_diff - .5)
    safe_level = next((v for v in levels if target + gain * (v - current) >= safe_target), current)
    return max(proposed, min(current, safe_level))


@dataclass
class RoomHeat:
    reported: float | None = None
    temperature: float = 0.
    expected: float = 0.
    first_rise: float = 0.
    excess: float = 0.
    rate: float = 0.
    evidence_at: float = 0.
    rate_at: float = 0.

    def observe(self, value, reported, expected, error, now):
        if self.excess and now - self.evidence_at >= EVENT_SECONDS:
            self.excess = self.rate = 0.
        self.expected += expected
        if self.reported is not None and reported - self.reported < 8 * 60:
            return
        if self.reported is not None and reported - self.reported <= 30 * 60:
            hours = (reported - self.reported) / 3600
            residual = value - self.temperature - self.expected
            threshold = max(.20, min(.35, 2 * error * math.sqrt(hours / .5)), .8 * hours)
            warming = residual >= threshold
            if self.excess or (self.first_rise and warming):
                self.excess = min(5., max(0., self.excess + self.first_rise + residual))
                if self.excess < .15:
                    self.excess = 0.
                self.rate = min(4., max(0., residual / hours)) if self.excess else 0.
                self.rate_at = reported
                if warming:
                    self.evidence_at = reported
                self.first_rise = 0.
            else:
                self.first_rise = residual if warming else 0.
        else:
            self.first_rise = 0.
        self.reported, self.temperature, self.expected = reported, value, 0.


class TemporaryHeat:
    def __init__(self):
        self.rooms = (RoomHeat(), RoomHeat())

    @property
    def active(self):
        return tuple(room.excess > 0 for room in self.rooms)

    @property
    def learning_hold(self):
        return any(room.first_rise or room.excess for room in self.rooms)

    def break_observations(self):
        for room in self.rooms:
            room.reported = None
            room.first_rise = 0.
            room.expected = 0.

    def observe(self, temperatures, reported, changes, error, now):
        for room, value, report, change in zip(self.rooms, temperatures, reported, changes):
            room.observe(value, report, change, error, now)

    def profile(self, now):
        return tuple((room.excess, room.rate * math.exp(-max(0., now - room.rate_at) / 3600 / SOURCE_HOURS))
                     if room.excess and now - room.evidence_at < EVENT_SECONDS else (0., 0.)
                     for room in self.rooms)
