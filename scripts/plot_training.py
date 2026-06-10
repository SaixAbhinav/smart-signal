"""Export the episode-reward training curve from TensorBoard logs to a PNG.

Usage: python scripts/plot_training.py [run_name] (default: latest ppo_single run)
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

sys.path.insert(0, str(Path(__file__).parent.parent))
from smartsignal.config import resolve

RUNS = Path(resolve("runs"))


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else "ppo_single"
    out = Path(resolve("docs")) / (
        "training_curve.png" if prefix == "ppo_single" else f"training_curve_{prefix}.png"
    )
    candidates = sorted(RUNS.glob(f"{prefix}*"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(f"no runs matching {prefix}* under {RUNS}")
    run_dir = candidates[-1]

    acc = EventAccumulator(str(run_dir))
    acc.Reload()
    events = acc.Scalars("rollout/ep_rew_mean")
    steps = [e.step for e in events]
    vals = [e.value for e in events]

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#0f1419")
    ax.set_facecolor("#1a2129")
    ax.plot(steps, vals, color="#4fc3f7", linewidth=2)
    ax.set_xlabel("environment steps", color="#8b98a5")
    ax.set_ylabel("mean episode reward", color="#8b98a5")
    ax.set_title(f"PPO training — {run_dir.name}", color="#e6e9ec")
    ax.tick_params(colors="#8b98a5")
    for spine in ax.spines.values():
        spine.set_color("#2a3441")
    ax.grid(color="#2a3441", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"wrote {out} ({len(events)} points, final reward {vals[-1]:.3f})")


if __name__ == "__main__":
    main()
