"""Watch a controller drive the intersection in SUMO's own GUI.

Usage:
  python scripts/demo_gui.py maxpressure --profile rush_ns
  python scripts/demo_gui.py rl --model models/ppo_single.zip
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from smartsignal.config import load_config, resolve
from smartsignal.controllers import CONTROLLERS
from smartsignal.demand.generate_routes import route_file_for
from smartsignal.evaluation.runner import run_episode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("controller", choices=list(CONTROLLERS))
    ap.add_argument("--profile", default="variable")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default="models/ppo_single.zip")
    args = ap.parse_args()

    cfg = load_config()
    env_cfg = cfg["env"]
    kwargs = {
        "green_duration": cfg["fixed_time"]["green_duration"],
        "max_green": env_cfg["max_green"],
    }
    if args.controller == "rl":
        kwargs["model_path"] = resolve(args.model)
    factory = lambda: CONTROLLERS[args.controller](**kwargs)

    metrics = run_episode(
        factory,
        resolve(env_cfg["net_file"]),
        route_file_for(args.profile),
        seed=args.seed,
        profile=args.profile,
        duration=env_cfg["episode_seconds"],
        delta_time=env_cfg["delta_time"],
        yellow_time=env_cfg["yellow_time"],
        min_green=env_cfg["min_green"],
        max_green=env_cfg["max_green"],
        use_libsumo=False,
        gui=True,
    )
    print(metrics)


if __name__ == "__main__":
    main()
