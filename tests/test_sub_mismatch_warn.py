from muxtools import Setup, get_workdir, ensure_path, SubFile, ASSHeader
from shutil import rmtree
from time import sleep
import pytest

test_dir = ensure_path(__file__, None).parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_mismatching_res_merge(caplog) -> None:
    """
    Test to check if merging subtitles with different resolution headers logs a warning.
    """
    sub = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    other = sub.copy(get_workdir() / "vigilantes_s01e01_en_mismatched_playres").set_headers((ASSHeader.PlayResX, 1280), (ASSHeader.PlayResY, 720))
    sub.merge(other)
    assert len([record for record in caplog.get_records("call") if record.levelname == "DANGER"]) == 2

    other2 = sub.copy(get_workdir() / "vigilantes_s01e01_en_no_layoutres").set_headers((ASSHeader.LayoutResX, None), (ASSHeader.LayoutResY, None))
    sub.merge(other2)
    assert len([record for record in caplog.get_records("call") if record.levelname == "WARN"]) == 2

    other3 = sub.copy(get_workdir() / "vigilantes_s01e01_en_bt601").set_headers((ASSHeader.YCbCr_Matrix, "TV.601"))
    sub.merge(other3)
    assert len([record for record in caplog.get_records("call") if record.levelname == "DANGER"]) == 3


def test_mismatching_res_init_merge(caplog) -> None:
    """
    Test to check if initializing a SubFile with multiple files with different resolutions set will log warnings.
    """
    initial = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    other = initial.copy().set_headers((ASSHeader.PlayResX, 1280), (ASSHeader.PlayResY, 720))

    sub = SubFile([initial.file, other.file])
    assert sub.file
    assert len([record for record in caplog.get_records("call") if record.levelname == "DANGER"]) == 2


def test_error_on_danger() -> None:
    """
    Test to check if merging with a resulting "danger" log actually throws an error when enabling the setting in the Setup.
    """
    Setup("Test", None, error_on_danger=True)

    sub = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    other = sub.copy(get_workdir() / "vigilantes_s01e01_en_mismatched_playres").set_headers((ASSHeader.PlayResX, 1280), (ASSHeader.PlayResY, 720))

    with pytest.raises(Exception):
        sub.merge(other)
