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
