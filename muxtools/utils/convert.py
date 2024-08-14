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
    "ms_to_frame",
    "frame_to_ms",
    "format_timedelta",
    "timedelta_from_formatted",
]


def mpls_timestamp_to_timedelta(timestamp: int) -> timedelta:
    """
    Converts a mpls timestamp (from BDMV Playlist files) to a timedelta.

    :param timestamp:       The mpls timestamp

    :return:                The resulting timedelta
    """
    seconds = Decimal(timestamp) / Decimal(45000)
    return timedelta(seconds=float(seconds))


def ms_to_frame(
    ms: int, time_type: TimeType, time_scale: Fraction, fps: Fraction | PathLike = Fraction(24000, 1001), rounding_method: RoundingMethod = RoundingMethod.ROUND
) -> int:
    """
    Converts a timedelta to a frame number.

    :param ms:                  The time in millisecond.
    :param time_type:           The time type.
    :param time_scale:          The time scale.
    :param fps:                 A Fraction containing fps_num and fps_den. Also accepts a timecode (v2, v4) file.
    :param rounding_method:     If you want to be compatible with mkv, use RoundingMethod.ROUND else RoundingMethod.FLOOR.
                                For more information, see the documentation of [timestamps](https://github.com/moi15moi/VideoTimestamps/blob/578373a5b83402d849d0e83518da7549edf8e03d/video_timestamps/abc_timestamps.py#L13-L26)
    :return:                    The resulting frame number.
    """

    if isinstance(fps, Fraction):
        timestamps = FPSTimestamps(rounding_method, time_scale, fps)
    else:
        timestamps_file = ensure_path_exists(fps, ms_to_frame)
        timestamps = TextFileTimestamps(timestamps_file, time_scale, rounding_method)

    frame = timestamps.time_to_frame(ms, time_type, 3)

    return frame


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
