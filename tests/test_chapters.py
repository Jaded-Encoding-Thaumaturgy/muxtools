from muxtools import Setup, get_workdir, ensure_path, Chapters, get_executable, run_commandline
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


def test_unicode_chapters_with_legacy_charset():
    ch = Chapters([(0, "Prólogo"), (24, "日本語")], _print=False)
    ogm = ch.to_file(minus_one_ms_hack=False)
    assert Chapters(ogm, _print=False).chapters == ch.chapters

    source = test_dir / "test-data" / "sample-files" / "H264-MP3-Vorbis-sample.mkv"
    out = get_workdir() / "unicode-chapters.mkv"
    # A BOM must override the legacy charset even on systems that default to UTF-8.
    args = [get_executable("mkvmerge"), "-o", str(out), "--no-chapters", str(source), "--chapter-charset", "Windows-1252", "--chapters", str(ogm)]
    assert run_commandline(args, mkvmerge=True) <= 1

    extracted = get_workdir() / "extracted-chapters.txt"
    assert run_commandline([get_executable("mkvextract"), str(out), "chapters", "-s", str(extracted)]) == 0
    assert Chapters(extracted, _print=False).chapters == ch.chapters
