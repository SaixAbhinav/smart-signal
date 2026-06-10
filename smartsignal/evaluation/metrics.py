"""Episode metrics, mostly parsed from SUMO's tripinfo output.

Only vehicles that completed their trip get a tripinfo entry; vehicles still
queued at episode end are reported separately as `unfinished` so congestion
collapse can't masquerade as low average waiting time.

For grid scenarios, vehicles whose flow id starts with a corridor route name
(e.g. "weBot_0.12") are additionally aggregated into the green-wave metrics:
corridor travel time, waiting, and stops per vehicle (tripinfo waitingCount).
"""

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass


@dataclass
class EpisodeMetrics:
    controller: str
    profile: str
    seed: int
    arrived: int
    unfinished: int
    mean_wait_s: float
    mean_travel_s: float
    mean_timeloss_s: float
    total_co2_kg: float
    mean_queue: float
    corridor_arrived: int = 0
    corridor_travel_s: float = 0.0
    corridor_wait_s: float = 0.0
    corridor_stops: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def _mean(trips, attr) -> float:
    return sum(float(t.get(attr)) for t in trips) / len(trips) if trips else 0.0


def parse_tripinfo(path: str, corridor_routes: tuple[str, ...] | None = None) -> dict:
    root = ET.parse(path).getroot()
    trips = root.findall("tripinfo")
    co2_mg = sum(
        float(t.find("emissions").get("CO2_abs", 0.0))
        for t in trips
        if t.find("emissions") is not None
    )
    corridor = [
        t
        for t in trips
        if corridor_routes
        and t.get("id").startswith(tuple(r + "_" for r in corridor_routes))
    ]
    return {
        "arrived": len(trips),
        "mean_wait_s": _mean(trips, "waitingTime"),
        "mean_travel_s": _mean(trips, "duration"),
        "mean_timeloss_s": _mean(trips, "timeLoss"),
        "total_co2_kg": co2_mg / 1e6,
        "corridor_arrived": len(corridor),
        "corridor_travel_s": _mean(corridor, "duration"),
        "corridor_wait_s": _mean(corridor, "waitingTime"),
        "corridor_stops": _mean(corridor, "waitingCount"),
    }
