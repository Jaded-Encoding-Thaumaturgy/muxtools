from muxtools import ensure_path, Setup, get_workdir, ParsedFile
from muxtools.helpers.bsf import (
    BSF_Format,
    BSF_Matrix,
    BSF_Primaries,
    BSF_Transfer,
    BSF_ChromaLocation,
    apply_hevc_bsf,
    apply_avc_bsf,
)
from time import sleep
from shutil import rmtree, copy
import pytest


test_dir = ensure_path(__file__, None).parent.parent
sample_file_h264 = test_dir / "test-data" / "sample-files" / "H264-PCM-sample.m2ts"
sample_file_h265 = test_dir / "test-data" / "sample-files" / "H265-Opus-AAC-sample-18F78726.mkv"


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    copy(sample_file_h264, get_workdir() / "Test_h264.m2ts")
    copy(sample_file_h265, get_workdir() / sample_file_h265.name)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_nothing_ever_happens():
    with pytest.raises(Exception, match="avc"):
        apply_avc_bsf(get_workdir() / "Test_h264.m2ts")
    with pytest.raises(Exception, match="hevc"):
        apply_hevc_bsf(get_workdir() / sample_file_h265.name)


def test_apply_avc_bsf():
    f = get_workdir() / "Test_h264.m2ts"
    apply_avc_bsf(
        f,
        sar=1,
        cloc_type=2,
        full_range=True,
        format=BSF_Format.NTSC,
        primaries=BSF_Primaries.SMPTE170M,
        transfer=BSF_Transfer.BT601,
        matrix=BSF_Matrix.SMPTE170M,
    )

    original = ParsedFile.from_file(sample_file_h264).tracks[0].raw_ffprobe
    new = ParsedFile.from_file(f).tracks[0].raw_ffprobe

    assert not original.color_transfer and new.color_transfer == "smpte170m"
    assert not original.color_primaries and new.color_primaries == "smpte170m"
    assert not original.color_space and new.color_space == "smpte170m"
    assert not original.color_range and new.color_range == "pc"
    assert original.chroma_location == "left"
    assert new.chroma_location == "topleft"


def test_apply_hevc_bsf():
    f = get_workdir() / sample_file_h265.name
    f = apply_hevc_bsf(
        f,
        sar=1,
        cloc_type=BSF_ChromaLocation.CENTER,
        full_range=True,
        format=BSF_Format.NTSC,
        primaries=BSF_Primaries.SMPTE170M,
        transfer=BSF_Transfer.BT601,
        matrix=BSF_Matrix.SMPTE170M,
    )

    assert f.name != sample_file_h265.name

    original = ParsedFile.from_file(sample_file_h265).tracks[0].raw_ffprobe
    new = ParsedFile.from_file(f).tracks[0].raw_ffprobe

    assert original.color_transfer == "bt709" and new.color_transfer == "smpte170m"
    assert original.color_primaries == "bt709" and new.color_primaries == "smpte170m"
    assert original.color_space == "bt709" and new.color_space == "smpte170m"
    assert original.color_range == "tv" and new.color_range == "pc"
    assert original.chroma_location == "left"
    assert new.chroma_location == "center"


def test_chromalocs():
    f = get_workdir() / sample_file_h265.name
    for cloc in BSF_ChromaLocation:
        f = apply_hevc_bsf(f, cloc_type=cloc)

        new = ParsedFile.from_file(f).tracks[0].raw_ffprobe

        assert new.chroma_location == cloc.name.lower().replace("_", "")

    f = get_workdir() / "Test_h264.m2ts"
    for cloc in BSF_ChromaLocation:
        f = apply_avc_bsf(f, cloc_type=cloc)

        new = ParsedFile.from_file(f).tracks[0].raw_ffprobe

        assert new.chroma_location == cloc.name.lower().replace("_", "")


def test_crops():
    f = get_workdir() / sample_file_h265.name
    f = apply_hevc_bsf(f, crop=2)

    new = ParsedFile.from_file(f).tracks[0].raw_ffprobe
    assert new.width == 1916
    assert new.height == 1076

    f = get_workdir() / "Test_h264.m2ts"
    apply_avc_bsf(f, crop=2)

    new = ParsedFile.from_file(f).tracks[0].raw_ffprobe
    assert new.width == 1916
    assert new.height == 1084  # AVC has internal mod16 padding
