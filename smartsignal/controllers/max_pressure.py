"""Max-pressure baseline: serve the phase with the largest upstream-downstream
queue imbalance (Varaiya 2013). Strong classical adaptive baseline."""

from smartsignal.controllers.base import Controller
from smartsignal.env.traffic_signal import TrafficSignal


class MaxPressureController(Controller):
    name = "maxpressure"

    def __init__(self, **_):
        pass

    def decide(self, ts: TrafficSignal, sim_time: float) -> int:
        if ts.pending is not None or ts.green_elapsed < ts.min_green:
            return ts.active_target
        pressures = [ts.phase_pressure(i) for i in range(ts.num_green_phases)]
        best = max(range(len(pressures)), key=lambda i: pressures[i])
        # keep current phase on ties to avoid pointless switching
        if pressures[best] <= pressures[ts.current]:
            return ts.current
        return best
