"""Generate SUMO route files for the 2x2 grid from configs/demand.yaml.

Flow ids are prefixed with the route name (e.g. "weBot_0.12"), which is how
the evaluation harness identifies east-west corridor vehicles for the
green-wave metrics.

Usage: python -m smartsignal.demand.generate_grid_routes [profile ...]
"""

import sys
from pathlib import Path

from smartsignal.config import PROJECT_ROOT, load_config

SCENARIO_DIR = PROJECT_ROOT / "scenarios" / "grid2x2"

# route name -> edge sequence through the grid
ROUTES = {
    # east-west corridor (the green-wave routes)
    "weBot": "W00__J00 J00__J10 J10__E10",
    "ewBot": "E10__J10 J10__J00 J00__W00",
    "weTop": "W01__J01 J01__J11 J11__E11",
    "ewTop": "E11__J11 J11__J01 J01__W01",
    # north-south cross traffic
    "snLeftCol": "S00__J00 J00__J01 J01__N01",
    "nsLeftCol": "N01__J01 J01__J00 J00__S00",
    "snRightCol": "S10__J10 J10__J11 J11__N11",
    "nsRightCol": "N11__J11 J11__J10 J10__S10",
    # turning routes so every junction sees left/right-turn demand
    "turnWN": "W00__J00 J00__J01 J01__N01",
    "turnES": "E11__J11 J11__J10 J10__S10",
    "turnSE": "S00__J00 J00__J10 J10__E10",
    "turnNW": "N11__J11 J11__J01 J01__W01",
}
CORRIDOR_ROUTES = ("weBot", "ewBot", "weTop", "ewTop")


def profile_to_xml(profile: dict) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<routes>",
        '    <vType id="car" accel="2.6" decel="4.5" length="5.0" '
        'minGap="2.5" maxSpeed="16.67" sigma="0.5"/>',
    ]
    for name, edges in ROUTES.items():
        lines.append(f'    <route id="{name}" edges="{edges}"/>')
    for i, interval in enumerate(profile["intervals"]):
        begin, end = interval["begin"], interval["end"]
        for route, vph in interval["rates"].items():
            if route not in ROUTES:
                raise KeyError(f"unknown grid route {route!r}")
            if vph <= 0:
                continue
            lines.append(
                f'    <flow id="{route}_{i}" route="{route}" '
                f'begin="{begin}" end="{end}" vehsPerHour="{vph}" '
                f'type="car" departLane="best" departSpeed="max"/>'
            )
    lines.append("</routes>")
    return "\n".join(lines) + "\n"


def load_grid_profiles() -> dict:
    return load_config("demand")["grid_profiles"]


def generate(profile_name: str, profiles: dict | None = None) -> Path:
    profiles = profiles or load_grid_profiles()
    out = SCENARIO_DIR / f"routes_{profile_name}.rou.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(profile_to_xml(profiles[profile_name]), encoding="utf-8")
    return out


def route_file_for(profile_name: str) -> str:
    out = SCENARIO_DIR / f"routes_{profile_name}.rou.xml"
    if not out.exists():
        generate(profile_name)
    return str(out)


if __name__ == "__main__":
    names = sys.argv[1:] or list(load_grid_profiles())
    for name in names:
        print("wrote", generate(name))
