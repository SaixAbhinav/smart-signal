"""Render benchmark CSVs as a markdown table for the README.

Usage: python -m smartsignal.evaluation.report results/baselines.csv results/rl.csv
"""

import csv
import statistics
import sys
from collections import defaultdict

LABELS = {
    "fixed": "Fixed timer (30 s)",
    "actuated": "Actuated (SUMO)",
    "maxpressure": "Max-pressure",
    "rl": "**PPO (SmartSignal)**",
}
ORDER = ["fixed", "actuated", "maxpressure", "rl"]


def main() -> None:
    paths = sys.argv[1:] or ["results/baselines.csv"]
    rows = []
    for path in paths:
        with open(path, newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))

    profiles = sorted({r["profile"] for r in rows})
    cells = defaultdict(list)
    for r in rows:
        cells[(r["controller"], r["profile"])].append(float(r["mean_wait_s"]))

    print("| Controller | " + " | ".join(profiles) + " |")
    print("|---" * (len(profiles) + 1) + "|")
    for c in ORDER:
        if not any((c, p) in cells for p in profiles):
            continue
        vals = []
        for p in profiles:
            xs = cells.get((c, p))
            if xs:
                m = statistics.mean(xs)
                s = statistics.stdev(xs) if len(xs) > 1 else 0.0
                vals.append(f"{m:.1f} ± {s:.1f}")
            else:
                vals.append("—")
        print(f"| {LABELS.get(c, c)} | " + " | ".join(vals) + " |")


if __name__ == "__main__":
    main()
