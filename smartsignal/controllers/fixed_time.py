"""Fixed-timer baseline: rotate through green phases on a fixed cycle."""

from smartsignal.controllers.base import Controller
from smartsignal.env.traffic_signal import TrafficSignal


class FixedTimeController(Controller):
    name = "fixed"

    def __init__(self, green_duration: int = 30, **_):
        self.green_duration = green_duration

    def decide(self, ts: TrafficSignal, sim_time: float) -> int:
        if ts.pending is None and ts.green_elapsed >= self.green_duration:
            return (ts.current + 1) % ts.num_green_phases
        return ts.active_target
