import json
import subprocess
from pathlib import Path

import pytest

from muxtools import AudioFormat, ParsedFile
from muxtools.utils import probe
from muxtools.utils.ffprobe import parse_probe_json, probe_file


def test_json_metadata_and_numeric_fields():
    raw = {
        "format": {"nb_streams": "1", "format_name": "matroska,webm", "tags": {"title": "日本語"}, "duration": "1.25"},
        "streams": [
            {
                "index": 0,
                "codec_name": "flac",
                "codec_long_name": "FLAC (Free Lossless Audio Codec)",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 6,
                "channel_layout": "5.1",
                "bits_per_sample": 0,
                "bits_per_raw_sample": "24",
                "bit_rate": "192000",
                "tags": {"language": "jpn", "title": "音声", "BPS": "192000"},
                "disposition": {"default": 1, "forced": 0},
                "side_data_list": [{"side_data_type": "Frame Cropping", "crop_left": 2}],
                "new_field": {"value": "untouched"},
            }
        ],
        "chapters": [{"id": 0, "start_time": "0.000000", "tags": {"title": "開始"}}],
        "new_section": {"value": 42},
    }
    parsed = parse_probe_json(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    stream = parsed.streams[0]

    assert parsed.format.nb_streams == 1
    assert parsed.format.tags == {"title": "日本語"}
    assert stream.index == 0
    assert stream.sample_rate == 48000
    assert stream.channels == 6
    assert stream.bits_per_sample == 0
    assert stream.bits_per_raw_sample == 24
    assert stream.bit_rate == 192000
    assert stream.channel_layout == "5.1"
    assert stream.tags["title"] == "音声"
    assert stream.disposition == {"default": 1, "forced": 0}
    assert stream.side_data_list == raw["streams"][0]["side_data_list"]
    assert parsed.chapters == raw["chapters"]
    assert parsed.raw == raw
    assert parsed.format.raw == raw["format"]
    assert stream.raw == raw["streams"][0]
    assert AudioFormat.from_track(stream) == AudioFormat.FLAC


@pytest.mark.parametrize("value", [None, "N/A", "", "unknown"])
def test_unavailable_numeric_fields(value):
    result = parse_probe_json(json.dumps({"format": {}, "streams": [{"sample_rate": value, "bits_per_raw_sample": value, "bit_rate": value}]}))
    stream = result.streams[0]
    assert stream.sample_rate is None
    assert stream.bits_per_raw_sample is None
    assert stream.bit_rate is None
    assert stream.channels is None
    assert stream.tags == {}
    assert stream.disposition == {}
    assert stream.side_data_list == []
    assert result.chapters == []


def test_parsing_preserves_raw_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "test.flac"
    path.touch()
    result = parse_probe_json(
        json.dumps(
            {
                "format": {"format_name": "flac", "nb_streams": 1, "tags": {"title": "音声"}},
                "streams": [
                    {
                        "index": 0,
                        "codec_name": "flac",
                        "codec_long_name": "FLAC (Free Lossless Audio Codec)",
                        "codec_type": "audio",
                        "tags": {"language": "jpn", "title": "音声", "BPS": "192000"},
                        "disposition": {"default": 1, "forced": 0},
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(probe, "get_executable", lambda *args, **kwargs: "ffprobe")
    monkeypatch.setattr(probe, "probe_file", lambda *args: result)
    parsed = ParsedFile.from_file(path)
    track = parsed.tracks[0]

    assert track.language == "jpn"
    assert track.title == "音声"
    assert track.other_tags == {"BPS": "192000"}
    assert track.is_default and not track.is_forced
    assert track.raw_ffprobe.tags == {"language": "jpn", "title": "音声", "BPS": "192000"}
    assert track.get_audio_format() == AudioFormat.FLAC
    parsed.container_info.tags.clear()
    assert parsed.container_info.raw_ffprobe.tags == {"title": "音声"}


@pytest.mark.parametrize("output", ["{", "[]", "{}", '{"format": null}'])
def test_invalid_probe_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str):
    path = tmp_path / "test.mkv"
    path.touch()
    monkeypatch.setattr(probe, "get_executable", lambda *args, **kwargs: "ffprobe")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, "diagnostic"))

    with pytest.raises(Exception, match="Failed to parse file 'test' with ffprobe"):
        ParsedFile.from_file(path)


def test_probe_command_and_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "日本語 sample.mkv"

    def run(args, **kwargs):
        assert args == ["custom-ffprobe", "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", "-i", str(path)]
        assert kwargs == {"capture_output": True, "check": True, "encoding": "utf-8"}
        return subprocess.CompletedProcess(args, 0, '{"format": {"tags": {"title": "日本語"}}}', "diagnostic")

    monkeypatch.setattr(subprocess, "run", run)
    result = probe_file(path, "custom-ffprobe")
    assert result.format.tags == {"title": "日本語"}


def test_failed_probe_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "test.mkv"
    path.touch()

    def run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output='{"format": {}}', stderr="Invalid data")

    monkeypatch.setattr(probe, "get_executable", lambda *args, **kwargs: "ffprobe")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(Exception, match="Failed to parse file 'test' with ffprobe"):
        ParsedFile.from_file(path)


@pytest.mark.parametrize("format_name", ["matroska,webm", "tty"])
def test_empty_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format_name: str):
    path = tmp_path / "test.mkv"
    path.touch()
    result = parse_probe_json(json.dumps({"format": {"format_name": format_name}}))
    monkeypatch.setattr(probe, "get_executable", lambda *args, **kwargs: "ffprobe")
    monkeypatch.setattr(probe, "probe_file", lambda *args: result)
    parsed = ParsedFile.from_file(path)
    assert parsed.tracks == []
    assert not parsed.is_video_file
    assert parsed.container_info.format_name == "Unknown"
    assert parsed.raw_ffprobe is result
