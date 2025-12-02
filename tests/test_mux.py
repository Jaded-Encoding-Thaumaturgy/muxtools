from muxtools import Setup, get_workdir, ensure_path, Chapters, SubFile, mux, download_binary, Premux, do_audio, ParsedFile, TrackType, FFMpeg
import muxtools

from shutil import rmtree
from time import sleep
import os
import pytest
import hashlib

test_dir = ensure_path(__file__, None).parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    setup = Setup("Test", None)
    setup.edit("mkv_title_naming", "")
    setup.edit("skip_mux_branding", True)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_mux():
    # Ensure use of mkvmerge 94.0 when running locally
    if os.name == "nt":
        from muxtools.utils.download import Tool

        muxtools.utils.download.tools = [
            Tool(
                "mkvmerge",
                "https://github.com/Vodes/muxtools-binaries/releases/download/mkvtoolnix-94.0/mkvtoolnix-94.0-windows-amd64.zip",
                ["mkvextract", "mkvinfo", "mkvpropedit"],
            )
        ]
        download_binary("mkvmerge")

    premux = Premux(
        test_dir / "test-data" / "sample-files" / "H265-Opus-EAC3-sample.mkv",
        mkvmerge_args="--no-global-tags --no-chapters --deterministic muxtools-tests-123",
    )
    sub = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    ch = Chapters.from_sub(test_dir / "test-data" / "input" / "atri-subkt" / "ATRI 03 - Dialogue.ass", use_actor_field=True)

    out = mux(premux, sub.to_track("Test"), ch, outfile=get_workdir() / "muxed.mkv", print_cli=True)

    assert hashlib.md5(out.read_bytes()).hexdigest() == "26ebd7a5bd5156adf265c07a938ae002"


def test_metadata_tokens():
    setup = Setup("Test", None)
    setup.edit("mkv_title_naming", "")
    setup.edit("skip_mux_branding", True)
    setup.edit("out_dir", str(get_workdir()))

    sample_files = test_dir / "test-data" / "sample-files"

    video = Premux(sample_files / "H265-Opus-EAC3-sample.mkv", audio=None, subtitles=None, keep_attachments=False)
    extractor = FFMpeg.Extractor(skip_analysis=True)
    test_ja = do_audio(sample_files / "H264-THD-Atmos-PCM-DTS-HeadphoneX-sample.m2ts", 1, extractor=extractor)
    test_de = do_audio(sample_files / "H264-DTS-HD-sample.mkv", 0, encoder=None, extractor=extractor)

    # Token usage in filenaming
    setup.edit("out_name", "Test Thing - 01 [BD $res$ $vformat$ $aformat$] [Group]")

    # Token usage in Track naming
    out = mux(
        video,
        test_ja.to_track("$language$ $ch$ / $format$"),
        test_de.to_track("$language$ $ch$ / $format$", "de"),
    )

    assert out.name == "Test Thing - 01 [BD 1080p HEVC TrueHD Atmos] [Group].mkv"

    a_tracks = ParsedFile.from_file(out).find_tracks(type=TrackType.AUDIO)
    assert a_tracks[0].title == "Japanese 7.1 / TrueHD Atmos"
    assert a_tracks[1].title == "German 5.1 / DTS-HD MA"
