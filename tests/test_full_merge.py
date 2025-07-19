from muxtools import SubFile, VideoMeta, Setup, get_workdir, resolve_timesource_and_scale, TimeType, ShiftMode
from muxtools.subtitle.basesub import _Line
from muxtools.subtitle.sub import LINES
from typing import cast
from shutil import rmtree
from time import sleep
import re
import pytest

from test_sub_shifting import test_dir, _compare_times


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def _sort_lines_by_start(lines: LINES) -> LINES:
    return sorted(lines, key=lambda x: x.start)


def _remove_folds_and_empty_lines(lines: LINES) -> LINES:
    """
    Something something "subkt actually handles the ASS lines "properly" in that an initial `{=X=YY=NNN}` style block is read as containing extradata IDs and excluded from line.text"
    """
    new_lines = []
    for line in lines:
        line.text = re.sub(r"{(?:=\d+)+}", "", line.text)
        if line.text.strip() == "" and line.effect.strip() == "" and line.name.strip() == "":
            continue
        new_lines.append(line)
    return new_lines


def test_full_merge():
    atri_dir = test_dir / "test-data" / "input" / "atri-subkt"
    meta = VideoMeta.from_json(atri_dir / "03_meta.json")
    resolved = resolve_timesource_and_scale(meta)

    # Merge static files
    sub = SubFile(atri_dir / "ATRI 03 - Dialogue.ass").merge(atri_dir / "ATRI 03 - TS (Nyarthur).ass").merge(atri_dir / "warning.ass")

    # Merge songs
    sub.merge(atri_dir / "ATRI - NCOP1.ass", "opsync", "sync", resolved, shift_mode=ShiftMode.TIME)
    sub.merge(atri_dir / "ATRI - NCED1.ass", "edsync", "sync", resolved, shift_mode=ShiftMode.TIME)

    sub.autoswapper().clean_comments().clean_garbage().clean_extradata()
    sub.manipulate_lines(_sort_lines_by_start)
    sub.manipulate_lines(_remove_folds_and_empty_lines)
    sub_doc = sub._read_doc()

    sub_correct = SubFile(test_dir / "test-data" / "output" / "atri_s01e03_from_release.ass")
    sub_correct.clean_comments().clean_garbage().clean_extradata()
    sub_correct.manipulate_lines(_sort_lines_by_start)
    sub_correct_doc = sub_correct._read_doc()

    assert len(sub_doc.events) == len(sub_correct_doc.events)

    for presumed, correct in zip(sub_doc.events, sub_correct_doc.events):
        presumed = cast(_Line, presumed)
        correct = cast(_Line, correct)

        _compare_times(presumed.start, correct.start, resolved, TimeType.START, presumed)
        _compare_times(presumed.end, correct.end, resolved, TimeType.END, correct)
