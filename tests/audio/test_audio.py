from muxtools import ensure_path, Setup, get_workdir, do_audio, get_executable, Opus, Sox, FFMpeg, VideoMeta, FLAC
from muxtools.utils.env import communicate_stdout
from time import sleep
from shutil import rmtree
import pytest
import logging
import os

test_dir = ensure_path(__file__, None).parent.parent
sample_file_aac = test_dir / "test-data" / "audio" / "aac_source.m4a"
sample_file_flac = test_dir / "test-data" / "audio" / "flac_source.flac"
sample_file_wav = test_dir / "test-data" / "audio" / "wav_source.wav"
sample_file_thd_fake24 = test_dir / "test-data" / "audio" / "thd_source_fake24.thd"


def get_md5_for_stream(file) -> str:
    ffmpeg = get_executable("ffmpeg")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(file), "-map", "0:a:0", "-f", "md5", "-"]
    code, out = communicate_stdout(args)
    if code != 0:
        raise RuntimeError(f"Failed to get md5 for stream in file: {str(file)}")
    return out.split("=")[1].strip()


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_lossy_input_no_encode():
    out = do_audio(sample_file_aac)
    assert get_md5_for_stream(out.file) == "3fe4c6674cc3b2ffc3ba3247c91ed622"


def test_lossy_input(caplog):
    out = do_audio(sample_file_aac, encoder=Opus())

    # Prints a danger log for reencoding lossy audio
    assert len([record for record in caplog.get_records("call") if record.levelname == "DANGER"]) == 1

    assert get_md5_for_stream(out.file) == "63b86479c6ef00f8065cf53ea16e5b35"


def test_flac_input():
    out = do_audio(sample_file_flac, encoder=Opus())
    assert get_md5_for_stream(out.file) == "3b71027670bdf582de0158e938405077"


def test_flac_sox_trim():
    # Cba to add sox to the github workflow
    if os.name != "nt":
        return
    meta = VideoMeta.from_json(test_dir / "test-data" / "input" / "vigilantes_s01e01.json")

    out = do_audio(sample_file_flac, trims=(-24, None), num_frames=len(meta.pts), timesource=meta, trimmer=Sox(), encoder=Opus())
    logging.getLogger("test_flac_sox_trim").log(200, get_md5_for_stream(out.file))


def test_flac_ffmpeg_trim():
    meta = VideoMeta.from_json(test_dir / "test-data" / "input" / "vigilantes_s01e01.json")

    out = do_audio(sample_file_flac, trims=(24, None), timesource=meta, trimmer=FFMpeg.Trimmer(), encoder=Opus())
    assert get_md5_for_stream(out.file) == "09c1bab3cae39460a8c1fccac884efa5"


def test_depth_detection(caplog):
    out = do_audio(sample_file_thd_fake24, encoder=FLAC(threads=1))

    assert len([record for record in caplog.get_records("call") if "padded 24" in record.message]) == 1
    assert len([record for record in caplog.get_records("call") if "truncated to 16" in record.message]) == 1

    assert get_md5_for_stream(out.file) == "52219678c3ac04dcd34e15d8a55e35df"


def test_opus_no_extractor(caplog):
    # Should encode file as is, 192 kbps default for stereo
    Opus().encode_audio(sample_file_wav)
    assert len([record for record in caplog.get_records("call") if "Encoding 'wav_source' to Opus (192 kbps)" in record.message]) == 1
    assert len([record for record in caplog.get_records("call") if "Piping audio" in record.message]) == 0

    # Should pipe from ffmpeg to have flac input because THD is not supported, 320 kbps default for 5.1
    Opus().encode_audio(sample_file_thd_fake24)
    assert len([record for record in caplog.get_records("call") if "Encoding 'thd_source_fake24' to Opus (320 kbps)" in record.message]) == 1
    assert len([record for record in caplog.get_records("call") if "Piping audio" in record.message]) == 1
