from muxtools import TmdbConfig, TMDBOrder, download_file, Setup, get_workdir
from shutil import rmtree
from time import sleep
import hashlib
import pytest


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())

def test_tmdb_custom_order() -> None:
    cfg = TmdbConfig(95479, 2, order=TMDBOrder.PRODUCTION)
    episode_meta = cfg.get_episode_meta(1)
    assert episode_meta is not None
    assert episode_meta.release_date == "2023-07-06"


def test_tmdb_sanitization() -> None:
    cfg = TmdbConfig(65336)
    episode_meta = cfg.get_episode_meta(1)
    assert episode_meta is not None
    assert episode_meta.title == "Rei Kiriyama / The Town Along the River"
    assert episode_meta.title_sanitized == "Rei Kiriyama  The Town Along the River"

def test_download_file() -> None:
    file = download_file("https://github.com/Vodes/muxtools-binaries/releases/download/flac-1.5.0.post1/flac-1.5.0.post1-windows-x86_64.tar.zst", get_workdir())

    with file.open("rb") as stream:
        hash = hashlib.file_digest(stream, "sha256").hexdigest()

    assert file.name == "flac-1.5.0.post1-windows-x86_64.tar.zst"
    assert hash == "bd4e2c535fb01be6aeab89b154cc28f0197d435f841c93b2aaf96460b0c59084"
