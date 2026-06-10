"""Observation vector for one intersection.

Per incoming lane: [queue density, vehicle density, normalized waiting time],
then a one-hot of the active (or transitioning-to) green phase, then the
normalized time the current green has been active. Everything is in [0, 1].
"""

import numpy as np

from smartsignal.env.traffic_signal import TrafficSignal

WAIT_NORM = 500.0  # seconds of summed lane waiting time mapped to 1.0


class ObservationBuilder:
    def __init__(self, ts: TrafficSignal, max_green: int):
        self.ts = ts
        self.max_green = max_green
        self.size = 3 * len(ts.in_lanes) + ts.num_green_phases + 1

    def build(self) -> np.ndarray:
        ts = self.ts
        obs = np.zeros(self.size, dtype=np.float32)
        i = 0
        for lane, s in ts.lane_states().items():
            capacity = max(s.length / TrafficSignal.VEHICLE_GAP, 1.0)
            obs[i] = min(s.queue / capacity, 1.0)
            obs[i + 1] = min(s.vehicles / capacity, 1.0)
            obs[i + 2] = min(s.waiting / WAIT_NORM, 1.0)
            i += 3
        obs[i + ts.active_target] = 1.0
        i += ts.num_green_phases
        obs[i] = min(ts.green_elapsed / self.max_green, 1.0)
        return obs
