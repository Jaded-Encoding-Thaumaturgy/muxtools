import os
import json
import subprocess
from pathlib import Path

from ..main import Setup

__all__ = ["save_setup", "get_setup_attr", "get_workdir", "get_temp_workdir", "is_debug", "download_allowed", "run_commandline"]


def save_setup(setup: Setup):
    os.environ["vof_setup"] = setup._toJson()


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
    return wd.resolve()


def is_debug() -> bool:
    return get_setup_attr("debug", True)


def download_allowed() -> bool:
    return get_setup_attr("allow_binary_download", False)


def run_commandline(command: str | list[str], quiet: bool = True, shell: bool = False, stdin=subprocess.DEVNULL, **kwargs) -> int:
    if os.name != "nt" and isinstance(command, str):
        shell = True
    if quiet:
        p = subprocess.Popen(command, stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=shell, **kwargs)
    else:
        p = subprocess.Popen(command, stdin=stdin, shell=shell, **kwargs)

    return p.wait()
