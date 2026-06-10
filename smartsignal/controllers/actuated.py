"""SUMO's built-in gap-based actuated control.

The network's traffic light is generated with tlType="actuated", so this
controller simply leaves the signal program alone.
"""

from smartsignal.controllers.base import Controller


class ActuatedController(Controller):
    name = "actuated"
    uses_builtin_program = True

    def __init__(self, **_):
        pass

    def decide(self, ts, sim_time):  # never called
        raise RuntimeError("ActuatedController delegates to SUMO's program")
