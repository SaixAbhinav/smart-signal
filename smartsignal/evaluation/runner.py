"""Run one evaluation episode for any controller behind the common interface."""

import os
import tempfile

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
    controller: Controller,
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
) -> EpisodeMetrics:
    fd, tripinfo_path = tempfile.mkstemp(suffix=".xml", prefix="tripinfo_")
    os.close(fd)
    cmd = build_sumo_cmd(
        net_file, route_file, gui=gui, seed=seed,
        tripinfo_file=tripinfo_path, emissions=True,
    )
    conn = start_sumo(cmd, use_libsumo=use_libsumo)
    try:
        ts_id = conn.trafficlight.getIDList()[0]
        if controller.uses_builtin_program:
            ts = None
            in_lanes = list(dict.fromkeys(conn.trafficlight.getControlledLanes(ts_id)))
        else:
            ts = TrafficSignal(conn, ts_id, yellow_time, min_green)
            in_lanes = ts.in_lanes
        controller.reset(ts)

        queue_samples = []
        t = 0
        while t < duration:
            if ts is not None:
                apply_decision(ts, controller.decide(ts, t), max_green)
            for _ in range(delta_time):
                conn.simulationStep()
                if ts is not None:
                    ts.tick(1.0)
            t += delta_time
            queue_samples.append(
                sum(conn.lane.getLastStepHaltingNumber(l) for l in in_lanes)
            )
        unfinished = conn.vehicle.getIDCount()
    finally:
        close_sumo(conn)  # flushes tripinfo output

    trip = parse_tripinfo(tripinfo_path)
    os.unlink(tripinfo_path)
    return EpisodeMetrics(
        controller=controller.name,
        profile=profile,
        seed=seed,
        arrived=trip["arrived"],
        unfinished=unfinished,
        mean_wait_s=trip["mean_wait_s"],
        mean_travel_s=trip["mean_travel_s"],
        mean_timeloss_s=trip["mean_timeloss_s"],
        total_co2_kg=trip["total_co2_kg"],
        mean_queue=sum(queue_samples) / max(len(queue_samples), 1),
    )
