"""Uniform controller interface used by evaluation and the dashboard.

A controller is asked every decision interval which green phase it wants.
Controllers with `uses_builtin_program = True` (SUMO's actuated logic) are
never asked - the simulation's own signal program runs untouched.
"""

from smartsignal.env.traffic_signal import TrafficSignal


class Controller:
    name = "base"
    uses_builtin_program = False

    def reset(self, ts: TrafficSignal | None, obs_fn=None) -> None:
        """Called once at episode start, once per controlled junction.

        ts is None for builtin-program controllers. obs_fn, when given, returns
        the observation vector for this junction (used by the RL controller so
        it sees exactly what it saw in training, incl. neighbor features).
        """

    def decide(self, ts: TrafficSignal, sim_time: float) -> int:
        """Return the desired green phase index for this decision interval."""
        raise NotImplementedError
