"""Episode metrics, mostly parsed from SUMO's tripinfo output.

Only vehicles that completed their trip get a tripinfo entry; vehicles still
queued at episode end are reported separately as `unfinished` so congestion
collapse can't masquerade as low average waiting time.
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

    def as_dict(self) -> dict:
        return asdict(self)


def parse_tripinfo(path: str) -> dict:
    root = ET.parse(path).getroot()
    trips = root.findall("tripinfo")
    n = len(trips)
    if n == 0:
        return {
            "arrived": 0,
            "mean_wait_s": 0.0,
            "mean_travel_s": 0.0,
            "mean_timeloss_s": 0.0,
            "total_co2_kg": 0.0,
        }
    co2_mg = sum(
        float(t.find("emissions").get("CO2_abs", 0.0))
        for t in trips
        if t.find("emissions") is not None
    )
    return {
        "arrived": n,
        "mean_wait_s": sum(float(t.get("waitingTime")) for t in trips) / n,
        "mean_travel_s": sum(float(t.get("duration")) for t in trips) / n,
        "mean_timeloss_s": sum(float(t.get("timeLoss")) for t in trips) / n,
        "total_co2_kg": co2_mg / 1e6,
    }
