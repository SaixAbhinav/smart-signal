"""Gymnasium environment for a single SUMO-controlled intersection.

Action: index of the green phase to serve next (Discrete). The TrafficSignal
wrapper enforces min-green and yellow transitions; this env force-rotates the
phase when max-green is exceeded, so no action sequence can starve an approach
forever or produce an unsafe signal state.
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from smartsignal.env.observations import ObservationBuilder
from smartsignal.env.rewards import REWARDS
from smartsignal.env.sumo_utils import build_sumo_cmd, close_sumo, start_sumo
from smartsignal.env.traffic_signal import TrafficSignal


class SingleIntersectionEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        net_file: str,
        route_files: list[str] | str,
        episode_seconds: int = 3600,
        delta_time: int = 5,
        yellow_time: int = 3,
        min_green: int = 10,
        max_green: int = 60,
        reward: str = "diff_waiting",
        use_gui: bool = False,
        use_libsumo: bool = False,
        sumo_seed: int | None = None,
    ):
        super().__init__()
        self.net_file = net_file
        self.route_files = (
            [route_files] if isinstance(route_files, str) else list(route_files)
        )
        self.episode_seconds = episode_seconds
        self.delta_time = delta_time
        self.yellow_time = yellow_time
        self.min_green = min_green
        self.max_green = max_green
        self.reward_name = reward
        self.use_gui = use_gui
        self.use_libsumo = use_libsumo
        self.sumo_seed = sumo_seed

        self.conn = None
        self.ts: TrafficSignal | None = None
        self.sim_time = 0.0
        self.arrived_total = 0

        n_phases, n_lanes = self._probe_network()
        self.action_space = spaces.Discrete(n_phases)
        obs_size = 3 * n_lanes + n_phases + 1
        self.observation_space = spaces.Box(0.0, 1.0, (obs_size,), np.float32)

    def _probe_network(self) -> tuple[int, int]:
        """Open the net once (TraCI subprocess) to size the spaces."""
        cmd = build_sumo_cmd(self.net_file, self.route_files[0], seed=0)
        conn = start_sumo(cmd, use_libsumo=False)
        try:
            ts_id = conn.trafficlight.getIDList()[0]
            ts = TrafficSignal(conn, ts_id, self.yellow_time, self.min_green)
            return ts.num_green_phases, len(ts.in_lanes)
        finally:
            close_sumo(conn)

    # ---- gym API -------------------------------------------------------------

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if self.conn is not None:
            close_sumo(self.conn)
            self.conn = None

        route_file = self.route_files[
            int(self.np_random.integers(len(self.route_files)))
            if len(self.route_files) > 1
            else 0
        ]
        sim_seed = (
            self.sumo_seed
            if self.sumo_seed is not None
            else int(self.np_random.integers(0, 2**31 - 1))
        )
        cmd = build_sumo_cmd(
            self.net_file, route_file, gui=self.use_gui, seed=sim_seed
        )
        self.conn = start_sumo(cmd, use_libsumo=self.use_libsumo)
        ts_id = self.conn.trafficlight.getIDList()[0]
        self.ts = TrafficSignal(self.conn, ts_id, self.yellow_time, self.min_green)
        self.obs_builder = ObservationBuilder(self.ts, self.max_green)
        self.reward_fn = REWARDS[self.reward_name](self.ts)
        self.sim_time = 0.0
        self.arrived_total = 0
        return self.obs_builder.build(), {}

    def step(self, action):
        action = int(action)
        ts = self.ts
        if action != ts.active_target:
            ts.request_phase(action)
        elif ts.pending is None and ts.green_elapsed >= self.max_green:
            ts.request_phase((ts.current + 1) % ts.num_green_phases)

        for _ in range(self.delta_time):
            self.conn.simulationStep()
            ts.tick(1.0)
            self.arrived_total += self.conn.simulation.getArrivedNumber()
        self.sim_time += self.delta_time

        obs = self.obs_builder.build()
        reward = float(self.reward_fn())
        truncated = self.sim_time >= self.episode_seconds
        info = {
            "sim_time": self.sim_time,
            "total_queued": ts.total_queued(),
            "total_waiting": self.reward_fn.prev
            if hasattr(self.reward_fn, "prev")
            else ts.total_waiting(),
            "arrived_total": self.arrived_total,
        }
        return obs, reward, False, truncated, info

    def close(self):
        if self.conn is not None:
            close_sumo(self.conn)
            self.conn = None

    def __del__(self):
        self.close()
