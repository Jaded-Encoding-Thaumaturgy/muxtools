from .log import crit, error

import os
import sys
import shutil as sh
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from itertools import chain
from typing import Literal, overload
from contextlib import nullcontext

__all__: list[str] = [
    "get_executable",
    "download_binary",
    "download_file",
    "unpack_all",
]


@overload
def get_executable(type: str, can_error: Literal[True] = ...) -> str: ...


@overload
def get_executable(type: str, can_error: Literal[False] = ...) -> str | None: ...


def get_executable(type: str, can_error: bool = True) -> str | None:
    from .binaries.runner import get_managed_executable

    env = os.environ.get(f"vof_exe_{type.lower()}", None)
    if env:
        path = Path(env)
        if path.exists():
            return str(path.resolve())
        if not can_error:
            return None
        raise error(f"Custom executable for {type} not found!", get_executable)
    try:
        path = get_managed_executable(type)
    except FileNotFoundError:
        if not can_error:
            return None
        raise
    if path is None and can_error:
        raise crit(f"{type.lower()} executable not found in path!", get_executable)
    return path


def download_file(url: str, destination: Path, show_progress: bool = True) -> Path:
    if destination.is_dir():
        destination /= Path(urlsplit(url).path).name

    import niquests

    with niquests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        try:
            total = int(content_length) if content_length else None
        except ValueError:
            total = None

        file = NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False)
        temporary = Path(file.name)
        from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn

        progress_display = (
            Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            )
            if show_progress
            else nullcontext()
        )
        try:
            with file, progress_display as progress:
                task = progress.add_task(destination.name, total=total) if progress else None
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    file.write(chunk)
                    if progress and task is not None:
                        progress.update(task, advance=len(chunk))
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    return destination


def download_binary(type: str) -> str:
    from .binaries.operations import install, load_catalog, parse_spec, scope_path
    from .binaries.runner import _get_fitting_variant
    from ..config import discover_config

    config = discover_config()
    root = scope_path(config)
    item = install(parse_spec(type), load_catalog(), root)
    entry = item.get("binaries", {}).get(type)
    if entry is None:
        raise ValueError(f"Installed package does not provide {type!r}")
    return str(_get_fitting_variant(entry, Path(item["_path"])))


def unpack_all(dir: Path | str):
    dir = Path(dir) if isinstance(dir, str) else dir

    if sys.version_info < (3, 14):
        from backports.zstd import register_shutil

        register_shutil()

    for file in chain(dir.rglob("*.zip"), dir.rglob("*.tar.zst"), dir.rglob("*.tar")):
        if file.is_dir():
            continue
        out = Path(os.path.join(file.resolve(True).parent, file.stem.replace(".tar", "")))
        out.mkdir(exist_ok=True)
        sh.unpack_archive(file, out)
        os.remove(file)

    for file in dir.rglob("*.7z"):
        try:
            import py7zr as p7z
        except:
            raise error("Please install py7zr if you want to unpack 7z files.", get_executable)
        out = Path(os.path.join(file.resolve(True).parent, file.stem))
        out.mkdir(exist_ok=True)
        p7z.unpack_7zarchive(file, out)
        os.remove(file)
