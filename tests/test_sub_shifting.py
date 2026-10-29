from muxtools import SubFile, VideoMeta, Setup, get_workdir, ensure_path, resolve_timesource_and_scale, ABCTimestamps, TimeType, OutOfBoundsMode
from muxtools.subtitle.basesub import _Line
from muxtools.subtitle.subutils import create_document
from ass import Dialogue, Style
from pathlib import Path
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


def _write_sub(path: Path, lines: list[tuple[timedelta, timedelta, str]]) -> Path:
    doc = create_document()
    doc.styles.append(Style(name="Default"))
    doc.events.extend(Dialogue(start=start, end=end, style="Default", text=text) for start, end, text in lines)
    with open(path, "w", encoding="utf_8_sig") as writer:
        doc.dump_file(writer)
    return path


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
    path = _write_sub(
        get_workdir() / "shift_zero.ass",
        [
            (timedelta(minutes=7, seconds=18, milliseconds=420), timedelta(minutes=7, seconds=18, milliseconds=460), "one frame"),
            (timedelta(minutes=7, seconds=18, milliseconds=460), timedelta(minutes=7, seconds=18, milliseconds=520), "next"),
            (timedelta(minutes=7, seconds=18, milliseconds=300), timedelta(minutes=7, seconds=18, milliseconds=600), "partial"),
            (timedelta(milliseconds=200), timedelta(milliseconds=420), "gone"),
            (timedelta(0), timedelta(0), "empty"),
        ],
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


def _shift_bounded(frame_ranges: list[tuple[int, int]], frames: int, **kwargs) -> list[tuple[int, int]]:
    """
    Writes one line per (start, end) frame range, shifts the file and returns the resulting (start, end) frames.
    """
    from fractions import Fraction

    resolved = resolve_timesource_and_scale(Fraction(24000, 1001))
    lines = [
        (
            timedelta(milliseconds=resolved.frame_to_time(start, TimeType.START, 2, True) * 10),
            timedelta(milliseconds=resolved.frame_to_time(end, TimeType.END, 2, True) * 10),
            f"line {i}",
        )
        for i, (start, end) in enumerate(frame_ranges)
    ]
    path = _write_sub(get_workdir() / "shift_bounds.ass", lines)

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


def test_shift_keeps_frame_with_float_imprecise_time() -> None:
    """
    256.09s turns into 256089ms when going through total_seconds(), which is on the previous frame at 23.976.
    Shifting by 0 frames must keep the line on the same frames.
    """
    from fractions import Fraction

    resolved = resolve_timesource_and_scale(Fraction(24000, 1001))
    path = _write_sub(get_workdir() / "shift_float.ass", [(timedelta(milliseconds=256090), timedelta(milliseconds=256340), "on grid")])
    sub = SubFile(path)

    sub.shift(0, resolved)
    line = cast(_Line, sub._read_doc().events[0])
    # Frame n is shown at round(n * 1001 / 24) ms: 6140 at 256089, 6141 at 256131, 6146 at 256339 and 6147 at 256381.
    # A line starts on the first frame shown at or after its start and ends after the last frame shown before its end.
    # So the line is on frames 6141 to 6146 and has to stay in those frame windows.
    assert timedelta(milliseconds=256089) < line.start <= timedelta(milliseconds=256131), _line_yap(line)
    assert timedelta(milliseconds=256339) < line.end <= timedelta(milliseconds=256381), _line_yap(line)
