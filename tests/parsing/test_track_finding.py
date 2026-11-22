from pathlib import Path

from muxtools import ensure_path, TrackType
from muxtools.utils import AudioFormat, ContainerInfo, ParsedFile, ProbeFormat, ProbeResult, ProbeStream, TrackInfo
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


def _parsed_with_sub_langs(*langs: str) -> ParsedFile:
    tracks = [
        TrackInfo(
            index=i,
            relative_index=i,
            type=TrackType.SUB,
            codec_name="ass",
            codec_long_name=None,
            profile=None,
            language=lang,
            title=None,
            is_default=False,
            is_forced=False,
            container_delay=0,
            other_tags={},
            raw_ffprobe=ProbeStream(index=i, codec_name="ass", codec_type="subtitle"),
            raw_mkvmerge=None,
        )
        for i, lang in enumerate(langs)
    ]
    probe_format = ProbeFormat(nb_streams=len(tracks), format_name="matroska")
    return ParsedFile(
        container_info=ContainerInfo(len(tracks), "matroska", None, {}, probe_format, None),
        tracks=tracks,
        is_video_file=False,
        source=Path("synthetic.mkv"),
        raw_ffprobe=ProbeResult(format=probe_format, streams=[t.raw_ffprobe for t in tracks]),
        raw_mkvmerge=None,
    )


def test_find_by_language_hierarchy_and_allow_broader():
    parsed = _parsed_with_sub_langs("en", "en-US", "en-GB", "es", "es-419", "es-ES", "zh-Hans", "zh-Hans-CN", "zh-Hant", "zh-TW")

    assert [t.language for t in parsed.find_tracks(lang="en")] == ["en", "en-US", "en-GB"]
    assert [t.language for t in parsed.find_tracks(lang="en-US")] == ["en-US"]
    assert [t.language for t in parsed.find_tracks(lang="en-US", allow_broader_lang=True)] == ["en", "en-US"]

    assert [t.language for t in parsed.find_tracks(lang="es")] == ["es", "es-419", "es-ES"]
    assert [t.language for t in parsed.find_tracks(lang="es-419")] == ["es-419"]
    assert [t.language for t in parsed.find_tracks(lang="es-419", allow_broader_lang=True)] == ["es", "es-419"]
    assert [t.language for t in parsed.find_tracks(lang="es-ES")] == ["es-ES"]
    assert [t.language for t in parsed.find_tracks(lang="es-ES", allow_broader_lang=True)] == ["es", "es-ES"]

    assert [t.language for t in parsed.find_tracks(lang="zh-Hans")] == ["zh-Hans", "zh-Hans-CN"]
    assert [t.language for t in parsed.find_tracks(lang="zh-CN")] == ["zh-Hans", "zh-Hans-CN"]
    assert [t.language for t in parsed.find_tracks(lang="zh-Hant")] == ["zh-Hant", "zh-TW"]
    assert [t.language for t in parsed.find_tracks(lang="zh-TW")] == ["zh-Hant", "zh-TW"]
    assert [t.language for t in parsed.find_tracks(lang="zh-Hans-CN")] == ["zh-Hans-CN"]
    assert [t.language for t in parsed.find_tracks(lang="zh-Hans-CN", allow_broader_lang=True)] == ["zh-Hans", "zh-Hans-CN"]
