"""Run one evaluation episode for any controller on any scenario.

Works for a single intersection or a whole grid: every traffic light in the
network gets its own controller instance from `controller_factory` (so an RL
factory can share one loaded policy across junctions — parameter sharing at
deployment, matching how the policy was trained).
"""

import os
import tempfile
from typing import Callable

from smartsignal.controllers.base import Controller
from smartsignal.env.sumo_utils import build_sumo_cmd, close_sumo, start_sumo
from smartsignal.env.traffic_signal import TrafficSignal
from smartsignal.evaluation.metrics import EpisodeMetrics, parse_tripinfo


def apply_decision(ts: TrafficSignal, desired: int, max_green: int) -> None:
    """Apply a controller's desired phase with the same safety rules as the env."""
    if desired != ts.active_target:
        ts.request_phase(desired)
    elif ts.pending is None and ts.green_elapsed >= max_green:
        ts.request_phase((ts.current + 1) % ts.num_green_phases)


def run_episode(
    controller_factory: Callable[[], Controller],
    net_file: str,
    route_file: str,
    seed: int,
    profile: str = "",
    duration: int = 3600,
    delta_time: int = 5,
    yellow_time: int = 3,
    min_green: int = 10,
    max_green: int = 60,
    use_libsumo: bool = True,
    gui: bool = False,
    corridor_routes: tuple[str, ...] | None = None,
) -> EpisodeMetrics:
    from smartsignal.env.multi_signal import SignalNetwork  # avoid import cycle

    fd, tripinfo_path = tempfile.mkstemp(suffix=".xml", prefix="tripinfo_")
    os.close(fd)
    cmd = build_sumo_cmd(
        net_file, route_file, gui=gui, seed=seed,
        tripinfo_file=tripinfo_path, emissions=True,
    )
    conn = start_sumo(cmd, use_libsumo=use_libsumo)
    try:
        probe = controller_factory()
        if probe.uses_builtin_program:
            network = None
            controllers: dict[str, Controller] = {}
            in_lanes = []
            for ts_id in conn.trafficlight.getIDList():
                lanes = conn.trafficlight.getControlledLanes(ts_id)
                in_lanes.extend(dict.fromkeys(lanes))
        else:
            network = SignalNetwork(conn, yellow_time, min_green, max_green)
            controllers = {}
            for i, ts_id in enumerate(network.ids):
                c = probe if i == 0 else controller_factory()
                c.reset(
                    network.signals[ts_id],
                    obs_fn=(lambda t=ts_id: network.observe(t)),
                )
                controllers[ts_id] = c
            in_lanes = [l for t in network.ids for l in network.signals[t].in_lanes]

        queue_samples = []
        t = 0
        while t < duration:
            if network is not None:
                for ts_id, c in controllers.items():
                    ts = network.signals[ts_id]
                    apply_decision(ts, c.decide(ts, t), max_green)
            for _ in range(delta_time):
                conn.simulationStep()
                if network is not None:
                    network.tick(1.0)
            t += delta_time
            queue_samples.append(
                sum(conn.lane.getLastStepHaltingNumber(l) for l in in_lanes)
            )
        unfinished = conn.vehicle.getIDCount()
    finally:
        close_sumo(conn)  # flushes tripinfo output

    trip = parse_tripinfo(tripinfo_path, corridor_routes=corridor_routes)
    os.unlink(tripinfo_path)
    return EpisodeMetrics(
        controller=probe.name,
        profile=profile,
        seed=seed,
        arrived=trip["arrived"],
        unfinished=unfinished,
        mean_wait_s=trip["mean_wait_s"],
        mean_travel_s=trip["mean_travel_s"],
        mean_timeloss_s=trip["mean_timeloss_s"],
        total_co2_kg=trip["total_co2_kg"],
        mean_queue=sum(queue_samples) / max(len(queue_samples), 1),
        corridor_arrived=trip["corridor_arrived"],
        corridor_travel_s=trip["corridor_travel_s"],
        corridor_wait_s=trip["corridor_wait_s"],
        corridor_stops=trip["corridor_stops"],
    )
