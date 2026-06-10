"""Generate the 2x2 grid scenario (nodes/edges/connections) and run netconvert.

Every junction gets the same approach layout as the single intersection
(lane 0 right+straight, lane 1 straight, lane 2 exclusive left), so netconvert
emits the same 4-green-phase protected-left program at all four junctions and
a policy trained on one junction structure transfers to all of them.

Usage: python scripts/build_grid.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from smartsignal.config import PROJECT_ROOT
from smartsignal.env.sumo_utils import ensure_sumo_home

OUT_DIR = PROJECT_ROOT / "scenarios" / "grid2x2"

# world coordinates; junction spacing 300 m, fringe approaches 200 m
NODES = {
    "J00": (0, 0), "J10": (300, 0), "J01": (0, 300), "J11": (300, 300),
    "W00": (-200, 0), "S00": (0, -200),
    "E10": (500, 0), "S10": (300, -200),
    "W01": (-200, 300), "N01": (0, 500),
    "E11": (500, 300), "N11": (300, 500),
}
JUNCTIONS = ["J00", "J10", "J01", "J11"]

# what lies in each compass direction from each junction
NEIGHBORS = {
    "J00": {"N": "J01", "S": "S00", "E": "J10", "W": "W00"},
    "J10": {"N": "J11", "S": "S10", "E": "E10", "W": "J00"},
    "J01": {"N": "N01", "S": "J00", "E": "J11", "W": "W01"},
    "J11": {"N": "N11", "S": "J10", "E": "E11", "W": "J01"},
}
# for a vehicle entering FROM direction d (e.g. from W, heading east):
# which compass side is straight / right / left
HEADING = {
    "W": {"straight": "E", "right": "S", "left": "N"},
    "E": {"straight": "W", "right": "N", "left": "S"},
    "S": {"straight": "N", "right": "E", "left": "W"},
    "N": {"straight": "S", "right": "W", "left": "E"},
}


def edge_id(a: str, b: str) -> str:
    return f"{a}__{b}"


def build_xml() -> tuple[str, str, str]:
    nodes = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for nid, (x, y) in NODES.items():
        if nid in JUNCTIONS:
            nodes.append(
                f'    <node id="{nid}" x="{x}" y="{y}" '
                'type="traffic_light" tlType="actuated"/>'
            )
        else:
            nodes.append(f'    <node id="{nid}" x="{x}" y="{y}" type="priority"/>')
    nodes.append("</nodes>")

    pairs = set()
    for j, nbrs in NEIGHBORS.items():
        for other in nbrs.values():
            pairs.add(tuple(sorted((j, other))))
    edges = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for a, b in sorted(pairs):
        for u, v in ((a, b), (b, a)):
            edges.append(
                f'    <edge id="{edge_id(u, v)}" from="{u}" to="{v}" '
                'numLanes="3" speed="13.89"/>'
            )
    edges.append("</edges>")

    cons = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for j in JUNCTIONS:
        nbrs = NEIGHBORS[j]
        for frm_dir, moves in HEADING.items():
            inc = edge_id(nbrs[frm_dir], j)
            right = edge_id(j, nbrs[moves["right"]])
            straight = edge_id(j, nbrs[moves["straight"]])
            left = edge_id(j, nbrs[moves["left"]])
            cons += [
                f'    <connection from="{inc}" fromLane="0" to="{right}" toLane="0"/>',
                f'    <connection from="{inc}" fromLane="0" to="{straight}" toLane="0"/>',
                f'    <connection from="{inc}" fromLane="1" to="{straight}" toLane="1"/>',
                f'    <connection from="{inc}" fromLane="2" to="{left}" toLane="2"/>',
            ]
    cons.append("</connections>")
    return "\n".join(nodes) + "\n", "\n".join(edges) + "\n", "\n".join(cons) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nod, edg, con = build_xml()
    (OUT_DIR / "grid2x2.nod.xml").write_text(nod, encoding="utf-8")
    (OUT_DIR / "grid2x2.edg.xml").write_text(edg, encoding="utf-8")
    (OUT_DIR / "grid2x2.con.xml").write_text(con, encoding="utf-8")

    netconvert = Path(ensure_sumo_home()) / "bin" / "netconvert.exe"
    subprocess.run(
        [
            str(netconvert),
            "--node-files", str(OUT_DIR / "grid2x2.nod.xml"),
            "--edge-files", str(OUT_DIR / "grid2x2.edg.xml"),
            "--connection-files", str(OUT_DIR / "grid2x2.con.xml"),
            "--no-turnarounds", "true",
            "-o", str(OUT_DIR / "grid2x2.net.xml"),
        ],
        check=True,
    )
    print(f"wrote {OUT_DIR / 'grid2x2.net.xml'}")


if __name__ == "__main__":
    main()
