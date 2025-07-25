from muxtools import ensure_path, Setup, get_workdir, ParsedFile
from muxtools.helpers.bsf import apply_mpeg2_bsf, BSF_Format, BSF_Matrix, BSF_Primaries, BSF_Transfer, MPEG2_DAR, MPEG2_FPS
from time import sleep
from shutil import rmtree, copy
import pytest


test_dir = ensure_path(__file__, None).parent.parent
sample_file = test_dir / "test-data" / "sample-files" / "H262-DTS-ES-sample.m2ts"


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)
    f = get_workdir() / "Test.m2ts"

    copy(sample_file, f)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_invalid_values():
    f = get_workdir() / "Test.m2ts"
    for transfer in [BSF_Transfer.LOG100, BSF_Transfer.HLG, BSF_Transfer.BT2020_10]:
        with pytest.raises(Exception):
            apply_mpeg2_bsf(f, transfer=transfer)

    for matrix in [BSF_Matrix.RGB, BSF_Matrix.YCGCO]:
        with pytest.raises(Exception):
            apply_mpeg2_bsf(f, matrix=matrix)

    for primaries in [BSF_Primaries.FILM, BSF_Primaries.BT2020]:
        with pytest.raises(Exception):
            apply_mpeg2_bsf(f, primaries=primaries)


def test_nothing_ever_happens():
    f = get_workdir() / "Test.m2ts"
    with pytest.raises(Exception):
        apply_mpeg2_bsf(f)


def test_apply():
    f = get_workdir() / "Test.m2ts"
    apply_mpeg2_bsf(
        f,
        dar=MPEG2_DAR.DAR_16_9,
        fps=MPEG2_FPS.FPS_25,
        format=BSF_Format.NTSC,
        primaries=BSF_Primaries.SMPTE170M,
        transfer=BSF_Transfer.BT601,
        matrix=BSF_Matrix.SMPTE170M,
    )

    original = ParsedFile.from_file(sample_file).tracks[0].raw_ffprobe
    new = ParsedFile.from_file(f).tracks[0].raw_ffprobe

    assert not original.color_transfer and new.color_transfer == "smpte170m"
    assert not original.color_primaries and new.color_primaries == "smpte170m"
    assert not original.color_space and new.color_space == "smpte170m"
    assert original.avg_frame_rate != new.avg_frame_rate and new.avg_frame_rate == "25/1"
