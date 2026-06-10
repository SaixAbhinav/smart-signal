"""Multi-junction VecEnv: one SUMO simulation, one VecEnv slot per junction.

This is how the shared policy is trained: PPO sees N junctions as N parallel
environments, so every junction's (obs, action, reward) transition trains the
same network — parameter sharing with independent execution. Episodes are
synchronized: all junctions truncate together when the simulation ends.
"""

import random

import numpy as np
from gymnasium import spaces
from stable_baselines3.common.vec_env.base_vec_env import VecEnv

from smartsignal.env.multi_signal import SignalNetwork
from smartsignal.env.sumo_utils import build_sumo_cmd, close_sumo, start_sumo
from smartsignal.evaluation.runner import apply_decision


class MultiSignalVecEnv(VecEnv):
    def __init__(
        self,
        net_file: str,
        route_files: list[str] | str,
        episode_seconds: int = 3600,
        delta_time: int = 5,
        yellow_time: int = 3,
        min_green: int = 10,
        max_green: int = 60,
        use_libsumo: bool = True,
        seed: int = 0,
    ):
        self.net_file = net_file
        self.route_files = (
            [route_files] if isinstance(route_files, str) else list(route_files)
        )
        self.episode_seconds = episode_seconds
        self.delta_time = delta_time
        self.yellow_time = yellow_time
        self.min_green = min_green
        self.max_green = max_green
        self.use_libsumo = use_libsumo
        self.rng = random.Random(seed)

        # size the spaces with a short-lived TraCI probe
        conn = start_sumo(
            build_sumo_cmd(net_file, self.route_files[0], seed=0), use_libsumo=False
        )
        try:
            probe = SignalNetwork(conn, yellow_time, min_green, max_green)
            self.tls_ids = probe.ids
            obs_size = probe.obs_size
            n_phases = probe.num_green_phases
        finally:
            close_sumo(conn)

        super().__init__(
            num_envs=len(self.tls_ids),
            observation_space=spaces.Box(0.0, 1.0, (obs_size,), np.float32),
            action_space=spaces.Discrete(n_phases),
        )
        self.render_mode = None
        self.conn = None
        self.network: SignalNetwork | None = None
        self.sim_time = 0
        self._actions = None

    # ---- simulation lifecycle -------------------------------------------------

    def _start_sim(self) -> None:
        if self.conn is not None:
            close_sumo(self.conn)
        route = self.rng.choice(self.route_files)
        cmd = build_sumo_cmd(
            self.net_file, route, seed=self.rng.randrange(2**31 - 1)
        )
        self.conn = start_sumo(cmd, use_libsumo=self.use_libsumo)
        self.network = SignalNetwork(
            self.conn, self.yellow_time, self.min_green, self.max_green
        )
        self.sim_time = 0

    def _obs(self) -> np.ndarray:
        return np.stack([self.network.observe(t) for t in self.tls_ids])

    # ---- VecEnv API -------------------------------------------------------------

    def reset(self) -> np.ndarray:
        self._start_sim()
        return self._obs()

    def step_async(self, actions: np.ndarray) -> None:
        self._actions = actions

    def step_wait(self):
        for t, a in zip(self.tls_ids, self._actions):
            apply_decision(self.network.signals[t], int(a), self.max_green)
        for _ in range(self.delta_time):
            self.conn.simulationStep()
            self.network.tick(1.0)
        self.sim_time += self.delta_time

        rewards = np.array(
            [self.network.reward(t) for t in self.tls_ids], dtype=np.float32
        )
        done = self.sim_time >= self.episode_seconds
        if done:
            terminal_obs = self._obs()
            infos = [
                {"terminal_observation": terminal_obs[i], "TimeLimit.truncated": True}
                for i in range(self.num_envs)
            ]
            self._start_sim()
            obs = self._obs()
            dones = np.ones(self.num_envs, dtype=bool)
        else:
            obs = self._obs()
            infos = [{} for _ in range(self.num_envs)]
            dones = np.zeros(self.num_envs, dtype=bool)
        return obs, rewards, dones, infos

    def close(self) -> None:
        if self.conn is not None:
            close_sumo(self.conn)
            self.conn = None

    # ---- introspection plumbing required by the VecEnv ABC ----------------------

    def get_attr(self, attr_name, indices=None):
        n = self.num_envs if indices is None else len(self._get_indices(indices))
        return [getattr(self, attr_name, None)] * n

    def set_attr(self, attr_name, value, indices=None):
        setattr(self, attr_name, value)

    def env_method(self, method_name, *args, indices=None, **kwargs):
        raise NotImplementedError("MultiSignalVecEnv slots are not separate envs")

    def env_is_wrapped(self, wrapper_class, indices=None):
        n = self.num_envs if indices is None else len(self._get_indices(indices))
        return [False] * n
