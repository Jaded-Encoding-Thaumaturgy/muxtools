import os
from typing import Any
from math import trunc
from pathlib import Path
from fractions import Fraction
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_DOWN
from video_timestamps import FPSTimestamps, RoundingMethod, TextFileTimestamps, VideoTimestamps, ABCTimestamps, TimeType

from ..utils.types import PathLike, TimeScale, VideoMeta, TimeSourceT, TimeScaleT
from ..utils.log import info, warn, crit, debug, error
from ..utils.files import ensure_path_exists, get_workdir, ensure_path
from ..utils.env import get_setup_attr
from ..utils.download import get_executable
from ..utils.probe import ParsedFile

__all__: list[str] = [
    "format_timedelta",
    "timedelta_from_formatted",
    "get_timemeta_from_video",
    "resolve_timesource_and_scale",
    "TimeType",
    "ABCTimestamps",
    "RoundingMethod",
]


class ExtrapolatingVideoTimestamps(VideoTimestamps):
    """
    Simple class extending VideoTimestamps to add back extrapolation for frames past the video.\n
    This works by getting the average framerate from the existing timestamps and assuming CFR from then on.
    """

    backing_fps_timestamps: FPSTimestamps

    def __init__(
        self,
        pts_list: list[int],
        time_scale: Fraction,
        normalize: bool = True,
        rounding_method: RoundingMethod = RoundingMethod.ROUND,
    ):
        super().__init__(pts_list, time_scale, normalize)

        # https://github.com/TypesettingTools/Aegisub/blob/a63edfe8bbf146c89744a3441907541ba7d8ed25/libaegisub/common/vfr.cpp#L154
        fps = Fraction((len(self.pts_list) - 1) * time_scale, self.pts_list[-1] - self.pts_list[0])
        self.backing_fps_timestamps = FPSTimestamps(rounding_method, time_scale, fps, self.first_timestamps)

    def _time_to_frame(
        self,
        time: Fraction,
        time_type: TimeType,
    ) -> int:
        if time > self.timestamps[-1]:
            return self.backing_fps_timestamps._time_to_frame(time, time_type)

        return super()._time_to_frame(time, time_type)

    def _frame_to_time(
        self,
        frame: int,
    ) -> Fraction:
        if frame > self.nbr_frames:
            return self.backing_fps_timestamps._frame_to_time(frame)

        return super()._frame_to_time(frame)


def get_timemeta_from_video(video_file: PathLike, out_file: PathLike | None = None, caller: Any | None = None) -> VideoMeta:
    """
    Parse timestamps from an existing video file using ffprobe.\n
    They're saved as a custom meta file in the current workdir and named based on the input.

    Also automatically reused (with a debug log) if already exists.

    :param video_file:      Input video. Path or String.
    :param out_file:        Output file. If None given, the above behavior applies.
    :param caller:          Caller used for the logging

    :return:                Videometa object
    """
    video_file = ensure_path_exists(video_file, get_timemeta_from_video)
    assert get_executable("ffprobe")
    if not out_file:
        out_file = get_workdir() / f"{video_file.stem}_meta.json"

    out_file = ensure_path(out_file, get_timemeta_from_video)
    if not out_file.exists() or out_file.stat().st_size < 1:
        info(f"Generating timestamps for '{video_file.name}'...", caller)
        timestamps = VideoTimestamps.from_video_file(video_file)
        meta = VideoMeta(timestamps.pts_list, timestamps.fps, timestamps.time_scale, str(video_file.resolve()))
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(meta.to_json())
    else:
        meta = VideoMeta.from_json(out_file)
        debug(f"Reusing existing timestamps for '{video_file.name}'", caller)
    return meta


