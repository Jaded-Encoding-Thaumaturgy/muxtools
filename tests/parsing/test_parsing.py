from muxtools import ensure_path
from muxtools import ParsedFile, AudioFormat

test_dir = ensure_path(__file__, None).parent.parent


def test_h262_dts_es():
    sample_file = test_dir / "test-data" / "sample-files" / "H262-DTS-ES-sample.m2ts"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "mpegts"
    assert parsed.tracks[0].codec_name == "mpeg2video"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.DTS_ES
    assert parsed.tracks[2].get_audio_format() == AudioFormat.AC3


def test_h264_flac():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-10bit-FLAC-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[0].raw_ffprobe.bits_per_raw_sample == 10
    assert parsed.tracks[1].get_audio_format() == AudioFormat.FLAC


def test_h264_ddp_atmos():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-DDP-Atmos-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.EAC3_ATMOS


def test_h264_dts_hra():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-DTS-HD-HRA-sample.m2ts"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "mpegts"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.AC3
    assert parsed.tracks[2].get_audio_format() == AudioFormat.DTS_HRA
    assert parsed.tracks[2].get_audio_format().is_lossy


def test_h264_dts_hd():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-DTS-HD-sample.m2ts"
    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "mpegts"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.DTS_HD
    assert parsed.tracks[2].get_audio_format() == AudioFormat.DTS_HD
    assert not parsed.tracks[2].get_audio_format().is_lossy

    sample_file = test_dir / "test-data" / "sample-files" / "H264-DTS-HD-sample.mkv"
    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.DTS_HD
    assert parsed.tracks[2].get_audio_format() == AudioFormat.DTS_HD
    assert not parsed.tracks[2].get_audio_format().is_lossy


def test_h264_dts():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-DTS-sample.mkv"
    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[0].raw_ffprobe.bits_per_raw_sample == 10
    assert parsed.tracks[1].get_audio_format() == AudioFormat.DTS
    assert parsed.tracks[1].get_audio_format().is_lossy
    assert parsed.tracks[2].get_audio_format() == AudioFormat.DTS

    sample_file = test_dir / "test-data" / "sample-files" / "H264-DTS-HD-sample.mkv"
    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.DTS_HD
    assert parsed.tracks[2].get_audio_format() == AudioFormat.DTS_HD


def test_h264_dts_x():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-DTS-X-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.DTS_HD_X
    assert parsed.tracks[2].get_audio_format() == AudioFormat.AC3
    assert not parsed.tracks[1].get_audio_format().is_lossy
    assert parsed.tracks[2].get_audio_format().is_lossy


def test_h264_mp3_vorbis():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-MP3-Vorbis-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.MP3
    assert parsed.tracks[2].get_audio_format() == AudioFormat.VORBIS


def test_h264_pcm():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-PCM-sample.m2ts"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "mpegts"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.PCM


def test_h264_thd():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-THD-AC3-sample.m2ts"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "mpegts"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.TRUEHD
    assert parsed.tracks[2].get_audio_format() == AudioFormat.AC3


def test_h264_thd_atmos():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-THD-Atmos-PCM-DTS-HeadphoneX-sample.m2ts"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "mpegts"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.PCM
    assert parsed.tracks[2].get_audio_format() == AudioFormat.TRUEHD_ATMOS
    assert parsed.tracks[3].get_audio_format() == AudioFormat.AC3
    assert parsed.tracks[4].get_audio_format() == AudioFormat.AC3
    assert parsed.tracks[5].get_audio_format() == AudioFormat.TRUEHD
    assert parsed.tracks[6].get_audio_format() == AudioFormat.AC3
    assert parsed.tracks[7].get_audio_format() == AudioFormat.AC3
    assert parsed.tracks[8].get_audio_format() == AudioFormat.PCM
    assert parsed.tracks[9].get_audio_format() == AudioFormat.AC3
    # TODO: This is a DTS Headphone-X track. Currently neither ffmpeg nor mkvmerge can indicate this.
    assert parsed.tracks[10].get_audio_format() == AudioFormat.DTS_HD


def test_h264_xhe_aac():
    sample_file = test_dir / "test-data" / "sample-files" / "H264-xHE-AAC-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "h264"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.AAC_XHE
    assert parsed.tracks[2].get_audio_format() == AudioFormat.AAC_XHE


def test_h265_opus_aac():
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-AAC-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "hevc"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.OPUS
    assert parsed.tracks[2].get_audio_format() == AudioFormat.AAC
    assert parsed.tracks[3].get_audio_format() == AudioFormat.AAC


def test_h265_opus_eac3():
    sample_file = test_dir / "test-data" / "sample-files" / "H265-Opus-EAC3-sample.mkv"

    parsed = ParsedFile.from_file(sample_file)

    assert parsed.container_info.format_name == "matroska,webm"
    assert parsed.tracks[0].codec_name == "hevc"
    assert parsed.tracks[1].get_audio_format() == AudioFormat.OPUS
    assert parsed.tracks[1].container_delay == 0
    assert parsed.tracks[2].get_audio_format() == AudioFormat.EAC3
    assert parsed.tracks[2].container_delay == 13
    assert parsed.tracks[3].get_audio_format() == AudioFormat.EAC3
    assert parsed.tracks[3].container_delay == 13
