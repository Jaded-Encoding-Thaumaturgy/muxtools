from math import trunc
from decimal import ROUND_HALF_DOWN, Decimal
from fractions import Fraction
from datetime import timedelta

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


def timedelta_to_frame(time: timedelta, fps: Fraction = Fraction(24000, 1001)) -> int:
    """
    Converts a timedelta to a frame number.

    :param time:    The timedelta
    :param fps:     A Fraction containing fps_num and fps_den

    :return:        The resulting frame number
    """
    ms = Decimal(time.total_seconds()) * 1000
    fps_dec = _fraction_to_decimal(fps)

    upper_bound = (ms + Decimal(0.5)) * fps_dec / 1000
    trunc_frame = int(upper_bound)

    if upper_bound == trunc_frame:
        return trunc_frame - 1

    return trunc_frame


def frame_to_timedelta(f: int, fps: Fraction = Fraction(24000, 1001), compensate: bool = False) -> timedelta:
    """
    Converts a frame number to a timedelta.
    Mostly used in the conversion for manually defined chapters.

    :param f:           The frame number
    :param fps:         A Fraction containing fps_num and fps_den
    :param compensate:  Whether or not to place the the timestamp in the middle of said frame
                        Useful for subtitles, not so much for audio where you'd wanna be accurate

    :return:            The resulting timedelta
    """
    if not f:
        return timedelta(seconds=0)
    fps_dec = _fraction_to_decimal(fps)
    seconds = Decimal(f) / fps_dec
    if not compensate:
        return timedelta(seconds=float(seconds))
    else:
        t1 = timedelta(seconds=float(seconds))
        t2 = timedelta(seconds=float(Decimal(f + 1) / fps_dec))
        return t1 + (t2 - t1) / 2


def frame_to_ms(f: int, fps: Fraction = Fraction(24000, 1001), compensate: bool = False) -> timedelta:
    """
    Converts a frame number to it's ms value.

    :param f:           The frame number
    :param fps:         A Fraction containing fps_num and fps_den
    :param compensate:  Whether or not to place the the timestamp in the middle of said frame
                        Useful for subtitles, not so much for audio where you'd wanna be accurate

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