def resolve_timesource_and_scale(
    timesource: PathLike | Fraction | float | list[int] | VideoMeta | ABCTimestamps | None = None,
    timescale: TimeScale | Fraction | int | None = None,
    rounding_method: RoundingMethod = RoundingMethod.ROUND,
    allow_warn: bool = True,
    fetch_from_setup: bool = False,
    caller: Any | None = None,
) -> ABCTimestamps:
    """
    Instantiates a timestamps class from various inputs.

    :param timesource:          The source of timestamps/timecodes.\n
                                For actual timestamps, this can be a timestamps (v1/v2/v4) file, a muxtools VideoMeta json file, a video file or a list of integers.\n
                                For FPS based timestamps, this can be a Fraction object, a float or even a string representing a fraction.\n
                                Like `'24000/1001'`. (`None` will also fallback to this and print a warning)

    :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                While you can pass an int, the needed type is always a Fraction and will be converted via `Fraction(your_int)`.\n
                                If `None` falls back to a generic Matroska timescale.

    :param rounding_method:     The rounding method used to round/floor the PTS (Presentation Time Stamp).
    :param allow_warn:          Allow this function to print warnings. If you know what you're doing feel free to disable this for your own use.
    :param fetch_from_setup:    Whether or not this function should fallback to the sub defaults from the current Setup.
    :param caller:              Caller used for the logging

    :return:                    Instantiated timestamps object from the videotimestamps library
    """
    if fetch_from_setup:
        if timesource is None and (setup_timesource := get_setup_attr("sub_timesource", None)) is not None:
            if not isinstance(setup_timesource, TimeSourceT):
                raise error("Invalid timesource type in Setup!", caller)
            debug("Using default timesource from setup.", caller)
            timesource = setup_timesource
        if timescale is None and (setup_timescale := get_setup_attr("sub_timescale", None)) is not None:
            if not isinstance(setup_timescale, TimeScaleT):
                raise error("Invalid timescale type in Setup!", caller)
            debug("Using default timescale from setup.", caller)
            timescale = setup_timescale

    def check_timescale(timescale) -> Fraction:
        if not timescale:
            if allow_warn:
                warn("No timescale was given, defaulting to Matroska scaling.", caller)
            timescale = Fraction(1000)
        return Fraction(timescale)

    if timesource is None:
        if allow_warn:
            warn("No timesource was given, generating timestamps for FPS (24000/1001).", caller)
        timescale = check_timescale(timescale)
        return FPSTimestamps(rounding_method, timescale, Fraction(24000, 1001))

    if isinstance(timesource, VideoMeta):
        return ExtrapolatingVideoTimestamps(timesource.pts, timesource.timescale, rounding_method=rounding_method)

    if isinstance(timesource, ABCTimestamps):
        return timesource

    if isinstance(timesource, Path) or isinstance(timesource, str):
        if isinstance(timesource, Path) or os.path.isfile(timesource):
            timesource = ensure_path(timesource, caller)
            parsed = ParsedFile.from_file(timesource, caller, False)

            if parsed and parsed.is_video_file:
                meta = get_timemeta_from_video(timesource, caller=caller)
                return ExtrapolatingVideoTimestamps(meta.pts, meta.timescale, rounding_method=rounding_method)
            else:
                try:
                    meta = VideoMeta.from_json(timesource)
                    return resolve_timesource_and_scale(meta, timescale, rounding_method, allow_warn, fetch_from_setup, caller)
                except:
                    timescale = check_timescale(timescale)
                    return TextFileTimestamps(timesource, timescale, rounding_method=rounding_method)

    elif isinstance(timesource, list) and isinstance(timesource[0], int):
        timescale = check_timescale(timescale)
        return ExtrapolatingVideoTimestamps(timesource, timescale, rounding_method=rounding_method)

    if isinstance(timesource, float) or isinstance(timesource, str) or isinstance(timesource, Fraction):
        fps = Fraction(timesource)
        timescale = check_timescale(timescale)
        return FPSTimestamps(rounding_method, timescale, fps)

    raise crit("Invalid timesource passed!", caller)


def format_timedelta(time: timedelta, precision: int = 3) -> str:
    """
    Formats a timedelta to hh:mm:ss.s[*precision] and pads with 0 if there aren't more numbers to work with.
    Mostly to be used for ogm/xml files.

    :param time:        The timedelta
    :param precision:   3 = milliseconds, 6 = microseconds, 9 = nanoseconds

    :return:            The formatted string
    """
    dec = Decimal(time.total_seconds())
    pattern = "." + "".join(["0"] * (precision - 1)) + "1"
    rounded = float(dec.quantize(Decimal(pattern), rounding=ROUND_HALF_DOWN))
    s = trunc(rounded)
    m = s // 60
    s %= 60
    h = m // 60
    m %= 60
    return f"{h:02d}:{m:02d}:{s:02d}.{str(rounded).split('.')[1].ljust(precision, '0')}"


def timedelta_from_formatted(formatted: str) -> timedelta:
    """
    Parses a string with the format of hh:mm:ss.sss
    Mostly to be used for ogm/xml files.

    :param formatted:       The timestamp string

    :return:                The parsed timedelta
    """
    # 00:05:25.534...
    split = formatted.split(":")
    seconds = Decimal(split[0]) * Decimal(3600)
    seconds = seconds + (Decimal(split[1]) * Decimal(60))
    seconds = seconds + (Decimal(split[2]))
    return timedelta(seconds=seconds.__float__())
