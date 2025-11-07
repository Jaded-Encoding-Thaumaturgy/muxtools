from .env import download_allowed
from .types import PathLike
from .log import crit, error, info
from .files import ensure_path_exists

import os
import wget  # type: ignore[import-untyped]
import shutil as sh
from pathlib import Path
from dataclasses import dataclass
from typing import Literal, overload

__all__: list[str] = [
    "get_executable",
    "download_binary",
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
    Tool("ffmpeg", "https://github.com/Vodes/muxtools-binaries/releases/download/latest-ffmpeg/ffmpeg-latest-windows-amd64.zip", ["ffprobe"]),
    Tool("mkvmerge", "https://github.com/Vodes/muxtools-binaries/releases/download/latest-mkvtoolnix/mkvtoolnix-latest-windows-amd64.zip", ['mkvextract', 'mkvinfo', 'mkvpropedit']), 
    Tool("eac3to", "https://files.catbox.moe/hn9oms.7z"), # Custom package because of removed sounds and updated libFlac
    Tool("x264", "https://github.com/DJATOM/x264-aMod/releases/download/r3101+20/x264-aMod-x64-core164-r3101+20.7z"),
    Tool("x265", "https://github.com/DJATOM/x265-aMod/releases/download/3.5+67/x265-x64-v3.5+67-aMod-gcc12.2.1+opt.7z"),
    Tool("qaac", "https://pomf2.lain.la/f/u8yyfyed.7z"), # 2.85 with flac, w64 and iTunes libraries included; Yes catbox frontend is down and I can't upload stuff there right now
    Tool("opusenc", "https://github.com/Vodes/muxtools-binaries/releases/download/latest-opus-tools/opus-tools-latest-windows-amd64.zip"),
    Tool("flac", "https://github.com/Vodes/muxtools-binaries/releases/download/latest-flac/flac-latest-windows-amd64.zip"),
    Tool("wavpack", "https://github.com/dbry/WavPack/releases/download/5.8.1/wavpack-5.8.0-x64.zip")
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

    wget.download(url, str(binary_dir.resolve()))
    print("")
    info("Done.", get_executable)
    unpack_all(binary_dir)

    executable = _find_downloaded_binary(type)

    if executable is None:
        raise error(f"Binary for '{type}' could not have been found!", get_executable)

    return str(executable.resolve())


def unpack_all(dir: Path | str):
    dir = Path(dir) if isinstance(dir, str) else dir

    for file in dir.rglob("*.zip"):
        out = Path(os.path.join(file.resolve(True).parent, file.stem))
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
