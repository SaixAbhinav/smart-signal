"""Locate SUMO binaries and manage TraCI/libsumo connections."""

import os
import sys
from pathlib import Path


def ensure_sumo_home() -> str:
    """Make sure SUMO_HOME is set, preferring the pip-installed eclipse-sumo wheel."""
    if "SUMO_HOME" in os.environ and Path(os.environ["SUMO_HOME"]).exists():
        return os.environ["SUMO_HOME"]
    try:
        import sumo  # provided by the eclipse-sumo wheel

        os.environ["SUMO_HOME"] = sumo.SUMO_HOME
        return sumo.SUMO_HOME
    except ImportError as e:
        raise RuntimeError(
            "SUMO not found: set SUMO_HOME or `pip install eclipse-sumo`."
        ) from e


def sumo_binary(gui: bool = False) -> str:
    home = Path(ensure_sumo_home())
    name = "sumo-gui" if gui else "sumo"
    exe = name + (".exe" if sys.platform == "win32" else "")
    candidate = home / "bin" / exe
    return str(candidate) if candidate.exists() else name  # fall back to PATH


def build_sumo_cmd(
    net_file: str,
    route_file: str,
    gui: bool = False,
    seed: int | None = None,
    tripinfo_file: str | None = None,
    emissions: bool = False,
    extra: list[str] | None = None,
) -> list[str]:
    cmd = [
        sumo_binary(gui),
        "-n", net_file,
        "-r", route_file,
        "--no-step-log", "true",
        "--no-warnings", "true",
        "--waiting-time-memory", "10000",
        "--duration-log.disable", "true",
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if tripinfo_file:
        cmd += ["--tripinfo-output", tripinfo_file]
    if emissions:
        cmd += ["--device.emissions.probability", "1.0"]
    if gui:
        cmd += ["--start", "--quit-on-end"]
    if extra:
        cmd += extra
    return cmd


_label_counter = 0


def start_sumo(cmd: list[str], use_libsumo: bool = False):
    """Start a simulation and return a connection-like object.

    With libsumo there is exactly one simulation per process and the module
    itself acts as the connection. With TraCI each call gets a unique label so
    several simulations can run side by side (used by the dashboard).
    """
    ensure_sumo_home()
    global _label_counter
    if use_libsumo:
        import libsumo

        libsumo.start(cmd)
        return libsumo
    import traci

    _label_counter += 1
    label = f"smartsignal_{os.getpid()}_{_label_counter}"
    traci.start(cmd, label=label)
    return traci.getConnection(label)


def close_sumo(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass
