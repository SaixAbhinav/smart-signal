"""Trained PPO policy behind the common controller interface."""

from smartsignal.controllers.base import Controller
from smartsignal.env.observations import ObservationBuilder
from smartsignal.env.traffic_signal import TrafficSignal


class RLController(Controller):
    name = "rl"

    def __init__(self, model_path: str, max_green: int = 60, **_):
        from stable_baselines3 import PPO  # deferred: heavy import

        self.model = PPO.load(model_path, device="cpu")
        self.max_green = max_green
        self.obs_builder: ObservationBuilder | None = None

    def reset(self, ts: TrafficSignal | None) -> None:
        self.obs_builder = ObservationBuilder(ts, self.max_green)

    def decide(self, ts: TrafficSignal, sim_time: float) -> int:
        obs = self.obs_builder.build()
        action, _ = self.model.predict(obs, deterministic=True)
        action = int(action)
        # mirror the env's max-green rotation so behavior matches training
        if action == ts.active_target and ts.pending is None and ts.green_elapsed >= self.max_green:
            return (ts.current + 1) % ts.num_green_phases
        return action
