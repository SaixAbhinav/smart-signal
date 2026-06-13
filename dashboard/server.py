"""SmartSignal live comparison dashboard.

Runs several SUMO simulations in lockstep — identical network, demand, and
seed, but different signal controllers — and streams their state to the
browser over a WebSocket. Supports both the single intersection and the
2x2 grid scenario (every junction controlled by the same shared policy).

Run with:  uvicorn dashboard.server:app  (from the project root)
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from smartsignal.config import load_config, load_demand_profiles, resolve
from smartsignal.demand import generate_grid_routes, generate_routes
from smartsignal.env.multi_signal import SignalNetwork
from smartsignal.env.sumo_utils import build_sumo_cmd, close_sumo, start_sumo
from smartsignal.evaluation.run_eval import make_controller_factory
from smartsignal.evaluation.runner import apply_decision

STATIC_DIR = Path(__file__).parent / "static"
CFG = load_config()
ENV_CFG = CFG["env"]

SCENARIOS = {
    "single": {
        "net_file": ENV_CFG["net_file"],
        "profiles": lambda: list(load_demand_profiles()),
        "route_file_for": generate_routes.route_file_for,
        "model": "models/ppo_single.zip",
    },
    "grid2x2": {
        "net_file": CFG["grid"]["net_file"],
        "profiles": lambda: list(generate_grid_routes.load_grid_profiles()),
        "route_file_for": generate_grid_routes.route_file_for,
        "model": "models/ppo_grid.zip",
    },
}

app = FastAPI(title="SmartSignal")


class SimInstance:
    """One controller's simulation (any number of junctions) plus live metrics."""

    def __init__(self, name: str, scenario: str, profile: str, seed: int):
        self.name = name
        scen = SCENARIOS[scenario]
        factory = make_controller_factory(name, CFG, scen["model"])

        cmd = build_sumo_cmd(
            resolve(scen["net_file"]), scen["route_file_for"](profile), seed=seed
        )
        self.conn = start_sumo(cmd, use_libsumo=False)

        probe = factory()
        if probe.uses_builtin_program:
            self.network = None
            self.controllers = {}
            tls_ids = list(self.conn.trafficlight.getIDList())
            self.tls_lanes = {
                t: list(dict.fromkeys(self.conn.trafficlight.getControlledLanes(t)))
                for t in tls_ids
            }
        else:
            self.network = SignalNetwork(
                self.conn, ENV_CFG["yellow_time"], ENV_CFG["min_green"],
                ENV_CFG["max_green"],
            )
            self.controllers = {}
            for i, t in enumerate(self.network.ids):
                c = probe if i == 0 else factory()
                c.reset(
                    self.network.signals[t],
                    obs_fn=(lambda tid=t: self.network.observe(tid)),
                )
                self.controllers[t] = c
            self.tls_lanes = {
                t: self.network.signals[t].in_lanes for t in self.network.ids
            }

        # lane -> indices into its TLS state string, for rendering signal colors
        self.lane_sig: dict[str, tuple[str, list[int]]] = {}
        for t, lanes in self.tls_lanes.items():
            idxs: dict[str, list[int]] = {l: [] for l in lanes}
            for i, link in enumerate(self.conn.trafficlight.getControlledLinks(t)):
                if link:
                    idxs[link[0][0]].append(i)
            for l, sig in idxs.items():
                self.lane_sig[l] = (t, sig)

        self.in_lanes = [l for lanes in self.tls_lanes.values() for l in lanes]
        self.time = 0
        self.arrived = 0
        self.cum_wait = 0.0  # vehicle-seconds spent halted

        # Real road geometry, captured once. Lane polylines (incl. internal
        # ":"-prefixed junction lanes so turn arcs render) are world-coordinate
        # paths the client draws as roads and the cars ride along.
        (x0, y0), (x1, y1) = self.conn.simulation.getNetBoundary()
        self.bounds = [[x0, y0], [x1, y1]]
        self.lane_shapes = {
            lid: [[round(x, 1), round(y, 1)] for x, y in self.conn.lane.getShape(lid)]
            for lid in self.conn.lane.getIDList()
        }

    def geometry(self) -> dict:
        """Static scene geometry sent once at init: world bounds, every lane's
        polyline, and which lanes carry a signal head (the incoming lanes)."""
        return {
            "bounds": self.bounds,
            "laneShapes": self.lane_shapes,
            "signalLanes": self.in_lanes,
        }

    def step_second(self) -> None:
        if self.network is not None and self.time % ENV_CFG["delta_time"] == 0:
            for t, c in self.controllers.items():
                ts = self.network.signals[t]
                apply_decision(ts, c.decide(ts, self.time), ENV_CFG["max_green"])
        self.conn.simulationStep()
        if self.network is not None:
            self.network.tick(1.0)
        self.time += 1
        self.arrived += self.conn.simulation.getArrivedNumber()

    def frame(self) -> dict:
        states = {
            t: self.conn.trafficlight.getRedYellowGreenState(t)
            for t in self.tls_lanes
        }
        rank = {"G": 3, "g": 2, "y": 1}
        colors = {}
        queued_now = 0
        for lane, (t, sig_idxs) in self.lane_sig.items():
            state = states[t]
            best = max((state[i] for i in sig_idxs), key=lambda c: rank.get(c, 0), default="r")
            colors[lane] = "green" if best in "Gg" else "yellow" if best == "y" else "red"
            queued_now += self.conn.lane.getLastStepHaltingNumber(lane)
        self.cum_wait += queued_now

        veh = self.conn.vehicle
        vehicles = []
        for vid in veh.getIDList():
            x, y = veh.getPosition(vid)
            vehicles.append([
                vid, round(x, 1), round(y, 1), round(veh.getAngle(vid)),
                1 if veh.getSpeed(vid) < 0.1 else 0,
            ])
        return {
            "colors": colors,
            "vehicles": vehicles,
            "metrics": {
                "queued": queued_now,
                "arrived": self.arrived,
                "cum_wait": round(self.cum_wait),
            },
        }

    def close(self) -> None:
        close_sumo(self.conn)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def config():
    out = {"scenarios": {}, "episode_seconds": ENV_CFG["episode_seconds"]}
    for name, scen in SCENARIOS.items():
        rl_ok = Path(resolve(scen["model"])).exists()
        out["scenarios"][name] = {
            "profiles": scen["profiles"](),
            "controllers": ["fixed", "actuated", "maxpressure"] + (["rl"] if rl_ok else []),
            "rl_available": rl_ok,
        }
    return out


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    sims: list[SimInstance] = []
    speed = 10.0
    running = False
    try:
        while True:
            if not running:
                msg = await ws.receive_json()
            else:
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=0.001)
                except asyncio.TimeoutError:
                    msg = None

            if msg:
                cmd = msg.get("cmd")
                if cmd == "start":
                    for s in sims:
                        s.close()
                    scenario = msg.get("scenario", "single")
                    sims = [
                        SimInstance(name, scenario, msg["profile"], int(msg.get("seed", 0)))
                        for name in msg["controllers"]
                    ]
                    speed = float(msg.get("speed", 10))
                    running = True
                    await ws.send_json(
                        {
                            "type": "init",
                            "scenario": scenario,
                            "controllers": [s.name for s in sims],
                            "geometry": sims[0].geometry(),
                        }
                    )
                elif cmd == "speed":
                    speed = float(msg["value"])
                elif cmd == "stop":
                    running = False

            if running and sims:
                for s in sims:
                    s.step_second()
                await ws.send_json(
                    {
                        "type": "frame",
                        "time": sims[0].time,
                        "sims": {s.name: s.frame() for s in sims},
                    }
                )
                if sims[0].time >= ENV_CFG["episode_seconds"]:
                    running = False
                    await ws.send_json({"type": "done"})
                else:
                    await asyncio.sleep(1.0 / max(speed, 0.1))
    except WebSocketDisconnect:
        pass
    finally:
        for s in sims:
            s.close()


DOCS_DIR = Path(resolve("docs"))
if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=DOCS_DIR), name="docs")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
