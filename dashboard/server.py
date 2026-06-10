"""SmartSignal live comparison dashboard.

Runs several SUMO simulations in lockstep — identical network, demand, and
seed, but different signal controllers — and streams their state to the
browser over a WebSocket.

Run with:  uvicorn dashboard.server:app  (from the project root)
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from smartsignal.config import load_config, load_demand_profiles, resolve
from smartsignal.controllers import CONTROLLERS
from smartsignal.demand.generate_routes import route_file_for
from smartsignal.env.sumo_utils import build_sumo_cmd, close_sumo, start_sumo
from smartsignal.env.traffic_signal import TrafficSignal
from smartsignal.evaluation.runner import apply_decision

STATIC_DIR = Path(__file__).parent / "static"
CFG = load_config()
ENV_CFG = CFG["env"]
MODEL_PATH = Path(resolve(CFG["paths"]["models_dir"])) / "ppo_single.zip"

app = FastAPI(title="SmartSignal")


class SimInstance:
    """One controller's simulation plus its live metrics."""

    def __init__(self, name: str, profile: str, seed: int):
        self.name = name
        kwargs = {
            "green_duration": CFG["fixed_time"]["green_duration"],
            "max_green": ENV_CFG["max_green"],
        }
        if name == "rl":
            kwargs["model_path"] = str(MODEL_PATH)
        self.controller = CONTROLLERS[name](**kwargs)

        cmd = build_sumo_cmd(
            resolve(ENV_CFG["net_file"]), route_file_for(profile), seed=seed
        )
        self.conn = start_sumo(cmd, use_libsumo=False)
        self.ts_id = self.conn.trafficlight.getIDList()[0]
        if self.controller.uses_builtin_program:
            self.ts = None
            lanes = self.conn.trafficlight.getControlledLanes(self.ts_id)
            self.in_lanes = list(dict.fromkeys(lanes))
        else:
            self.ts = TrafficSignal(
                self.conn, self.ts_id, ENV_CFG["yellow_time"], ENV_CFG["min_green"]
            )
            self.in_lanes = self.ts.in_lanes
        self.controller.reset(self.ts)

        # lane -> indices into the signal state string (for rendering colors)
        self.lane_sig: dict[str, list[int]] = {l: [] for l in self.in_lanes}
        for i, link in enumerate(self.conn.trafficlight.getControlledLinks(self.ts_id)):
            if link:
                self.lane_sig[link[0][0]].append(i)

        self.time = 0
        self.arrived = 0
        self.cum_wait = 0.0  # vehicle-seconds spent halted

    def step_second(self) -> None:
        if self.ts is not None and self.time % ENV_CFG["delta_time"] == 0:
            apply_decision(
                self.ts,
                self.controller.decide(self.ts, self.time),
                ENV_CFG["max_green"],
            )
        self.conn.simulationStep()
        if self.ts is not None:
            self.ts.tick(1.0)
        self.time += 1
        self.arrived += self.conn.simulation.getArrivedNumber()

    def frame(self) -> dict:
        state = self.conn.trafficlight.getRedYellowGreenState(self.ts_id)
        rank = {"G": 3, "g": 2, "y": 1}
        colors, queues = {}, {}
        queued_now = 0
        for lane, sig_idxs in self.lane_sig.items():
            best = max((state[i] for i in sig_idxs), key=lambda c: rank.get(c, 0), default="r")
            colors[lane] = "green" if best in "Gg" else "yellow" if best == "y" else "red"
            q = self.conn.lane.getLastStepHaltingNumber(lane)
            queues[lane] = q
            queued_now += q
        self.cum_wait += queued_now
        return {
            "colors": colors,
            "queues": queues,
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
    return {
        "profiles": list(load_demand_profiles()),
        "controllers": ["fixed", "actuated", "maxpressure"]
        + (["rl"] if MODEL_PATH.exists() else []),
        "rl_available": MODEL_PATH.exists(),
        "episode_seconds": ENV_CFG["episode_seconds"],
    }


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
                # poll for control messages without blocking the sim loop
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=0.001)
                except asyncio.TimeoutError:
                    msg = None

            if msg:
                cmd = msg.get("cmd")
                if cmd == "start":
                    for s in sims:
                        s.close()
                    sims = [
                        SimInstance(name, msg["profile"], int(msg.get("seed", 0)))
                        for name in msg["controllers"]
                    ]
                    speed = float(msg.get("speed", 10))
                    running = True
                    await ws.send_json(
                        {
                            "type": "init",
                            "controllers": [s.name for s in sims],
                            "lanes": sims[0].in_lanes,
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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
