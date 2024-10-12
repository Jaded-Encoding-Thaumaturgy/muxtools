import os
import re
import json
import subprocess
from pathlib import Path
from typing import Any

from ..main import Setup
from .types import PathLike

__all__ = [
    "save_setup",
    "get_setup_attr",
    "get_setup_dir",
    "get_workdir",
    "get_temp_workdir",
    "is_debug",
    "download_allowed",
    "run_commandline",
    "get_binary_version",
    "version_settings_dict",
]


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


def communicate_stdout(command: list[str] | list[str], shell: bool = False, **kwargs) -> tuple[int, str]:
    if os.name != "nt" and isinstance(command, str):
        shell = True
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, text=True, shell=shell, **kwargs)
    out, err = p.communicate()
    returncode = p.returncode
    stdout = (out or "") + (err or "")
    return (returncode, stdout)


def run_commandline(
    command: str | list[str], quiet: bool = True, shell: bool = False, stdin=subprocess.DEVNULL, mkvmerge: bool = False, **kwargs
) -> int:
    if os.name != "nt" and isinstance(command, str):
        shell = True
    if quiet:
        returncode, stdout = communicate_stdout(command, shell, stdin=stdin, **kwargs)
        if returncode > (1 if mkvmerge else 0) and stdout and quiet and (lines := stdout):
            print("\n----------------------")
            print(lines.strip())
            print("----------------------")
    else:
        p = subprocess.Popen(command, stdin=stdin, shell=shell, **kwargs)
        returncode = p.wait()

    return returncode


def get_binary_version(executable: Path, regex: str, args: list[str] | None = None) -> str | None:
    args = [executable] + args if args else [executable]
    _, readout = communicate_stdout(args)

    reg = re.compile(regex, re.I)

    if match := reg.search(readout):
        return match.group(1)

    return None


def version_settings_dict(
    settings: str, executable: PathLike, regex: str, args: list[str] | None = None, prepend: str | None = None
) -> dict[str, str] | None:
    if not isinstance(executable, Path):
        from .files import ensure_path

        executable = ensure_path(executable, None)

    version = get_binary_version(executable, regex, args)
    if version:
        if prepend:
            version = f"{prepend} {version}"
        return dict(ENCODER=version, ENCODER_SETTINGS=settings)
    return None
