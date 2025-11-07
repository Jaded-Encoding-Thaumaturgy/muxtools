import json
from enum import IntEnum
from pathlib import Path
from fractions import Fraction
from typing import Union, Optional
from datetime import timedelta
from dataclasses import dataclass, asdict
from video_timestamps import ABCTimestamps

from ..utils.dataclass import FractionEncoder, fraction_hook

__all__ = [
    "PathLike",
    "Paths",
    "Trim",
    "TrackType",
    "AudioFrame",
    "AudioStats",
    "AudioInfo",
    "Chapter",
    "LooseChapter",
    "DitherType",
    "LossyWavQuality",
    "VideoMeta",
    "TimeScale",
    "FileMixin",
]

PathLike = Union[Path, str, None]
Trim = tuple[int | None, int | None]

Paths = Union[PathLike, list[PathLike]]

LooseChapter = tuple[timedelta | int, Optional[str]]
"""
Chapter type where the time can be a frame number or timedelta.\n
The chapters class will normalize these to just timedeltas.
"""

Chapter = tuple[timedelta, Optional[str]]


class TrackType(IntEnum):
    VIDEO = 1
    AUDIO = 2
    SUB = 3
    ATTACHMENT = 4
    CHAPTERS = 5
    MKV = 6


@dataclass
class VideoMeta:
    pts: list[int]
    fps: Fraction
    timescale: Fraction
    source: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), cls=FractionEncoder, indent=4)

    @staticmethod
    def from_json(file: PathLike) -> "VideoMeta":
        from .files import ensure_path_exists

        with open(ensure_path_exists(file, VideoMeta), "r", encoding="utf-8") as f:
            meta_json = json.loads(f.read(), object_hook=fraction_hook)
            return VideoMeta(**meta_json)


class TimeScale(IntEnum):
    """Convenience enum for some common timescales."""

    MKV = 1000
    """Typical matroska timescale"""
    MATROSKA = MKV
    """Alias for MKV"""
    M2TS = 90000
    """Typical m2ts timescale"""


TimeSourceT = PathLike | Fraction | float | list | VideoMeta | ABCTimestamps
"""
The source of timestamps/timecodes.\n
For actual timestamps, this can be a timestamps (v1/v2/v4) file, a video file or a list of integers.\n
For FPS based timestamps, this can be a Fraction object, a float or even a string representing a fraction.\n
Like `'24000/1001'`.\n
Can also be an already instantiated Timestamps class from the videotimestamps library.\n
`None` will usually fallback to 24000/1001 but exact behavior might differ based on the target function.
"""

TimeScaleT = TimeScale | Fraction | int | None
"""
Unit of time (in seconds) in terms of which frame timestamps are represented.\n
While you can pass an int, the needed type is always a Fraction and will be converted via `Fraction(your_int)`.\n
`None` will usually fallback to a generic mkv timescale but exact behavior might differ based on the target function.
"""


class DitherType(IntEnum):
    """
    FFMPEG Dither Methods, see https://ffmpeg.org/ffmpeg-resampler.html#Resampler-Options
    """

    RECTANGULAR = 1
    TRIANGULAR = 2  # Allegedly SoX's default
    TRIANGULAR_HP = 3
    LIPSHITZ = 4
    SHIBATA = 5  # Foobar uses this for example
    LOW_SHIBATA = 6
    HIGH_SHIBATA = 7
    F_WEIGHTED = 8
    MODIFIED_E_WEIGHTED = 9
    IMPROVED_E_WEIGHTED = 10


class qAAC_MODE(IntEnum):
    TVBR = 1
    CVBR = 2
    ABR = 3
    CBR = 4


class LossyWavQuality(IntEnum):
    """
    LossyWAV Quality presets, see https://wiki.hydrogenaud.io/index.php?title=LossyWAV#Quality_presets

    TL;DR: Insane the least lossy, ExtraPortable the most lossy.
    """

    INSANE = 1
    EXTREME = 2
    HIGH = 3
    STANDARD = 4
    ECONOMIC = 5
    PORTABLE = 6
    EXTRAPORTABLE = 7


class ValidInputType(IntEnum):
    FLAC = 1
    W64 = 3
    RF64 = 4
    W64_OR_FLAC = 6
    RF64_OR_FLAC = 7

    def allows_flac(self) -> bool:
        return "_OR_FLAC" in str(self.name)

    def remove_flac(self):
        match self:
            case ValidInputType.RF64_OR_FLAC:
                return ValidInputType.RF64
            case ValidInputType.W64_OR_FLAC:
                return ValidInputType.W64

        return ValidInputType.RF64


class FileMixin:
    file: Path
    container_delay: int = 0
    source: PathLike | None = None
    tags: dict[str, str] | None = None

    def __init__(
        self,
        file: Path,
        container_delay: int = 0,
        source: PathLike | None = None,
        tags: dict[str, str] | None = None,
    ):
        self.file = file
        self.container_delay = container_delay
        self.source = source
        self.tags = tags


@dataclass
class AudioFrame:
    """
    A dataclass representing ffmpeg's `ashowdata` filter output.

    :param n:           The (sequential) number of the input frame, starting from 0
    :param pts:         The presentation timestamp of the input frame, in time base units
                        the time base depends on the filter input pad, and is usually 1/sample_rate

    :param pts_time:    The presentation timestamp of the input frame in seconds
    :param num_samples: Number of samples in a frame (can also be refered to as frame length or size)
    """

    n: int
    pts: int
    pts_time: float
    num_samples: int


@dataclass
class AudioStats:
    """
    A dataclass representing ffmpeg's `astats` filter output.

    Too many attributes to document to be honest.

    See https://ffmpeg.org/ffmpeg-filters.html#astats-1
    """

    dc_offset: float = 0.0
    min_level: float = 0.0
    max_level: float = 0.0
    min_difference: float = 0.0
    max_difference: float = 0.0
    mean_difference: float = 0.0
    rms_difference: float = 0.0
    peak_level_db: float = 0.0
    rms_level_db: float = 0.0
    rms_peak_db: float = 0.0
    rms_trough_db: float = 0.0
    flat_factor: float = 0.0
    peak_count: float = 0.0
    noise_floor_db: float = 0.0
    noise_floor_count: float = 0.0
    entropy: float = 0.0
    bit_depth: str = ""
    number_of_samples: int = 0


@dataclass
class AudioInfo:
    stats: AudioStats | None = None
    frames: list[AudioFrame] | None = None

    def num_samples(self) -> int:
        if not self.frames:
            return 0
        for frame in self.frames:
            if frame.num_samples:
                return frame.num_samples

        return 0
