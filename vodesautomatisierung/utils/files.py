import os
import binascii
from abc import ABC
from pathlib import Path
from typing import TypeVar
from dataclasses import dataclass
from pymediainfo import Track, MediaInfo
from utils.env import get_workdir
from utils.log import *
from utils.types import AudioInfo

__all__ = [
    "VideoFile",
    "AudioFile",
    "SubtitleFile",
    "PathLike",
    "get_path",
    "ensure_path",
    "uniquify_path",
    "get_crc32",
    "make_output",
    "ensure_path_exists",
]

PathLike = TypeVar("PathLike", str, Path, None)


def get_path(pathIn: PathLike) -> Path | None:
    return None if pathIn is None else Path(pathIn).resolve()


def ensure_path(pathIn: PathLike, caller: any) -> Path:
    """
    Utility function for other functions to make sure a path was passed to them.

    :param pathIn:      Supposed passed Path
    :param caller:      Caller name used for the exception and error message
    """
    if pathIn is None:
        raise crit("Path cannot be None.", caller)
    else:
        return Path(pathIn).resolve()


def ensure_path_exists(pathIn: PathLike, caller: any, allow_dir: bool = False) -> Path:
    """
    Utility function for other functions to make sure a path was passed to them and that it exists.

    :param pathIn:      Supposed passed Path
    :param caller:      Caller name used for the exception and error message
    """
    path = ensure_path(pathIn, caller)
    if not path.exists():
        raise crit(f"Path target '{path}' does not exist.", caller)
    if not allow_dir and path.is_dir():
        raise crit(f"Path cannot be a directory.", caller)
    return path


def make_output(source: PathLike, ext: str, suffix: str = "", user_passed: PathLike | None = None) -> Path:
    workdir = get_workdir()
    source_stem = Path(source).stem

    if user_passed:
        user_passed = Path(user_passed)
        if user_passed.exists() and user_passed.is_dir():
            return Path(user_passed, f"{source_stem}.{ext}")
        else:
            return user_passed.with_suffix(f".{ext}")
    else:
        return Path(uniquify_path(os.path.join(workdir, f"{source_stem}{f'_{suffix}' if suffix else ''}.{ext}")))


def uniquify_path(path: PathLike) -> str:
    """
    Extends path to not conflict with existing files

    :param file:        Input file

    :return:            Unique path
    """

    if isinstance(path, Path):
        path = str(path.resolve())

    filename, extension = os.path.splitext(path)
    counter = 1

    while os.path.exists(path):
        path = filename + " (" + str(counter) + ")" + extension
        counter += 1

    return path


def get_crc32(file: PathLike) -> str:
    """
    Generates crc32 checksum for file

    :param file:        Input file

    :return:            Checksum for file
    """
    buf = open(file, "rb").read()
    buf = binascii.crc32(buf) & 0xFFFFFFFF
    return "%08X" % buf


@dataclass
class FileMixin:
    file: PathLike
    container_delay: int = 0
    source: PathLike | None = None


class MuxingFile(ABC, FileMixin):
    def __post_init__(self):
        self.file = ensure_path(self.file, self)


@dataclass
class VideoFile(MuxingFile):
    pass


@dataclass
class AudioFile(MuxingFile):
    info: AudioInfo | None = None

    def get_mediainfo(self) -> Track:
        return MediaInfo.parse(self.file).audio_tracks[0]

    def is_lossy(self) -> bool:
        from utils.format import format_from_track

        minfo = self.get_mediainfo()
        form = format_from_track(minfo)
        if form:
            return form.lossy

        return getattr(minfo, "compression_mode", True)

    def has_multiple_tracks(self, caller: any = None) -> bool:
        fileIn = ensure_path_exists(self.file, caller)
        minfo = MediaInfo.parse(fileIn)
        if len(minfo.audio_tracks) > 1 or len(minfo.video_tracks) > 1 or len(minfo.text_tracks) > 1:
            return True
        elif len(minfo.audio_tracks) == 0:
            raise error(f"'{fileIn.name}' does not contain an audio track!", caller)
        return False

    @staticmethod
    def from_file(pathIn: PathLike, caller: any):
        from utils.log import warn

        warn("It's strongly recommended to explicitly extract tracks first!", caller, 1)
        file = ensure_path_exists(pathIn, caller)
        return AudioFile(file, 0, file)


@dataclass
class SubtitleFile(MuxingFile):
    pass
