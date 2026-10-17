from pathlib import Path
import subprocess

import pytest

from muxtools import MKVExtract, ParsedFile, Setup, TrackType, get_executable, get_workdir, mux
from muxtools.helpers import extract
from muxtools.utils.ffprobe import probe_file
from muxtools.utils.log import LoggingException


SAMPLES = Path(__file__).resolve().parent.parent / "test-data" / "sample-files"


def run_binary(name: str, *args: str | Path) -> None:
    result = subprocess.run([get_executable(name), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode <= (1 if name.startswith("mkv") else 0), result.stdout + result.stderr


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("vof_setup", raising=False)
    Setup("extract-test", work_dir=str(tmp_path / "work"), clean_work_dirs=False, mkv_title_naming="").edit("skip_mux_branding", True)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    english = tmp_path / "english.srt"
    english.write_text("1\n00:00:01,000 --> 00:00:02,000\n<i>Keep SRT!</i>\n", encoding="utf-8")
    french = tmp_path / "french.srt"
    french.write_text("1\n00:00:00,500 --> 00:00:01,500\nBonjour\n", encoding="utf-8")
    tags = tmp_path / "tags.xml"
    tags.write_text("<Tags><Tag><Targets/><Simple><Name>CUSTOM</Name><String>retained</String></Simple></Tag></Tags>", encoding="utf-8")
    font = tmp_path / "font.ttf"
    font.write_bytes(b"attachment bytes")
    data = tmp_path / "data.bin"
    data.write_bytes(b"second attachment bytes")
    output = tmp_path / "source.mkv"
    run_binary(
        "mkvmerge",
        "-o",
        output,
        "--no-chapters",
        "--no-attachments",
        SAMPLES / "H265-Opus-AAC-sample.mkv",
        "--language",
        "0:en-US",
        "--track-name",
        "0:Original SRT",
        "--default-track-flag",
        "0:no",
        "--forced-display-flag",
        "0:yes",
        "--tags",
        f"0:{tags}",
        "--sync",
        "0:240",
        english,
        "--language",
        "0:fr",
        french,
        "--track-order",
        "0:0,1:0,0:1,2:0,0:2,0:3",
        "--attachment-mime-type",
        "font/ttf",
        "--attachment-name",
        "../same.ttf",
        "--attach-file",
        font,
        "--attachment-mime-type",
        "application/octet-stream",
        "--attachment-name",
        "../same.ttf",
        "--attach-file",
        data,
    )
    return output


def test_native_srt_content_and_timing(source: Path) -> None:
    subtitle = MKVExtract(source).sub_track()

    assert subtitle.file.suffix == ".srt"
    assert subtitle.file.read_text(encoding="utf-8-sig") == "1\n00:00:01,240 --> 00:00:02,240\n<i>Keep SRT!</i>\n\n"
    assert subtitle.delay == 0


def test_repeated_selection_uses_the_same_relative_track(source: Path) -> None:
    extractor = MKVExtract(source)
    first = extractor.sub_track(1)
    repeat = extractor.sub_track(1)

    assert "Bonjour" in first.file.read_text(encoding="utf-8-sig")
    assert repeat.file.read_bytes() == first.file.read_bytes()
    assert repeat.file != first.file


def test_inherited_subtitle_metadata(source: Path) -> None:
    track = MKVExtract(source).sub_track()

    assert track.name == "Original SRT"
    assert track.lang == "en-US"
    assert not track.default
    assert track.forced
    assert track.tags and track.tags.get("CUSTOM") == "retained"


def test_explicit_metadata_overrides(source: Path) -> None:
    track = MKVExtract(source).sub_track(name="", lang="", default=False, forced=False, delay=0, tags={})

    assert track.name == ""
    assert track.lang == ""
    assert not track.default
    assert not track.forced
    assert track.delay == 0
    assert track.tags == {}


def test_audio_selection(source: Path) -> None:
    extractor = MKVExtract(source)
    first = extractor.audio_track()
    selected = extractor.audio_track(2)

    assert first.name == "Japanese 2.0"
    assert first.file.suffix == ".opus"
    assert selected.name == "German 2.0"
    assert selected.file.suffix == ".aac"


def test_output_routing(source: Path, tmp_path: Path) -> None:
    default = MKVExtract(source).audio_track()
    output = tmp_path / "extracted"
    extractor = MKVExtract(source, output)
    routed = extractor.sub_track()
    per_call_output = tmp_path / "per-call"
    per_call_output.mkdir()
    per_call = extractor.audio_track(output=per_call_output)

    assert default.file.parent == get_workdir()
    assert output.is_dir() and routed.file.parent == output
    assert per_call.file.parent == tmp_path / "per-call"


def test_explicit_output_filename(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Preserve project binaries when changing directories outside the project.
    for name in ("ffprobe", "mkvmerge", "mkvextract"):
        monkeypatch.setenv(f"vof_exe_{name}", get_executable(name))
    monkeypatch.chdir(tmp_path)
    track = MKVExtract(source, tmp_path / "default").audio_track(output="custom/name.txt")

    assert track.file == tmp_path / "custom" / "name.opus"


def test_audio_only_fallback(tmp_path: Path) -> None:
    source = tmp_path / "audio.mka"
    run_binary(
        "mkvmerge",
        "-o",
        source,
        "-D",
        "-a",
        "1,2",
        "--no-chapters",
        "--language",
        "2:en-US",
        "--default-track-flag",
        "2:no",
        "--forced-display-flag",
        "2:yes",
        SAMPLES / "H265-Opus-AAC-sample.mkv",
    )
    parsed = ParsedFile.from_file(source)
    english = MKVExtract(source).audio_track(1)

    assert parsed.raw_mkvmerge is None
    assert (english.name, english.lang, english.file.suffix) == ("English 5.1", "en-US", ".aac")
    assert not english.default and english.forced and english.file.read_bytes()[:4] != b"OggS"


def test_shifted_ffprobe_ids_keep_mkv_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    source = SAMPLES / "H265-Opus-AAC-sample.mkv"

    def shifted_indices(path: Path, executable: str):
        result = probe_file(path, executable)
        if path == source:
            streams = [stream.model_copy(update={"index": (stream.index or 0) + 1}) for stream in result.streams]
            return result.model_copy(update={"streams": streams})
        return result

    monkeypatch.setattr("muxtools.utils.probe.probe_file", shifted_indices)
    parsed = ParsedFile.from_file(source)
    output = MKVExtract(source).audio_track()

    identified = parsed.find_tracks(type=TrackType.AUDIO, relative_id=0)[0].raw_mkvmerge
    assert identified and identified.id == 1
    assert output.name == "Japanese 2.0" and output.file.suffix == ".opus"
    assert output.file.read_bytes().startswith(b"OggS")


def test_attachments_preserve_bytes_and_mime_through_mux(source: Path, tmp_path: Path) -> None:
    extractor = MKVExtract(source, tmp_path / "attachments")
    first = extractor.attachment()
    attachments = extractor.attachments()

    assert first.file.read_bytes() == attachments[0].file.read_bytes() == b"attachment bytes"
    assert [a.file.read_bytes() for a in attachments] == [b"attachment bytes", b"second attachment bytes"]
    assert [(a.name, a.lang) for a in attachments] == [
        ("../same.ttf", "font/ttf"),
        ("../same.ttf", "application/octet-stream"),
    ]
    remuxed = mux(extractor.video_track(), *attachments, outfile=tmp_path / "attachments-remux.mkv")
    info = ParsedFile.from_file(remuxed).raw_mkvmerge
    assert info and [(a.file_name, a.content_type) for a in info.attachments] == [
        ("../same.ttf", "font/ttf"),
        ("../same.ttf", "application/octet-stream"),
    ]


def test_extraction_failure_cleans_partial_outputs(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "failed"
    marker = output / "keep.txt"
    output.mkdir()
    marker.write_text("keep me", encoding="utf-8")

    def command(args: list[str], *unused: object, **kwargs: object) -> int:
        Path(args[-1].split(":", 1)[1]).write_bytes(b"partial output")
        return 2

    monkeypatch.setattr(extract, "run_commandline", command)
    extractor = MKVExtract(source, output)

    with pytest.raises(LoggingException):
        extractor.audio_track()
    with pytest.raises(LoggingException):
        extractor.attachment()

    assert list(output.iterdir()) == [marker]


def timestamps(file: Path, output: Path) -> list[float]:
    run_binary("mkvextract", file, "timestamps_v2", f"0:{output}")
    return [float(line) for line in output.read_text(encoding="utf-8-sig").splitlines() if line and not line.startswith("#")]


@pytest.fixture
def delayed_source(tmp_path: Path) -> tuple[Path, list[int]]:
    sample = SAMPLES / "H265-Opus-AAC-sample.mkv"
    original = timestamps(sample, tmp_path / "original.txt")
    vfr = [120 + i * 60 + (20 if i % 2 else 0) for i in range(len(original))]
    timing = tmp_path / "vfr.txt"
    timing.write_text("# timestamp format v2\n" + "\n".join(map(str, vfr)) + "\n", encoding="utf-8")
    source = tmp_path / "vfr.mkv"
    run_binary(
        "mkvmerge",
        "-o",
        source,
        "-A",
        "--no-chapters",
        "--timestamps",
        f"0:{timing}",
        sample,
        "-D",
        "-a",
        "1",
        "--no-chapters",
        "--sync",
        "1:250",
        sample,
    )
    return source, vfr


def test_vfr_video_roundtrip(delayed_source: tuple[Path, list[int]], tmp_path: Path) -> None:
    source, expected = delayed_source
    video = MKVExtract(source).video_track()
    timecode = Path(video.args[video.args.index("--timestamps") + 1].split(":", 1)[1])

    remuxed = mux(video, outfile=tmp_path / "vfr-remux.mkv")
    assert timecode.parent == video.file.parent
    assert timestamps(remuxed, tmp_path / "after.txt") == expected


def test_opus_delay_roundtrip(delayed_source: tuple[Path, list[int]], tmp_path: Path) -> None:
    source = delayed_source[0]
    extractor = MKVExtract(source)
    remuxed = mux(extractor.video_track(), extractor.audio_track(), outfile=tmp_path / "roundtrip.mkv")
    before = ParsedFile.from_file(source).find_tracks(type=TrackType.AUDIO)[0].raw_mkvmerge
    after = ParsedFile.from_file(remuxed).find_tracks(type=TrackType.AUDIO)[0].raw_mkvmerge

    assert before and after
    assert before.properties.minimum_timestamp is not None
    assert after.properties.minimum_timestamp is not None
    assert abs(after.properties.minimum_timestamp - before.properties.minimum_timestamp) <= 1_000_000
