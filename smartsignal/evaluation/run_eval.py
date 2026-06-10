"""Benchmark controllers across demand profiles and seeds.

Usage:
  python -m smartsignal.evaluation.run_eval --controllers fixed actuated maxpressure
  python -m smartsignal.evaluation.run_eval --controllers rl --model models/ppo_single.zip
  python -m smartsignal.evaluation.run_eval --scenario grid2x2 --controllers rl --model models/ppo_grid.zip
"""

import argparse
import csv
import statistics
from pathlib import Path

from smartsignal.config import load_config, resolve
from smartsignal.controllers import CONTROLLERS, RLController
from smartsignal.demand import generate_grid_routes, generate_routes
from smartsignal.demand.generate_grid_routes import CORRIDOR_ROUTES
from smartsignal.evaluation.runner import run_episode

SCENARIOS = {
    "single": {
        "net_key": "env",
        "profiles": ["offpeak", "rush_ns", "variable"],
        "route_file_for": generate_routes.route_file_for,
        "corridor_routes": None,
        "default_model": "models/ppo_single.zip",
    },
    "grid2x2": {
        "net_key": "grid",
        "profiles": ["grid_corridor", "grid_balanced"],
        "route_file_for": generate_grid_routes.route_file_for,
        "corridor_routes": CORRIDOR_ROUTES,
        "default_model": "models/ppo_grid.zip",
    },
}


def make_controller_factory(name: str, cfg: dict, model: str | None):
    kwargs = {
        "green_duration": cfg["fixed_time"]["green_duration"],
        "max_green": cfg["env"]["max_green"],
    }
    if name == "rl":
        from stable_baselines3 import PPO

        ppo = PPO.load(resolve(model), device="cpu")
        return lambda: RLController(model=ppo, max_green=kwargs["max_green"])
    return lambda: CONTROLLERS[name](**kwargs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="single", choices=list(SCENARIOS))
    ap.add_argument("--controllers", nargs="+", default=["fixed", "actuated", "maxpressure"],
                    choices=list(CONTROLLERS))
    ap.add_argument("--profiles", nargs="+", default=None)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--model", default=None, help="SB3 model path for the rl controller")
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = load_config()
    env_cfg = cfg["env"]
    scen = SCENARIOS[args.scenario]
    profiles = args.profiles or scen["profiles"]
    duration = args.duration or env_cfg["episode_seconds"]
    net_file = resolve(cfg[scen["net_key"]]["net_file"])
    model = args.model or scen["default_model"]
    out_path = args.out or f"results/{args.scenario}_eval.csv"

    rows = []
    for name in args.controllers:
        factory = make_controller_factory(name, cfg, model)
        for profile in profiles:
            route_file = scen["route_file_for"](profile)
            for seed in range(args.seeds):
                m = run_episode(
                    factory, net_file, route_file, seed=seed, profile=profile,
                    duration=duration,
                    delta_time=env_cfg["delta_time"],
                    yellow_time=env_cfg["yellow_time"],
                    min_green=env_cfg["min_green"],
                    max_green=env_cfg["max_green"],
                    use_libsumo=False,  # several episodes in one process needs TraCI
                    corridor_routes=scen["corridor_routes"],
                )
                rows.append(m.as_dict())
                line = (f"{name:12s} {profile:14s} seed={seed} "
                        f"wait={m.mean_wait_s:7.1f}s queue={m.mean_queue:6.1f} "
                        f"arrived={m.arrived} unfinished={m.unfinished}")
                if scen["corridor_routes"]:
                    line += (f" | corridor: travel={m.corridor_travel_s:6.1f}s "
                             f"stops={m.corridor_stops:.2f}")
                print(line)

    out = Path(resolve(out_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows to {out}\n")

    cols = ["mean_wait_s", "mean_timeloss_s", "mean_queue"]
    if scen["corridor_routes"]:
        cols += ["corridor_travel_s", "corridor_stops"]
    header = f"{'controller':12s} {'profile':14s}" + "".join(f" {c:>18s}" for c in cols)
    print(header)
    for name in args.controllers:
        for profile in profiles:
            sub = [r for r in rows if r["controller"] == name and r["profile"] == profile]
            if not sub:
                continue
            def ms(key):
                vals = [r[key] for r in sub]
                m = statistics.mean(vals)
                s = statistics.stdev(vals) if len(vals) > 1 else 0.0
                return f"{m:.1f}±{s:.1f}"
            print(f"{name:12s} {profile:14s}" + "".join(f" {ms(c):>18s}" for c in cols))


if __name__ == "__main__":
    main()
