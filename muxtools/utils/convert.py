from math import trunc
from decimal import Decimal, ROUND_HALF_DOWN
from fractions import Fraction
from datetime import timedelta
from video_timestamps import FPSTimestamps, RoundingMethod, TextFileTimestamps, TimeType

from ..utils.types import PathLike
from ..utils.files import ensure_path_exists
from ..utils.log import error

__all__: list[str] = [
    "mpls_timestamp_to_timedelta",
    "timedelta_to_frame",
    "frame_to_ms",
    "format_timedelta",
    "timedelta_from_formatted",
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


def _timedelta_from_timecodes(timecodes: PathLike, frame: int) -> timedelta:
    timecode_file = ensure_path_exists(timecodes, _timedelta_from_timecodes)
    parsed = [float(x) / 1000 for x in open(timecode_file, "r").read().splitlines()[1:]]
    if len(parsed) <= frame:
        raise error(f"Frame {frame} is out of range for the given timecode file!", _timedelta_from_timecodes)

    target = timedelta(seconds=parsed[frame])
    return target


def _frame_from_timecodes(timecodes: PathLike, time: timedelta) -> int:
    timecode_file = ensure_path_exists(timecodes, _frame_from_timecodes)
    # Subtract 0.5 from timecodes to ensure correct behavior even with small rounding errors
    # (A timedelta of 42ms should belong to frame [42, 83) with a timecode list [0, 42, 83, ...])
    parsed = [(float(x) - 0.5) / 1000 for x in open(timecode_file, "r").read().splitlines()[1:]]

    return len([t for t in parsed if t < time.total_seconds()]) - 1


def timedelta_to_frame(
    time: timedelta, fps: Fraction | PathLike = Fraction(24000, 1001), exclude_boundary: bool = False, allow_rounding: bool = True
) -> int:
    """
    Converts a timedelta to a frame number.

    :param time:                The timedelta
    :param fps:                 A Fraction containing fps_num and fps_den. Also accepts a timecode (v2) file.

    :param exclude_boundary:    Associate frame boundaries with the previous frame rather than the current one.
                                Use this option when dealing with subtitle start/end times.

    :param allow_rounding:      Use the next int if the difference to the next frame is smaller than 0.01.
                                This should *probably* not be used for subtitles. We are not sure.

    :return:                    The resulting frame number
    """
    if exclude_boundary:
        return timedelta_to_frame(time - timedelta(milliseconds=1), fps, allow_rounding=False)

    if not isinstance(fps, Fraction):
        return _frame_from_timecodes(fps, time)

    ms = int(Decimal(time.total_seconds()).__round__(3) * 1000)
    frame = ms * fps / 1000
    frame_dec = Decimal(frame.numerator) / Decimal(frame.denominator)

    # Return next int if difference is less than 0.03
    if allow_rounding and abs(frame_dec.__round__(3) - frame_dec.__ceil__()) < 0.03:
        return frame_dec.__ceil__()

    return int(frame)


def frame_to_ms(f: int, time_type: TimeType, time_scale: Fraction, fps: Fraction | PathLike = Fraction(24000, 1001),
        rounding: bool = True, rounding_method: RoundingMethod = RoundingMethod.ROUND
    ) -> int:
    """
    Converts a frame number to a timedelta.
    Mostly used in the conversion for manually defined chapters.

    :param f:                   The frame number.
    :param time_type:           The time type.
    :param time_scale:          The time scale.
    :param fps:                 A Fraction containing fps_num and fps_den. Also accepts a timecode (v2, v4) file.
    :param rounding:            Round compensated value to centi seconds if True.
    :param rounding_method:     If you want to be compatible with mkv, use RoundingMethod.ROUND else RoundingMethod.FLOOR.
                                For more information, see the documentation of [timestamps](https://github.com/moi15moi/VideoTimestamps/blob/578373a5b83402d849d0e83518da7549edf8e03d/video_timestamps/abc_timestamps.py#L13-L26)
    :return:                    The resulting time in milliseconds or centiseconds.
    """
    if isinstance(fps, Fraction):
        timestamps = FPSTimestamps(rounding_method, time_scale, fps)
    else:
        timestamps_file = ensure_path_exists(fps, frame_to_ms)
        timestamps = TextFileTimestamps(timestamps_file, time_scale, rounding_method)

    if rounding:
        return timestamps.frame_to_time(f, time_type, 2)
    else:
        return timestamps.frame_to_time(f, time_type, 3)


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
    split = formatted.split(":")
    seconds = Decimal(split[0]) * Decimal(3600)
    seconds = seconds + (Decimal(split[1]) * Decimal(60))
    seconds = seconds + (Decimal(split[2]))
    return timedelta(seconds=seconds.__float__())
