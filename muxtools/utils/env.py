import os
import json
import subprocess
from pathlib import Path
from typing import Any

from ..main import Setup

__all__ = ["save_setup", "get_setup_attr", "get_setup_dir", "get_workdir", "get_temp_workdir", "is_debug", "download_allowed", "run_commandline"]


def save_setup(setup: Setup):
    os.environ["vof_setup"] = setup._toJson()


def get_setup_attr(attr: str, default: Any = None) -> Any:
    envi = os.environ.get("vof_setup")
    if not envi:
        return default
    loaded = json.loads(envi)
    if loaded:
        if isinstance(loaded, dict):
            return loaded.get(attr, default)
        return getattr(loaded, attr, default)
    return default


def get_setup_dir() -> list[str]:
    envi = os.environ.get("vof_setup")
    if not envi:
        return []
    loaded = json.loads(envi)
    return loaded.keys() if isinstance(loaded, dict) else dir(loaded)


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


def run_commandline(
    command: str | list[str], quiet: bool = True, shell: bool = False, stdin=subprocess.DEVNULL, mkvmerge: bool = False, **kwargs
) -> int:
    if os.name != "nt" and isinstance(command, str):
        shell = True
    if quiet:
        p = subprocess.Popen(
            command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, text=True, shell=shell, **kwargs
        )
    else:
        p = subprocess.Popen(command, stdin=stdin, shell=shell, **kwargs)

    returncode = p.wait()
    if returncode > (1 if mkvmerge else 0) and p.stdout and quiet and (lines := p.stdout.readlines()):
        print("\n----------------------")
        for line in lines:
            print(line.rstrip("\n"))
        print("----------------------")

    return returncode
