from muxtools import Setup, get_workdir, ensure_path, Chapters, SubFile, mux, download_binary, Premux
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
