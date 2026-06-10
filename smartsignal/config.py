"""Load YAML configuration files relative to the project root."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_ROOT / "configs"


def load_config(name: str = "default") -> dict:
    path = CONFIGS_DIR / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_demand_profiles() -> dict:
    return load_config("demand")["profiles"]


def resolve(path: str) -> str:
    """Resolve a project-relative path to an absolute one."""
    p = Path(path)
    return str(p if p.is_absolute() else PROJECT_ROOT / p)
