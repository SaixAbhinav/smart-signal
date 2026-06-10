"""Trained PPO policy behind the common controller interface."""

from smartsignal.controllers.base import Controller
from smartsignal.env.observations import ObservationBuilder
from smartsignal.env.traffic_signal import TrafficSignal


class RLController(Controller):
    name = "rl"

    def __init__(self, model_path: str = "", max_green: int = 60, model=None, **_):
        if model is None:
            from stable_baselines3 import PPO  # deferred: heavy import

            model = PPO.load(model_path, device="cpu")
        self.model = model
        self.max_green = max_green
        self._obs_fn = None

    def reset(self, ts: TrafficSignal | None, obs_fn=None) -> None:
        if obs_fn is not None:
            self._obs_fn = obs_fn
        else:
            builder = ObservationBuilder(ts, self.max_green)
            self._obs_fn = builder.build

    def decide(self, ts: TrafficSignal, sim_time: float) -> int:
        obs = self._obs_fn()
        action, _ = self.model.predict(obs, deterministic=True)
        action = int(action)
        # mirror the env's max-green rotation so behavior matches training
        if action == ts.active_target and ts.pending is None and ts.green_elapsed >= self.max_green:
            return (ts.current + 1) % ts.num_green_phases
        return action
