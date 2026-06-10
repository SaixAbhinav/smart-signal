"""Generate SUMO route files from the demand profiles in configs/demand.yaml.

Output is deterministic for a given profile: stochasticity in vehicle insertion
comes from SUMO's own --seed at simulation time, not from this generator.

Usage: python -m smartsignal.demand.generate_routes [profile ...]
"""

import sys
from pathlib import Path

from smartsignal.config import PROJECT_ROOT, load_demand_profiles

SCENARIO_DIR = PROJECT_ROOT / "scenarios" / "single"

# Compass movement map for a 4-way intersection. A vehicle entering from the
# north drives south: its left turn exits east, its right turn exits west.
MOVEMENTS = {
    "N": {"straight": "S", "left": "E", "right": "W"},
    "S": {"straight": "N", "left": "W", "right": "E"},
    "E": {"straight": "W", "left": "S", "right": "N"},
    "W": {"straight": "E", "left": "N", "right": "S"},
}


def profile_to_xml(profile: dict) -> str:
    turns = profile["turns"]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<routes>",
        '    <vType id="car" accel="2.6" decel="4.5" length="5.0" '
        'minGap="2.5" maxSpeed="16.67" sigma="0.5"/>',
    ]
    for approach, exits in MOVEMENTS.items():
        for movement, exit_dir in exits.items():
            lines.append(
                f'    <route id="{approach}_{movement}" '
                f'edges="{approach}_in {exit_dir}_out"/>'
            )
    flow_i = 0
    for interval in profile["intervals"]:
        begin, end = interval["begin"], interval["end"]
        for approach, rate in interval["rates"].items():
            for movement, frac in turns.items():
                vph = rate * frac
                if vph <= 0:
                    continue
                lines.append(
                    f'    <flow id="f{flow_i}" route="{approach}_{movement}" '
                    f'begin="{begin}" end="{end}" vehsPerHour="{vph:.2f}" '
                    f'type="car" departLane="best" departSpeed="max"/>'
                )
                flow_i += 1
    lines.append("</routes>")
    return "\n".join(lines) + "\n"


def generate(profile_name: str, profiles: dict | None = None) -> Path:
    profiles = profiles or load_demand_profiles()
    out = SCENARIO_DIR / f"routes_{profile_name}.rou.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(profile_to_xml(profiles[profile_name]), encoding="utf-8")
    return out


def route_file_for(profile_name: str) -> str:
    """Path to a profile's route file, generating it if missing."""
    out = SCENARIO_DIR / f"routes_{profile_name}.rou.xml"
    if not out.exists():
        generate(profile_name)
    return str(out)


if __name__ == "__main__":
    names = sys.argv[1:] or list(load_demand_profiles())
    for name in names:
        print("wrote", generate(name))
