import os
from math import trunc
from decimal import ROUND_HALF_DOWN, Decimal
from fractions import Fraction
from datetime import timedelta
from typing import Any

from ..utils.types import PathLike
from ..utils.files import ensure_path_exists
from ..utils.log import error

__all__: list[str] = [
    "mpls_timestamp_to_timedelta",
    "timedelta_to_frame",
    "frame_to_timedelta",
    "format_timedelta",
    "timedelta_from_formatted",
    "frame_to_ms",
]


def _fraction_to_decimal(f: Fraction) -> Decimal:
    return Decimal(f.numerator) / Decimal(f.denominator)


def mpls_timestamp_to_timedelta(timestamp: int) -> timedelta:
    """
    Converts a mpls timestamp (from BDMV Playlist files) to a timedelta.

    :param timestamp:       The mpls timestamp

    :return:                The resulting timedelta
    """
    seconds = Decimal(timestamp) / Decimal(45000)
    return timedelta(seconds=float(seconds))


def _timedelta_from_timecodes(timecodes: PathLike, frame: int, compensate: bool = False, rounding: bool = False) -> timedelta:
    timecode_file = ensure_path_exists(timecodes, _timedelta_from_timecodes)
    parsed = [float(x) / 1000 for x in open(timecode_file, "r").read().splitlines()[1:]]
    if len(parsed) <= frame:
        raise error(f"Frame {frame} is out of range for the given timecode file!", _timedelta_from_timecodes)

    target = timedelta(seconds=parsed[frame])
    if compensate and len(parsed) - 1 >= frame + 1:
        next = timedelta(seconds=parsed[frame + 1])
        target = target + (next - target) / 2
        if rounding:
            return timedelta(seconds=round(target.total_seconds(), 2))
    return target


def _frame_from_timecodes(timecodes: PathLike, time: timedelta) -> int:
    timecode_file = ensure_path_exists(timecodes, _frame_from_timecodes)
    parsed = [float(x) / 1000 for x in open(timecode_file, "r").read().splitlines()[1:]]

    nearest_frame = min(parsed, key=lambda val: abs(val - time.total_seconds()))
    return parsed.index(nearest_frame)


def timedelta_to_frame(time: timedelta, fps: Fraction | PathLike = Fraction(24000, 1001)) -> int:
    """
    Converts a timedelta to a frame number.

    :param time:    The timedelta
    :param fps:     A Fraction containing fps_num and fps_den. Also accepts a timecode (v2) file.

    :return:        The resulting frame number
    """
    if not isinstance(fps, Fraction):
        return _frame_from_timecodes(fps, time)
    ms = Decimal(time.total_seconds()) * 1000
    fps_dec = _fraction_to_decimal(fps)

    upper_bound = (ms + Decimal(0.5)) * fps_dec / 1000
    trunc_frame = int(upper_bound)

    if upper_bound == trunc_frame:
        return trunc_frame - 1

    return trunc_frame


def frame_to_timedelta(f: int, fps: Fraction | PathLike = Fraction(24000, 1001), compensate: bool = False, rounding: bool = True) -> timedelta:
    """
    Converts a frame number to a timedelta.
    Mostly used in the conversion for manually defined chapters.

    :param f:           The frame number
    :param fps:         A Fraction containing fps_num and fps_den. Also accepts a timecode (v2) file.
    :param compensate:  Whether to place the timestamp in the middle of said frame
                        Useful for subtitles, not so much for audio where you'd want to be accurate
    :param rounding:    Round compensated value to centi seconds if True
    :return:            The resulting timedelta
    """
    if not f or f < 0:
        return timedelta(seconds=0)

    if not isinstance(fps, Fraction):
        return _timedelta_from_timecodes(fps, f, compensate, rounding)

    fps_dec = _fraction_to_decimal(fps)
    seconds = Decimal(f) / fps_dec
    if not compensate:
        return timedelta(seconds=float(seconds))
    else:
        t1 = timedelta(seconds=float(seconds))
        t2 = timedelta(seconds=float(Decimal(f + 1) / fps_dec))
        result = t1 + (t2 - t1) / 2
        if not rounding:
            return result
        rounded = round(result.total_seconds(), 2)
        return timedelta(seconds=rounded)


def frame_to_ms(f: int, fps: Fraction | PathLike = Fraction(24000, 1001), compensate: bool = False) -> float:
    """
    Converts a frame number to it's ms value.

    :param f:           The frame number
    :param fps:         A Fraction containing fps_num and fps_den. Also accepts a timecode (v2) file.
    :param compensate:  Whether to place the timestamp in the middle of said frame
                        Useful for subtitles, not so much for audio where you'd want to be accurate

    :return:            The resulting ms
    """
    td = frame_to_timedelta(f, fps, compensate)
    return td.total_seconds() * 1000


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
    return f'{h:02d}:{m:02d}:{s:02d}.{str(rounded).split(".")[1].ljust(precision, "0")}'


def timedelta_from_formatted(formatted: str) -> timedelta:
    """
    Parses a string with the format of hh:mm:ss.sss
    Mostly to be used for ogm/xml files.

    :param formatted:       The timestamp string

    :return:                The parsed timedelta
    """
    # 00:05:25.534...
    seconds: float = 0.0
    split = formatted.split(":")
    seconds += float(split[0]) * 3600
    seconds += float(split[1]) * 60
    seconds += float(split[2])
    return timedelta(seconds=seconds)
