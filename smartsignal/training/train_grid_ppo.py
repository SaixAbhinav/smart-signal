"""Train a shared PPO policy on the 2x2 grid.

One SUMO simulation, four junctions, four VecEnv slots, one policy: every
junction's transitions update the same network (parameter sharing), and each
junction's observation includes its neighbors' queue totals so coordination
("green waves") can be learned rather than hand-coded.

Usage:
  python -m smartsignal.training.train_grid_ppo                 # full run
  python -m smartsignal.training.train_grid_ppo --timesteps 30000  # smoke
"""

import argparse
from pathlib import Path

from smartsignal.config import load_config, resolve
from smartsignal.demand.generate_grid_routes import load_grid_profiles, route_file_for


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=None)
    ap.add_argument("--run-name", default="ppo_grid")
    args = ap.parse_args()

    cfg = load_config()
    env_cfg, ppo_cfg = cfg["env"], cfg["ppo_grid"]
    total_timesteps = args.timesteps or ppo_cfg["total_timesteps"]
    route_files = [route_file_for(p) for p in load_grid_profiles()]

    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import VecMonitor

    from smartsignal.env.vec_env import MultiSignalVecEnv

    vec_env = VecMonitor(
        MultiSignalVecEnv(
            net_file=resolve(cfg["grid"]["net_file"]),
            route_files=route_files,
            episode_seconds=env_cfg["episode_seconds"],
            delta_time=env_cfg["delta_time"],
            yellow_time=env_cfg["yellow_time"],
            min_green=env_cfg["min_green"],
            max_green=env_cfg["max_green"],
            use_libsumo=True,
            seed=0,
        )
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
        save_freq=50_000 // vec_env.num_envs,
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
