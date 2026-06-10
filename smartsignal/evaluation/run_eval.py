"""Benchmark controllers across demand profiles and seeds.

Usage:
  python -m smartsignal.evaluation.run_eval --controllers fixed actuated maxpressure
  python -m smartsignal.evaluation.run_eval --controllers rl --model models/ppo_single.zip
"""

import argparse
import csv
import statistics
from pathlib import Path

from smartsignal.config import load_config, resolve
from smartsignal.controllers import CONTROLLERS
from smartsignal.demand.generate_routes import route_file_for
from smartsignal.evaluation.runner import run_episode


def make_controller(name: str, cfg: dict, model: str | None):
    kwargs = {
        "green_duration": cfg["fixed_time"]["green_duration"],
        "max_green": cfg["env"]["max_green"],
    }
    if name == "rl":
        if not model:
            raise SystemExit("--model is required for the rl controller")
        kwargs["model_path"] = model
    return CONTROLLERS[name](**kwargs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--controllers", nargs="+", default=["fixed", "actuated", "maxpressure"],
                    choices=list(CONTROLLERS))
    ap.add_argument("--profiles", nargs="+", default=["offpeak", "rush_ns", "variable"])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--model", default=None, help="SB3 model path for the rl controller")
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--out", default="results/eval.csv")
    args = ap.parse_args()

    cfg = load_config()
    env_cfg = cfg["env"]
    duration = args.duration or env_cfg["episode_seconds"]
    net_file = resolve(env_cfg["net_file"])

    rows = []
    for name in args.controllers:
        for profile in args.profiles:
            route_file = route_file_for(profile)
            for seed in range(args.seeds):
                controller = make_controller(name, cfg, args.model)
                m = run_episode(
                    controller, net_file, route_file, seed=seed, profile=profile,
                    duration=duration,
                    delta_time=env_cfg["delta_time"],
                    yellow_time=env_cfg["yellow_time"],
                    min_green=env_cfg["min_green"],
                    max_green=env_cfg["max_green"],
                    use_libsumo=False,  # several episodes in one process needs TraCI
                )
                rows.append(m.as_dict())
                print(f"{name:12s} {profile:10s} seed={seed} "
                      f"wait={m.mean_wait_s:7.1f}s queue={m.mean_queue:6.1f} "
                      f"arrived={m.arrived} unfinished={m.unfinished}")

    out = Path(resolve(args.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows to {out}\n")

    print(f"{'controller':12s} {'profile':10s} {'wait_s':>10s} {'timeloss_s':>11s} "
          f"{'queue':>8s} {'arrived':>8s} {'CO2_kg':>8s}")
    for name in args.controllers:
        for profile in args.profiles:
            sub = [r for r in rows if r["controller"] == name and r["profile"] == profile]
            if not sub:
                continue
            def ms(key):
                vals = [r[key] for r in sub]
                m = statistics.mean(vals)
                s = statistics.stdev(vals) if len(vals) > 1 else 0.0
                return f"{m:.1f}±{s:.1f}"
            print(f"{name:12s} {profile:10s} {ms('mean_wait_s'):>10s} "
                  f"{ms('mean_timeloss_s'):>11s} {ms('mean_queue'):>8s} "
                  f"{ms('arrived'):>8s} {ms('total_co2_kg'):>8s}")


if __name__ == "__main__":
    main()
