"""Train PPO on the single intersection.

Each parallel worker runs its own headless SUMO via libsumo (one simulation per
process, which is exactly libsumo's constraint). Episodes sample a random
demand profile so the policy generalizes across traffic patterns.

Usage:
  python -m smartsignal.training.train_ppo                  # full run from config
  python -m smartsignal.training.train_ppo --timesteps 50000 --n-envs 4  # smoke
"""

import argparse
from pathlib import Path

from smartsignal.config import load_config, load_demand_profiles, resolve
from smartsignal.demand.generate_routes import route_file_for


def make_env_fn(env_cfg: dict, route_files: list[str], rank: int):
    def _init():
        from stable_baselines3.common.monitor import Monitor

        from smartsignal.env import SingleIntersectionEnv

        env = SingleIntersectionEnv(
            net_file=resolve(env_cfg["net_file"]),
            route_files=route_files,
            episode_seconds=env_cfg["episode_seconds"],
            delta_time=env_cfg["delta_time"],
            yellow_time=env_cfg["yellow_time"],
            min_green=env_cfg["min_green"],
            max_green=env_cfg["max_green"],
            reward=env_cfg["reward"],
            use_libsumo=True,
        )
        env.reset(seed=1000 + rank)
        return Monitor(env)

    return _init


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=None)
    ap.add_argument("--n-envs", type=int, default=None)
    ap.add_argument("--run-name", default="ppo_single")
    args = ap.parse_args()

    cfg = load_config()
    env_cfg, ppo_cfg = cfg["env"], cfg["ppo"]
    total_timesteps = args.timesteps or ppo_cfg["total_timesteps"]
    n_envs = args.n_envs or ppo_cfg["n_envs"]

    profiles = list(load_demand_profiles())
    route_files = [route_file_for(p) for p in profiles]

    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv

    vec_env = SubprocVecEnv(
        [make_env_fn(env_cfg, route_files, i) for i in range(n_envs)]
    )

    models_dir = Path(resolve(cfg["paths"]["models_dir"]))
    runs_dir = Path(resolve(cfg["paths"]["runs_dir"]))
    models_dir.mkdir(parents=True, exist_ok=True)

    model = PPO(
        "MlpPolicy",
        vec_env,
        n_steps=ppo_cfg["n_steps"],
        batch_size=ppo_cfg["batch_size"],
        learning_rate=ppo_cfg["learning_rate"],
        gamma=ppo_cfg["gamma"],
        gae_lambda=ppo_cfg["gae_lambda"],
        ent_coef=ppo_cfg["ent_coef"],
        clip_range=ppo_cfg["clip_range"],
        policy_kwargs={"net_arch": list(ppo_cfg["net_arch"])},
        tensorboard_log=str(runs_dir),
        verbose=1,
        device="cpu",
    )
    checkpoint = CheckpointCallback(
        save_freq=max(50_000 // n_envs, 1),
        save_path=str(models_dir / "checkpoints"),
        name_prefix=args.run_name,
    )
    try:
        model.learn(
            total_timesteps=total_timesteps,
            callback=checkpoint,
            tb_log_name=args.run_name,
            progress_bar=False,
        )
    finally:
        out = models_dir / f"{args.run_name}.zip"
        model.save(out)
        vec_env.close()
        print(f"saved model to {out}")


if __name__ == "__main__":
    main()
