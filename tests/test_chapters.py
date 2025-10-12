from muxtools import Setup, get_workdir, ensure_path, Chapters
from shutil import rmtree
from time import sleep
import pytest

test_dir = ensure_path(__file__, None).parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_chapters_from_mkv():
    f = test_dir / "test-data" / "sample-files" / "H265-Opus-EAC3-sample.mkv"
    ch = Chapters.from_mkv(f)

    assert ch.chapters


def test_chapters_from_sub():
    f = test_dir / "test-data" / "input" / "atri-subkt" / "ATRI 03 - Dialogue.ass"
    ch = Chapters.from_sub(f, use_actor_field=True)

    assert ch.chapters


def test_chapters_from_ogm():
    f = test_dir / "test-data" / "input" / "atri-subkt" / "ATRI 03 - Dialogue.ass"
    ch = Chapters.from_sub(f, use_actor_field=True)

    assert ch.chapters

    ogm = ch.to_file(minus_one_ms_hack=False)
    ch_ogm = Chapters(ogm)

    assert ch.chapters == ch_ogm.chapters
