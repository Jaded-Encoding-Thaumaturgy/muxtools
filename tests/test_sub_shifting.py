from muxtools import SubFile, VideoMeta, Setup, get_workdir, ensure_path, resolve_timesource_and_scale, ABCTimestamps, TimeType, OutOfBoundsMode
from muxtools.subtitle.basesub import _Line
from typing import cast
from shutil import rmtree
from datetime import timedelta
from time import sleep
import pytest

test_dir = ensure_path(__file__, None).parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def _timedelta_to_frame(delta: timedelta, ts: ABCTimestamps, type: TimeType) -> int:
    return ts.time_to_frame(int(delta.total_seconds() * 1000), type, 3)


def _line_yap(line: _Line | None) -> str:
    if not line:
        return ""
    print(s := f"Line failed: {line.text} | {line.start} -> {line.end}")
    return s


def _compare_times(delta: timedelta, other: timedelta, ts: ABCTimestamps, type: TimeType, line: _Line | None = None):
    tolerance = timedelta(microseconds=10000)  # One centisecond; both aegisub and muxtools will center the time so this should never be an issue
    assert _timedelta_to_frame(delta, ts, type) == _timedelta_to_frame(other, ts, type), _line_yap(line)  # Frame matches
    assert (other - delta) <= tolerance, _line_yap(line)  # Difference is within tolerance


def test_shift_by_24() -> None:
    """
    Simple test for shifting subs by 24 frames.

    The "output" file to compare with was created by opening the "input" file in aegisub
    with the same video that was used to generate the json VideoMeta.
    """
    meta = VideoMeta.from_json(test_dir / "test-data" / "input" / "vigilantes_s01e01.json")
    resolved = resolve_timesource_and_scale(meta)

    sub = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    sub.shift(24, resolved)
    sub_doc = sub._read_doc()

    sub_correct = SubFile(test_dir / "test-data" / "output" / "vigilantes_s01e01_en_shifted.ass")
    sub_correct_doc = sub_correct._read_doc()

    for presumed, correct in zip(sub_doc.events, sub_correct_doc.events):
        presumed = cast(_Line, presumed)
        correct = cast(_Line, correct)

        _compare_times(presumed.start, correct.start, resolved, TimeType.START)
        _compare_times(presumed.end, correct.end, resolved, TimeType.END)


def test_shift_by_7200() -> None:
    """
    Simple test for shifting subs by 7200 frames.

    Mostly to check if more extrapolated lines match up with aegisub.
    """
    meta = VideoMeta.from_json(test_dir / "test-data" / "input" / "vigilantes_s01e01.json")
    resolved = resolve_timesource_and_scale(meta)

    sub = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    sub.shift(7200, resolved)
    sub_doc = sub._read_doc()

    sub_correct = SubFile(test_dir / "test-data" / "output" / "vigilantes_s01e01_en_shifted_7200.ass")
    sub_correct_doc = sub_correct._read_doc()

    for presumed, correct in zip(sub_doc.events, sub_correct_doc.events):
        presumed = cast(_Line, presumed)
        correct = cast(_Line, correct)

        _compare_times(presumed.start, correct.start, resolved, TimeType.START)
        _compare_times(presumed.end, correct.end, resolved, TimeType.END)


