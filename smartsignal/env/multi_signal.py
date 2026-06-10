"""All traffic signals of one simulation, with neighbor-aware observations.

Each junction's observation is its own lane state (same layout as the single
intersection) plus, when the network has multiple junctions, four extra values:
the normalized total queue at the neighboring junction to the N/S/E/W (0 where
there is no neighbor). Junction adjacency is derived from the "A__B" edge
naming convention used by scripts/build_grid.py.
"""

import numpy as np

from smartsignal.env.observations import ObservationBuilder
from smartsignal.env.rewards import DiffWaitingReward
from smartsignal.env.traffic_signal import TrafficSignal

NEIGHBOR_QUEUE_NORM = 50.0
DIRECTIONS = "NSEW"


class SignalNetwork:
    def __init__(self, conn, yellow_time: int = 3, min_green: int = 10, max_green: int = 60):
        self.conn = conn
        self.max_green = max_green
        self.ids = sorted(conn.trafficlight.getIDList())
        self.signals = {
            t: TrafficSignal(conn, t, yellow_time, min_green) for t in self.ids
        }
        self.obs_builders = {
            t: ObservationBuilder(self.signals[t], max_green) for t in self.ids
        }
        self.reward_fns = {
            t: DiffWaitingReward(self.signals[t]) for t in self.ids
        }

        edge_ids = set(conn.edge.getIDList())
        positions = {t: conn.junction.getPosition(t) for t in self.ids}
        self.neighbors: dict[str, dict[str, str | None]] = {}
        for t in self.ids:
            nbrs: dict[str, str | None] = {d: None for d in DIRECTIONS}
            for other in self.ids:
                if other == t or f"{other}__{t}" not in edge_ids:
                    continue
                dx = positions[other][0] - positions[t][0]
                dy = positions[other][1] - positions[t][1]
                d = ("E" if dx > 0 else "W") if abs(dx) > abs(dy) else ("N" if dy > 0 else "S")
                nbrs[d] = other
            self.neighbors[t] = nbrs
        self.has_neighbors = any(
            n is not None for nbrs in self.neighbors.values() for n in nbrs.values()
        )

    @property
    def obs_size(self) -> int:
        base = self.obs_builders[self.ids[0]].size
        return base + (len(DIRECTIONS) if self.has_neighbors else 0)

    @property
    def num_green_phases(self) -> int:
        return self.signals[self.ids[0]].num_green_phases

    def observe(self, tls_id: str) -> np.ndarray:
        base = self.obs_builders[tls_id].build()
        if not self.has_neighbors:
            return base
        extra = np.zeros(len(DIRECTIONS), dtype=np.float32)
        for i, d in enumerate(DIRECTIONS):
            nbr = self.neighbors[tls_id][d]
            if nbr is not None:
                extra[i] = min(
                    self.signals[nbr].total_queued() / NEIGHBOR_QUEUE_NORM, 1.0
                )
        return np.concatenate([base, extra])

    def reward(self, tls_id: str) -> float:
        return float(self.reward_fns[tls_id]())

    def tick(self, dt: float = 1.0) -> None:
        for ts in self.signals.values():
            ts.tick(dt)

    def total_queued(self) -> int:
        return sum(ts.total_queued() for ts in self.signals.values())
