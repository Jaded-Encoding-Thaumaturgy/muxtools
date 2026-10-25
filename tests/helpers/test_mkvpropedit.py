from muxtools import ensure_path, MKVPropEdit, Setup, get_workdir, Chapters, ParsedFile
from time import sleep
from shutil import rmtree, copy
import pytest

test_dir = ensure_path(__file__, None).parent.parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_mkvpropedit():
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-AAC-sample-18F78726.mkv"
    f = get_workdir() / sample_file.name

    copy(sample_file, f)

    f, _ = (
        MKVPropEdit(f, chapters="", tags=dict(TVDB="111111", TMDB=""))
        .video_track("Yapper Encode", "de", True, False)
        .audio_track("Yappernese", "und", False, True, tags=dict(ENCODER="not opus", ENCODER_SETTINGS=""))
        .audio_track("English 5.1 (edited)", "en", tags=dict(ENCODER="not qaac"))
        .audio_track("German 2.0 (edited)", "de")
        .run()
    )

    assert f.name != sample_file.name
    assert "3FB7881D" in f.name

    with pytest.raises(Exception):
        Chapters.from_mkv(f)

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

    assert new.tracks[2].other_tags.get("ENCODER") != original.tracks[2].other_tags.get("ENCODER")
    assert original.tracks[2].title != new.tracks[2].title
    assert original.tracks[3].title != new.tracks[3].title


def test_mkvpropedit_crops():
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-AAC-sample.mkv"
    f = get_workdir() / "Test.mkv"

    copy(sample_file, f)

    MKVPropEdit(f).video_track(crop=(1, 2, 3, 4)).run()
    parsed = ParsedFile.from_file(f)
    assert parsed.tracks[0].raw_ffprobe.side_data_list
    side_data = parsed.tracks[0].raw_ffprobe.side_data_list[0]
    assert side_data["side_data_type"] == "Frame Cropping"
    assert side_data["crop_left"] == 1
    assert side_data["crop_top"] == 2
    assert side_data["crop_right"] == 3
    assert side_data["crop_bottom"] == 4

    # Crop 2 horizontally, 4 vertically
    MKVPropEdit(f).video_track(crop=(2, 4)).run()
    parsed = ParsedFile.from_file(f)
    assert parsed.tracks[0].raw_ffprobe.side_data_list
    side_data = parsed.tracks[0].raw_ffprobe.side_data_list[0]
    assert side_data["side_data_type"] == "Frame Cropping"
    assert side_data["crop_left"] == 2
    assert side_data["crop_right"] == 2
    assert side_data["crop_top"] == 4
    assert side_data["crop_bottom"] == 4

    # Crop 4 on all sides
    MKVPropEdit(f).video_track(crop=4).run()
    parsed = ParsedFile.from_file(f)
    assert parsed.tracks[0].raw_ffprobe.side_data_list
    side_data = parsed.tracks[0].raw_ffprobe.side_data_list[0]
    assert side_data["side_data_type"] == "Frame Cropping"
    assert all(side_data[key] == 4 for key in ("crop_left", "crop_top", "crop_right", "crop_bottom"))

    # Crop removed
    MKVPropEdit(f).video_track(crop=0).run()
    parsed = ParsedFile.from_file(f)
    assert not parsed.tracks[0].raw_ffprobe.side_data_list


def test_mkvpropedit_with_tokens():
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-EAC3-sample.mkv"
    f = get_workdir() / "Test.mkv"

    copy(sample_file, f)

    (
        MKVPropEdit(f)
        .video_track("Test $format$ $bits$-bit", "de", True, False)
        .audio_track("$language$ $format$ $ch$", "und")
        .audio_track("$language$ $format$ $ch$")
        .audio_track("$language$ $format$ $ch$")
        .run()
    )

    original = ParsedFile.from_file(sample_file)
    new = ParsedFile.from_file(f)

    assert original.tracks[0].title != new.tracks[0].title
    assert original.tracks[0].language != new.tracks[0].language

    assert new.tracks[0].title == "Test HEVC 10-bit"
    assert new.tracks[1].title == "Unknown language Opus 2.0"
    assert new.tracks[2].title == "English EAC-3 2.0"
    assert new.tracks[3].title == "German EAC-3 2.0"
