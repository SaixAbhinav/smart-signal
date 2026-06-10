"""Grid scenario tests: route generation, neighbor detection, VecEnv contract."""

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from smartsignal.config import resolve
from smartsignal.demand.generate_grid_routes import (
    CORRIDOR_ROUTES,
    ROUTES,
    load_grid_profiles,
    profile_to_xml,
    route_file_for,
)

NET = resolve("scenarios/grid2x2/grid2x2.net.xml")


def test_grid_generation_is_deterministic():
    profiles = load_grid_profiles()
    assert profile_to_xml(profiles["grid_corridor"]) == profile_to_xml(
        profiles["grid_corridor"]
    )


def test_grid_routes_are_connected():
    # consecutive edges must share the intermediate node: "A__B" -> "B__C"
    for name, edges in ROUTES.items():
        seq = edges.split()
        for e1, e2 in zip(seq, seq[1:]):
            assert e1.split("__")[1] == e2.split("__")[0], f"broken route {name}"


def test_corridor_flow_ids_are_identifiable():
    profiles = load_grid_profiles()
    root = ET.fromstring(profile_to_xml(profiles["grid_corridor"]))
    flow_ids = [f.get("id") for f in root.findall("flow")]
    corridor = [
        fid for fid in flow_ids
        if fid.startswith(tuple(r + "_" for r in CORRIDOR_ROUTES))
    ]
    assert len(corridor) == 4  # weBot, ewBot, weTop, ewTop x 1 interval


def test_signal_network_finds_grid_neighbors():
    from smartsignal.env.multi_signal import SignalNetwork
    from smartsignal.env.sumo_utils import build_sumo_cmd, close_sumo, start_sumo

    conn = start_sumo(
        build_sumo_cmd(NET, route_file_for("grid_balanced"), seed=0),
        use_libsumo=False,
    )
    try:
        net = SignalNetwork(conn)
        assert net.ids == ["J00", "J01", "J10", "J11"]
        assert net.has_neighbors
        assert net.neighbors["J00"] == {"N": "J01", "S": None, "E": "J10", "W": None}
        assert net.neighbors["J11"] == {"N": None, "S": "J10", "E": None, "W": "J01"}
        # base obs (12 lanes * 3 + 4 phases + 1) + 4 neighbor slots
        assert net.obs_size == 45
        obs = net.observe("J00")
        assert obs.shape == (45,)
        assert (obs >= 0).all() and (obs <= 1).all()
    finally:
        close_sumo(conn)


@pytest.mark.slow
def test_vec_env_contract():
    from smartsignal.env.vec_env import MultiSignalVecEnv

    env = MultiSignalVecEnv(
        net_file=NET,
        route_files=route_file_for("grid_balanced"),
        episode_seconds=60,
        use_libsumo=False,
        seed=1,
    )
    try:
        assert env.num_envs == 4
        obs = env.reset()
        assert obs.shape == (4, 45)
        for step in range(12):  # 60s / 5s -> episode boundary on the last step
            env.step_async(np.array([step % 4] * 4))
            obs, rewards, dones, infos = env.step_wait()
            assert obs.shape == (4, 45)
            assert rewards.shape == (4,)
        assert dones.all()
        assert "terminal_observation" in infos[0]
        assert infos[0]["TimeLimit.truncated"] is True
    finally:
        env.close()
