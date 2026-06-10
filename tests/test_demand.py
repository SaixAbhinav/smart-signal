import xml.etree.ElementTree as ET

from smartsignal.config import load_demand_profiles
from smartsignal.demand.generate_routes import MOVEMENTS, profile_to_xml


def test_generation_is_deterministic():
    profiles = load_demand_profiles()
    assert profile_to_xml(profiles["offpeak"]) == profile_to_xml(profiles["offpeak"])


def test_flow_rates_match_profile():
    profiles = load_demand_profiles()
    profile = profiles["rush_ns"]
    root = ET.fromstring(profile_to_xml(profile))
    flows = root.findall("flow")
    interval = profile["intervals"][0]
    expected = sum(
        1 for rate in interval["rates"].values() for f in profile["turns"].values() if rate * f > 0
    )
    assert len(flows) == expected

    # total injected vehicles/hour equals the sum of approach rates
    total_vph = sum(float(f.get("vehsPerHour")) for f in flows)
    assert abs(total_vph - sum(interval["rates"].values())) < 0.1


def test_routes_cover_all_movements():
    profiles = load_demand_profiles()
    root = ET.fromstring(profile_to_xml(profiles["offpeak"]))
    route_ids = {r.get("id") for r in root.findall("route")}
    expected = {
        f"{a}_{m}" for a, moves in MOVEMENTS.items() for m in moves
    }
    assert route_ids == expected


def test_no_route_enters_and_exits_same_side():
    profiles = load_demand_profiles()
    root = ET.fromstring(profile_to_xml(profiles["offpeak"]))
    for r in root.findall("route"):
        edges = r.get("edges").split()
        assert edges[0][0] != edges[1][0], f"u-turn route {r.get('id')}"
