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
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-AAC-sample.mkv"
    f = get_workdir() / "Test.mkv"

    copy(sample_file, f)

    (
        MKVPropEdit(f, chapters="", tags=dict(TVDB="111111", TMDB=""))
        .video_track("Yapper Encode", "de", True, False)
        .audio_track("Yappernese", "und", False, True, tags=dict(ENCODER="not opus", ENCODER_SETTINGS=""))
        .audio_track("English 5.1 (edited)", "en", tags=dict(ENCODER="not qaac"))
        .audio_track("German 2.0 (edited)", "de")
        .run()
    )

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

    side_data = parsed.tracks[0].raw_ffprobe.side_data_list.side_data[0]
    assert side_data.type == "Frame Cropping"
    assert [data for data in side_data.side_datum if data.key == "crop_left"][0].value == "1"
    assert [data for data in side_data.side_datum if data.key == "crop_top"][0].value == "2"
    assert [data for data in side_data.side_datum if data.key == "crop_right"][0].value == "3"
    assert [data for data in side_data.side_datum if data.key == "crop_bottom"][0].value == "4"

    # Crop 2 horizontally, 4 vertically
    MKVPropEdit(f).video_track(crop=(2, 4)).run()
    parsed = ParsedFile.from_file(f)
    assert parsed.tracks[0].raw_ffprobe.side_data_list

    side_data = parsed.tracks[0].raw_ffprobe.side_data_list.side_data[0]
    assert side_data.type == "Frame Cropping"
    assert [data for data in side_data.side_datum if data.key == "crop_left"][0].value == "2"
    assert [data for data in side_data.side_datum if data.key == "crop_right"][0].value == "2"
    assert [data for data in side_data.side_datum if data.key == "crop_top"][0].value == "4"
    assert [data for data in side_data.side_datum if data.key == "crop_bottom"][0].value == "4"

    # Crop 4 on all sides
    MKVPropEdit(f).video_track(crop=4).run()
    parsed = ParsedFile.from_file(f)
    assert parsed.tracks[0].raw_ffprobe.side_data_list

    side_data = parsed.tracks[0].raw_ffprobe.side_data_list.side_data[0]
    assert side_data.type == "Frame Cropping"
    assert len([data for data in side_data.side_datum if data.value == "4"]) == 4

    # Crop removed
    MKVPropEdit(f).video_track(crop=0).run()
    parsed = ParsedFile.from_file(f)
    assert not parsed.tracks[0].raw_ffprobe.side_data_list