def test_shift_to_frame_zero() -> None:
    """
    Shifting lines to or past frame 0 should keep visible frames visible and hide everything else.
    """
    from fractions import Fraction

    resolved = resolve_timesource_and_scale(Fraction(24000, 1001))
    path = get_workdir() / "shift_zero.ass"
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:07:18.42,0:07:18.46,Default,,0,0,0,,one frame\n"
        "Dialogue: 0,0:07:18.46,0:07:18.52,Default,,0,0,0,,next\n"
        "Dialogue: 0,0:07:18.30,0:07:18.60,Default,,0,0,0,,partial\n"
        "Dialogue: 0,0:00:00.20,0:00:00.42,Default,,0,0,0,,gone\n"
        "Dialogue: 0,0:00:00.00,0:00:00.00,Default,,0,0,0,,empty\n",
        encoding="utf-8",
    )
    first = _timedelta_to_frame(timedelta(minutes=7, seconds=18, milliseconds=420), resolved, TimeType.START)

    sub = SubFile(path)
    sub.shift(-first, resolved, oob_mode=OutOfBoundsMode.MAX_TO_ZERO)
    one, nxt, partial, gone, empty = (cast(_Line, line) for line in sub._read_doc().events)

    # one frame line lands on frame 0 and stays one frame long
    assert _timedelta_to_frame(one.start, resolved, TimeType.START) == 0, _line_yap(one)
    assert _timedelta_to_frame(one.end, resolved, TimeType.END) == 0, _line_yap(one)
    assert one.end > one.start, _line_yap(one)
    assert one.end == nxt.start, _line_yap(one)

    # frames 10509-10515 -> -3 to 3, start clamped to 0
    assert _timedelta_to_frame(partial.start, resolved, TimeType.START) == 0, _line_yap(partial)
    assert _timedelta_to_frame(partial.end, resolved, TimeType.END) == 3, _line_yap(partial)
    assert partial.end > partial.start, _line_yap(partial)

    # fully before 0 after the shift, should be hidden
    assert gone.end == gone.start, _line_yap(gone)
    assert empty.end == empty.start, _line_yap(empty)


def _cs_to_ass(cs: int) -> str:
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def _shift_bounded(frame_ranges: list[tuple[int, int]], frames: int, **kwargs) -> list[tuple[int, int]]:
    """
    Writes one line per (start, end) frame range, shifts the file and returns the resulting (start, end) frames.
    """
    from fractions import Fraction

    resolved = resolve_timesource_and_scale(Fraction(24000, 1001))
    path = get_workdir() / "shift_bounds.ass"
    events = "".join(
        f"Dialogue: 0,{_cs_to_ass(resolved.frame_to_time(start, TimeType.START, 2, True))},"
        f"{_cs_to_ass(resolved.frame_to_time(end, TimeType.END, 2, True))},Default,,0,0,0,,line {i}\n"
        for i, (start, end) in enumerate(frame_ranges)
    )
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + events,
        encoding="utf-8",
    )

    sub = SubFile(path)
    sub.shift(frames, resolved, **kwargs)
    lines = (cast(_Line, line) for line in sub._read_doc().events)
    return [(_timedelta_to_frame(line.start, resolved, TimeType.START), _timedelta_to_frame(line.end, resolved, TimeType.END)) for line in lines]


def test_shift_before() -> None:
    """
    With `before`, only timestamps at or before that frame are shifted.
    """
    result = _shift_bounded([(50, 60), (100, 110), (150, 160)], 10, before=100)
    # (100, 110) has its start on the boundary (shifted) and its end after it (untouched)
    assert result == [(60, 70), (110, 110), (150, 160)], result


def test_shift_after() -> None:
    """
    With `after`, only timestamps at or after that frame are shifted.
    """
    result = _shift_bounded([(50, 60), (90, 100), (150, 160)], 10, after=100)
    # (90, 100) has its start before the boundary (untouched) and its end on it (shifted)
    assert result == [(50, 60), (90, 110), (160, 170)], result


def test_shift_before_and_after() -> None:
    """
    With both, timestamps outside of the (before, after) gap are shifted and the ones inside it are left alone.
    """
    result = _shift_bounded([(10, 20), (110, 120), (210, 220)], 5, before=50, after=200)
    assert result == [(15, 25), (110, 120), (215, 225)], result


def test_shift_without_bounds_shifts_everything() -> None:
    result = _shift_bounded([(50, 60), (150, 160)], 10)
    assert result == [(60, 70), (160, 170)], result


def test_shift_bounds_with_negative_offset_and_oob() -> None:
    """
    Out of bounds handling still applies to lines that are partially shifted.
    """
    result = _shift_bounded([(2, 10), (200, 210)], -5, before=100, oob_mode=OutOfBoundsMode.MAX_TO_ZERO)
    assert result == [(0, 5), (200, 210)], result
