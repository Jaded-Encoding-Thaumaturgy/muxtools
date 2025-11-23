from muxtools import ensure_path, TrackType
from muxtools.utils import AudioFormat, ParsedFile
import pytest


@pytest.fixture
def parsed_file():
    sample_file = ensure_path(__file__, None).parent.parent / "test-data" / "sample-files" / "H265-Opus-AAC-sample.mkv"
    parsed = ParsedFile.from_file(sample_file)
    assert parsed
    return parsed


def test_find_by_name(parsed_file):
    found = parsed_file.find_tracks("English.*", type=TrackType.AUDIO)

    assert len(found) == 1
    assert found[0].get_audio_format() == AudioFormat.AAC


def test_find_by_type(parsed_file):
    found = parsed_file.find_tracks(type=TrackType.AUDIO)

    assert len(found) == 3
    assert found[0].get_audio_format() == AudioFormat.OPUS
    assert found[1].get_audio_format() == AudioFormat.AAC
    assert found[2].get_audio_format() == AudioFormat.AAC

    found = parsed_file.find_tracks(type=TrackType.VIDEO)
    assert bool(found)
    assert found[0].codec_name == "hevc"


def test_find_by_relative_index(parsed_file):
    found = parsed_file.find_tracks(type=TrackType.AUDIO, relative_id=2)

    assert len(found) == 1
    assert found[0].get_audio_format() == AudioFormat.AAC
    assert found[0].language == "ger"


def test_find_by_language(parsed_file):
    found = parsed_file.find_tracks(lang="jpn")

    assert len(found) == 2
    assert found[0].type == TrackType.VIDEO
    assert found[1].type == TrackType.AUDIO
    assert found[1].get_audio_format() == AudioFormat.OPUS

    found = parsed_file.find_tracks(lang="ja", reverse_lang=True)

    assert len(found) == 2
    assert found[0].type == TrackType.AUDIO
    assert found[1].type == TrackType.AUDIO


def test_find_custom_condition(parsed_file):
    found = parsed_file.find_tracks(custom_condition=lambda track: track.get_audio_format() == AudioFormat.OPUS)

    assert len(found) == 1
    assert found[0].type == TrackType.AUDIO


def test_error_on_empty(parsed_file):
    with pytest.raises(Exception):
        parsed_file.find_tracks(custom_condition=lambda track: track.get_audio_format() == AudioFormat.FLAC, error_if_empty=True)
