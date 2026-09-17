from .env import download_allowed
from .types import PathLike
from .log import crit, error, info
from .files import ensure_path_exists

import os
import sys
import shutil as sh
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from itertools import chain
from dataclasses import dataclass
from typing import Literal, overload

__all__: list[str] = [
    "get_executable",
    "download_binary",
    "download_file",
    "unpack_all",
]


@dataclass
class Tool:
    name: str
    url: str
    alias: list[str] | None = None


# fmt: off
# Feel free to compare the hashes if you don't like the custom files
tools = [
    Tool("CUETools.FLACCL.cmd", "https://github.com/gchudov/cuetools.net/releases/download/v2.2.6/CUETools_2.2.6.zip", ["flaccl"]),
    # non-free builds for libfdk_aac if one so desires
    Tool("ffmpeg", "https://github.com/Vodes/muxtools-binaries/releases/download/ffmpeg-9.0.1-27-g9b0578816c-2026-09-07/ffmpeg-9.0.1-27-g9b0578816c-2026-09-07-windows-x86_64.tar.zst", ["ffprobe"]),
    Tool("mkvmerge", "https://github.com/Vodes/muxtools-binaries/releases/download/mkvtoolnix-101.0/mkvtoolnix-101.0-windows-x86_64.tar.zst", ['mkvextract', 'mkvinfo', 'mkvpropedit']),
    Tool("eac3to", "https://files.catbox.moe/hn9oms.7z"), # Custom package because of removed sounds and updated libFlac
    Tool("x264", "https://github.com/Vodes/muxtools-binaries/releases/download/x264-r3222-b35605a/x264-r3222-b35605a-windows-x86_64.tar.zst"),
    Tool("x265", "https://github.com/Vodes/muxtools-binaries/releases/download/x265-4.2/x265-4.2-windows-x86_64.tar.zst"),
    Tool("qaac", "https://pomf2.lain.la/f/u8yyfyed.7z"), # 2.85 with flac, w64 and iTunes libraries included; Yes catbox frontend is down and I can't upload stuff there right now
    Tool("opusenc", "https://github.com/Vodes/muxtools-binaries/releases/download/opus-tools-0.2-libopus-1.6.1/opus-tools-0.2-libopus-1.6.1-windows-x86_64.tar.zst"),
    Tool("flac", "https://github.com/Vodes/muxtools-binaries/releases/download/flac-1.5.0.post1/flac-1.5.0.post1-windows-x86_64.tar.zst"),
    Tool("wavpack", "https://github.com/Vodes/muxtools-binaries/releases/download/wavpack-5.9.0/wavpack-5.9.0-windows-x86_64.tar.zst")
]
# fmt: on

# TODO: check CPU to decide on which x264/5 file to use


@overload
def get_executable(type: str, can_download: bool | None = None, can_error: Literal[True] = ...) -> str: ...


@overload
def get_executable(type: str, can_download: bool | None = None, can_error: Literal[False] = ...) -> str | None: ...


def get_executable(type: str, can_download: bool | None = None, can_error: bool = True) -> str | None:
    if can_download is None:
        can_download = download_allowed()
    path = sh.which(type)
    env = os.environ.get(f"vof_exe_{type.lower()}", None)
    if env:
        path = Path(env)
        if path.exists():
            return str(path.resolve())
        else:
            if not can_error:
                return None
            raise error(f"Custom executable for {type} not found!", get_executable)

    if path is None:
        if not can_download or can_download is False:
            if os.name == "nt" and (exe := _find_downloaded_binary(type)):
                return str(exe)

            if not can_error:
                return None

            raise crit(f"{type.lower()} executable not found in path!", get_executable)
        else:
            path = download_binary(type.lower())

    return str(path)


def _find_downloaded_binary(type: str) -> Path | None:
    binary_dir = Path(os.path.join(os.getcwd(), "_binaries"))
    binary_dir.mkdir(exist_ok=True)

    type = type.lower()

    executables = binary_dir.rglob(type + "*.exe")

    for exe in sorted(executables):
        if exe.is_file():
            _append_exe_to_path(exe)
            return exe.resolve()
    return None


def _append_exe_to_path(file: PathLike) -> None:
    file = ensure_path_exists(file, get_executable, True)
    if file.is_file():
        file = file.parent
    if str(file.resolve()) not in os.environ["PATH"].split(os.pathsep):
        os.environ["PATH"] = os.pathsep.join([str(file.resolve()), os.environ["PATH"]])


def download_file(url: str, destination: Path) -> Path:
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

        try:
            with (
                file,
                Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeRemainingColumn(),
                ) as progress,
            ):
                task = progress.add_task(destination.name, total=total)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    file.write(chunk)
                    progress.update(task, advance=len(chunk))
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    return destination


def download_binary(type: str) -> str:
    if os.name != "nt":
        raise EnvironmentError("Of course only Windows is supported for downloading of binaries!")

    if exe := _find_downloaded_binary(type):
        return str(exe)

    binary_dir = Path(os.path.join(os.getcwd(), "_binaries"))

    info(f"Downloading {type} executables...", get_executable)
    url = None
    for tool in tools:
        if tool.name.lower() == type:
            url = tool.url
        else:
            if tool.alias:
                for name in tool.alias:
                    if name.lower() == type:
                        url = tool.url

    if not url:
        raise error(f"There is no tool registered for {type}!", get_executable)

    download_file(url, binary_dir.resolve())
    info("Done.", get_executable)
    unpack_all(binary_dir)

    executable = _find_downloaded_binary(type)

    if executable is None:
        raise error(f"Binary for '{type}' could not have been found!", get_executable)

    return str(executable.resolve())


def unpack_all(dir: Path | str):
    dir = Path(dir) if isinstance(dir, str) else dir

    if sys.version_info < (3, 14):
        from backports.zstd import register_shutil

        register_shutil()

    for file in chain(dir.rglob("*.zip"), dir.rglob("*.tar.zst")):
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
