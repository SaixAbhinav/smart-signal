"""Reward functions. All are stateful "diff" rewards computed per decision step."""

from smartsignal.env.traffic_signal import TrafficSignal

WAIT_SCALE = 100.0


class DiffWaitingReward:
    """Negative change in cumulative accumulated waiting time on incoming lanes.

    Positive when the agent reduced total waiting since the last decision.
    The standard dense reward for signal control (IntelliLight, sumo-rl).
    """

    def __init__(self, ts: TrafficSignal):
        self.ts = ts
        self.prev = ts.total_waiting()

    def __call__(self) -> float:
        cur = self.ts.total_waiting()
        r = (self.prev - cur) / WAIT_SCALE
        self.prev = cur
        return r


class PressureReward:
    """Negative absolute pressure (queued in minus queued out). Alternative."""

    def __init__(self, ts: TrafficSignal):
        self.ts = ts

    def __call__(self) -> float:
        total = sum(
            self.ts.phase_pressure(i) for i in range(self.ts.num_green_phases)
        )
        return -total / 50.0


REWARDS = {"diff_waiting": DiffWaitingReward, "pressure": PressureReward}
