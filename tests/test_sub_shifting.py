from muxtools import SubFile, VideoMeta, Setup, get_workdir, ensure_path, resolve_timesource_and_scale, ABCTimestamps, TimeType
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
