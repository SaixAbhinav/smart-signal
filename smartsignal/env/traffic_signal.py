"""Wrapper around one SUMO traffic light: phase control with safety constraints.

The agent (or a baseline controller) only ever requests "which green phase
next". This class owns the unsafe details: it discovers the green phases from
the network's signal program, inserts the mandatory yellow transition, and
enforces minimum green time. Maximum green is enforced by the caller (env /
runner) because it is a policy decision which phase to rotate to.
"""

from dataclasses import dataclass


def make_yellow_state(old: str, new: str) -> str:
    """Transition state between two green states: signals losing their green
    turn yellow, everything else keeps its old color."""
    return "".join(
        "y" if o in "Gg" and n in "rs" else o for o, n in zip(old, new)
    )


@dataclass
class LaneState:
    queue: int          # halted vehicles
    vehicles: int       # all vehicles on lane
    waiting: float      # summed accumulated waiting time (s)
    length: float       # lane length (m)


class TrafficSignal:
    VEHICLE_GAP = 7.5  # avg vehicle length + min gap, for density normalization

    def __init__(self, conn, ts_id: str, yellow_time: int = 3, min_green: int = 10):
        self.conn = conn
        self.id = ts_id
        self.yellow_time = yellow_time
        self.min_green = min_green

        controlled = conn.trafficlight.getControlledLanes(ts_id)
        self.in_lanes = list(dict.fromkeys(controlled))  # dedupe, keep order
        self.lane_lengths = {l: conn.lane.getLength(l) for l in self.in_lanes}

        # (in_lane, out_lane) per signal index, for pressure computations
        self.links = [
            (link[0][0], link[0][1]) if link else None
            for link in conn.trafficlight.getControlledLinks(ts_id)
        ]

        logic = conn.trafficlight.getAllProgramLogics(ts_id)[0]
        self.green_phases = [
            p.state
            for p in logic.phases
            if "y" not in p.state and ("G" in p.state or "g" in p.state)
        ]
        if len(self.green_phases) < 2:
            raise ValueError(f"TLS {ts_id} has fewer than 2 green phases")
        self.num_green_phases = len(self.green_phases)

        self.current = 0
        self.green_elapsed = 0.0     # seconds current green has been active
        self.pending: int | None = None
        self.yellow_remaining = 0.0
        conn.trafficlight.setRedYellowGreenState(ts_id, self.green_phases[0])

    # ---- control -----------------------------------------------------------

    def request_phase(self, idx: int) -> bool:
        """Ask to switch to green phase `idx`. Ignored while in yellow, when
        already in that phase, or before min_green has elapsed."""
        if self.pending is not None or idx == self.current:
            return False
        if self.green_elapsed < self.min_green:
            return False
        yellow = make_yellow_state(self.green_phases[self.current], self.green_phases[idx])
        self.conn.trafficlight.setRedYellowGreenState(self.id, yellow)
        self.pending = idx
        self.yellow_remaining = float(self.yellow_time)
        return True

    def tick(self, dt: float = 1.0) -> None:
        """Advance internal clocks by dt; call once per simulationStep."""
        if self.pending is not None:
            self.yellow_remaining -= dt
            if self.yellow_remaining <= 0:
                self.current = self.pending
                self.pending = None
                self.green_elapsed = 0.0
                self.conn.trafficlight.setRedYellowGreenState(
                    self.id, self.green_phases[self.current]
                )
        else:
            self.green_elapsed += dt

    @property
    def active_target(self) -> int:
        """The phase the signal is in, or transitioning into."""
        return self.pending if self.pending is not None else self.current

    # ---- state extraction ---------------------------------------------------

    def lane_states(self) -> dict[str, LaneState]:
        out = {}
        for lane in self.in_lanes:
            veh_ids = self.conn.lane.getLastStepVehicleIDs(lane)
            waiting = sum(
                self.conn.vehicle.getAccumulatedWaitingTime(v) for v in veh_ids
            )
            out[lane] = LaneState(
                queue=self.conn.lane.getLastStepHaltingNumber(lane),
                vehicles=len(veh_ids),
                waiting=waiting,
                length=self.lane_lengths[lane],
            )
        return out

    def total_queued(self) -> int:
        return sum(
            self.conn.lane.getLastStepHaltingNumber(l) for l in self.in_lanes
        )

    def total_waiting(self) -> float:
        return sum(s.waiting for s in self.lane_states().values())

    def phase_pressure(self, idx: int) -> float:
        """Sum over movements served by phase idx of (incoming queue - outgoing queue)."""
        state = self.green_phases[idx]
        pressure = 0.0
        seen = set()
        for sig_i, ch in enumerate(state):
            link = self.links[sig_i] if sig_i < len(self.links) else None
            if ch in "Gg" and link is not None and link not in seen:
                seen.add(link)
                in_lane, out_lane = link
                pressure += self.conn.lane.getLastStepHaltingNumber(
                    in_lane
                ) - self.conn.lane.getLastStepHaltingNumber(out_lane)
        return pressure
