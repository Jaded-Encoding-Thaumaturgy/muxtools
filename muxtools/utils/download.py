from .env import download_allowed
from .types import PathLike
from .log import *

import os
import wget
import shutil as sh
import py7zr as p7z
from pathlib import Path
from dataclasses import dataclass

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
    Tool("CUETools.FLACCL.cmd", "https://github.com/gchudov/cuetools.net/releases/download/v2.2.5/CUETools_2.2.5.zip", ["flaccl"]),
    # non-free builds for libfdk_aac if one so desires
    Tool("ffmpeg", "https://github.com/AnimMouse/ffmpeg-autobuild/releases/download/2024-03-10-12-25-64634e8-a8e823a/ffmpeg-64634e8-a8e823a-win64-nonfree.7z", ["ffprobe"]),
    Tool("mkvmerge", "https://mkvtoolnix.download/windows/releases/83.0/mkvtoolnix-64-bit-83.0.7z", ['mkvextract', 'mkvinfo', 'mkvpropedit']), 
    Tool("eac3to", "https://files.catbox.moe/hn9oms.7z"), # Custom package because of removed sounds and updated libFlac
    Tool("x264", "https://github.com/DJATOM/x264-aMod/releases/download/r3101+20/x264-aMod-x64-core164-r3101+20.7z"),
    Tool("x265", "https://github.com/DJATOM/x265-aMod/releases/download/3.5+67/x265-x64-v3.5+67-aMod-gcc12.2.1+opt.7z"),
    Tool("qaac", "https://files.catbox.moe/z9q796.7z"), # 2.79 with flac, w64 and iTunes libraries included
    Tool("opusenc", "https://www.rarewares.org/files/opus/opustools-0.2-20230419-x64.zip"),
    Tool("flac", "https://github.com/xiph/flac/releases/download/1.4.3/flac-1.4.3-win.zip"),
    Tool("wavpack", "https://github.com/dbry/WavPack/releases/download/5.6.0/wavpack-5.6.0-x64.zip")
]
# fmt: on

# TODO: check CPU to decide on which x264/5 file to use


def get_executable(type: str, can_download: bool | None = None, can_error: bool = True) -> str:
    if can_download is None:
        can_download = download_allowed()
    type = type.lower()
    path = sh.which(type)
    env = os.environ.get(f"vof_exe_{type}", None)
    if env:
        path = Path(env)
        if path.exists():
            return str(path.resolve())
        else:
            if not can_error:
                return None
            raise error(f"Custom executable for {type} not found!", get_executable)

    if path is None:
        if not can_download or can_download == False:
            if not can_error:
                return None
            raise crit(f"{type.lower()} executable not found in path!", get_executable)
        else:
            path = download_binary(type)

    return path


def download_binary(type: str) -> str:
    if os.name != "nt":
        raise EnvironmentError("Of course only Windows is supported for downloading of binaries!")

    binary_dir = Path(os.path.join(os.getcwd(), "_binaries"))
    binary_dir.mkdir(exist_ok=True)

    type = type.lower()

    executable: Path = None
    executables = binary_dir.rglob(type + "*.exe")

    for exe in sorted(executables):
        if exe.is_file():
            return exe.resolve()

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
    info(f"Done.", get_executable)
    unpack_all(binary_dir)

    executables = binary_dir.rglob(type.lower() + "*.exe")

    for exe in sorted(executables):
        if exe.is_file():
            executable = exe

    if executable is None:
        raise error(f"Binary for '{type}' could not have been found!", get_executable)

    return str(executable.resolve())


def unpack_all(dir: PathLike):
    dir = Path(dir) if isinstance(dir, str) else dir

    for file in dir.rglob("*.zip"):
        out = Path(os.path.join(file.resolve(True).parent, file.stem))
        out.mkdir(exist_ok=True)
        sh.unpack_archive(file, out)
        os.remove(file)

    for file in dir.rglob("*.7z"):
        out = Path(os.path.join(file.resolve(True).parent, file.stem))
        out.mkdir(exist_ok=True)
        p7z.unpack_7zarchive(file, out)
        os.remove(file)
