from muxtools import SubFile, VideoMeta, Setup, get_workdir, ensure_path
from muxtools.subtitle.basesub import _Line
from typing import cast
from shutil import rmtree


def test_shift_by_24() -> None:
    """
    Simple test for shifting subs by 24 frames.

    The "output" file to compare with was created by opening the "input" file in aegisub
    with the same video that was used to generate the json VideoMeta.
    """
    Setup("Test", None)

    cwd = ensure_path(__file__, test_shift_by_24).parent

    ts = VideoMeta.from_json(cwd / "test-data" / "input" / "vigilantes_s01e01.json")

    sub = SubFile(cwd / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    sub.shift(24, ts)
    sub_doc = sub._read_doc()

    sub_correct = SubFile(cwd / "test-data" / "output" / "vigilantes_s01e01_en_shifted.ass")
    sub_correct_doc = sub_correct._read_doc()

    for presumed, correct in zip(sub_doc.events, sub_correct_doc.events):
        presumed = cast(_Line, presumed)
        correct = cast(_Line, correct)

        assert presumed.start == correct.start
        assert presumed.end == correct.end

    rmtree(get_workdir())
