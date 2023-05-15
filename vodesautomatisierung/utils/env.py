import os
import json
from pathlib import Path
from .log import info
from ..main import Setup

__all__ = ["save_setup", "get_setup_attr", "get_workdir", "get_temp_workdir", "is_debug"]


def save_setup(setup: Setup):
    os.environ["vof_setup"] = setup.toJson()


def get_setup_attr(attr: str, default: any = None) -> any:
    envi = os.environ.get("vof_setup")
    if not envi:
        return default
    loaded = json.loads(envi)
    if loaded:
        if isinstance(loaded, dict):
            return loaded.get(attr, default)
        return getattr(loaded, attr, default)
    return default


def get_workdir() -> Path:
    return Path(get_setup_attr("work_dir", os.getcwd()))


def get_temp_workdir() -> Path:
    wd = Path(get_workdir(), ".temp")
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def is_debug() -> bool:
    return get_setup_attr("debug", True)
