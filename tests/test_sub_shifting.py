from muxtools import SubFile, VideoMeta, Setup, get_workdir, ensure_path
from muxtools.subtitle.basesub import _Line
from typing import cast
from shutil import rmtree
from time import sleep
import pytest

test_dir = ensure_path(__file__, None).parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.5)  # Just in case there's still a lock on some file lol
    rmtree(get_workdir())


def test_shift_by_24() -> None:
    """
    Simple test for shifting subs by 24 frames.

    The "output" file to compare with was created by opening the "input" file in aegisub
    with the same video that was used to generate the json VideoMeta.
    """
    ts = VideoMeta.from_json(test_dir / "test-data" / "input" / "vigilantes_s01e01.json")

    sub = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    sub.shift(24, ts)
    sub_doc = sub._read_doc()

    sub_correct = SubFile(test_dir / "test-data" / "output" / "vigilantes_s01e01_en_shifted.ass")
    sub_correct_doc = sub_correct._read_doc()

    for presumed, correct in zip(sub_doc.events, sub_correct_doc.events):
        presumed = cast(_Line, presumed)
        correct = cast(_Line, correct)

        assert presumed.start == correct.start
        assert presumed.end == correct.end
