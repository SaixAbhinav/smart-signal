"""Uniform controller interface used by evaluation and the dashboard.

A controller is asked every decision interval which green phase it wants.
Controllers with `uses_builtin_program = True` (SUMO's actuated logic) are
never asked - the simulation's own signal program runs untouched.
"""

from smartsignal.env.traffic_signal import TrafficSignal


class Controller:
    name = "base"
    uses_builtin_program = False

    def reset(self, ts: TrafficSignal | None) -> None:
        """Called once at episode start. ts is None for builtin-program controllers."""

    def decide(self, ts: TrafficSignal, sim_time: float) -> int:
        """Return the desired green phase index for this decision interval."""
        raise NotImplementedError
