from muxtools import Setup, get_workdir, ensure_path, SubFilePGS
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


def test_pgs_extraction():
    f = test_dir / "test-data" / "sample-files" / "with-pgs" / "H265-PGS-sample.m2ts"
    sub = SubFilePGS.extract_from(f, 0)
    assert sub.file

    f = test_dir / "test-data" / "sample-files" / "with-pgs" / "H265-PGS-sample.mkv"
    sub = SubFilePGS.extract_from(f, 1)
    assert sub.file
    assert sub.to_track("Test", "en").mkvmerge_args()
