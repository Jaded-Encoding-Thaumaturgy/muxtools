from muxtools import ensure_path, MKVPropEdit, Setup, get_workdir, Chapters, ParsedFile
from time import sleep
from shutil import rmtree, copy
import pytest

test_dir = ensure_path(__file__, None).parent.parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.5)
    rmtree(get_workdir())


def test_mkvpropedit():
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-AAC-sample.mkv"
    f = get_workdir() / "Test.mkv"

    copy(sample_file, f)

    (
        MKVPropEdit(f, chapters="", tags=dict(TVDB="111111"))
        .video_track("Yapper Encode", "de", True, False)
        .audio_track("Yappernese", "und", False, True, tags=dict(ENCODER="not opus"))
        .audio_track("English 5.1 (edited)", "en")
        .audio_track("German 2.0 (edited)", "de")
        .run()
    )

    no_chapters = False
    try:
        Chapters.from_mkv(f)
    except:
        no_chapters = True

    assert no_chapters
    assert Chapters.from_mkv(sample_file, _print=False)

    original = ParsedFile.from_file(sample_file)
    new = ParsedFile.from_file(f)

    assert "TMDB" in original.container_info.tags
    assert "TMDB" not in new.container_info.tags
    assert original.tracks[0].title != new.tracks[0].title
    assert original.tracks[0].language != new.tracks[0].language

    assert original.tracks[1].title != new.tracks[1].title
    assert original.tracks[1].language != new.tracks[1].language
    assert "ENCODER_SETTINGS" not in new.tracks[1].other_tags and "ENCODER_SETTINGS" in original.tracks[1].other_tags
    assert new.tracks[1].other_tags.get("ENCODER") != original.tracks[1].other_tags.get("ENCODER")

    assert original.tracks[2].title != new.tracks[2].title
    assert original.tracks[3].title != new.tracks[3].title
