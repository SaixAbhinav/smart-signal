"""Integration tests: spin up real (headless) SUMO simulations. Slower (~seconds each)."""

import numpy as np
import pytest

from smartsignal.config import resolve
from smartsignal.demand.generate_routes import route_file_for
from smartsignal.env import SingleIntersectionEnv

NET = resolve("scenarios/single/single.net.xml")


@pytest.fixture
def env():
    e = SingleIntersectionEnv(
        net_file=NET,
        route_files=route_file_for("offpeak"),
        episode_seconds=120,
        sumo_seed=42,
    )
    yield e
    e.close()


def test_spaces(env):
    assert env.action_space.n == 4  # NS, NS-left, EW, EW-left
    obs, _ = env.reset(seed=0)
    assert obs.shape == env.observation_space.shape
    assert env.observation_space.contains(obs)


def test_episode_truncates(env):
    env.reset(seed=0)
    steps = 0
    truncated = False
    while not truncated:
        obs, r, terminated, truncated, info = env.step(env.action_space.sample())
        assert not terminated
        assert env.observation_space.contains(obs)
        steps += 1
        assert steps <= 200, "episode never truncated"
    assert steps == 120 // 5


def test_min_green_blocks_early_switch(env):
    env.reset(seed=0)
    ts = env.ts
    assert ts.active_target == 0
    # ask to switch immediately: min_green=10 > green_elapsed -> must be ignored
    env.step(2)
    assert ts.active_target == 0
    # after enough time in phase, the same request must go through
    env.step(0), env.step(0)  # 15s elapsed total
    env.step(2)
    assert ts.active_target == 2


def test_max_green_forces_rotation(env):
    env.reset(seed=0)
    ts = env.ts
    for _ in range(13):  # 65s > max_green=60 while always requesting phase 0
        env.step(0)
    assert ts.active_target != 0


def test_determinism_same_seed():
    def rollout():
        e = SingleIntersectionEnv(
            net_file=NET,
            route_files=route_file_for("offpeak"),
            episode_seconds=100,
            sumo_seed=7,
        )
        obs, _ = e.reset(seed=3)
        trace = [obs]
        for i in range(15):
            obs, r, *_ = e.step(i % 4)
            trace.append(obs)
        e.close()
        return np.stack(trace)

    a, b = rollout(), rollout()
    np.testing.assert_array_equal(a, b)


def test_sb3_env_checker():
    from stable_baselines3.common.env_checker import check_env

    e = SingleIntersectionEnv(
        net_file=NET,
        route_files=route_file_for("offpeak"),
        episode_seconds=60,
        sumo_seed=1,
    )
    try:
        check_env(e, skip_render_check=True)
    finally:
        e.close()
