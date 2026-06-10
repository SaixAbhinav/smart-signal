from smartsignal.controllers.base import Controller
from smartsignal.controllers.fixed_time import FixedTimeController
from smartsignal.controllers.actuated import ActuatedController
from smartsignal.controllers.max_pressure import MaxPressureController
from smartsignal.controllers.rl_agent import RLController

CONTROLLERS = {
    "fixed": FixedTimeController,
    "actuated": ActuatedController,
    "maxpressure": MaxPressureController,
    "rl": RLController,
}

__all__ = [
    "Controller",
    "FixedTimeController",
    "ActuatedController",
    "MaxPressureController",
    "RLController",
    "CONTROLLERS",
]
