import re
from enum import Enum
from typing import Any, Optional
from typed_ffmpeg.ffprobe.schema import streamType

__all__ = ["AudioFormat"]


class AudioFormat(Enum):
    """
    A collection of somewhat common known audio formats.
    """

    display_name: str
    codec_name: str
    codec_long_name: str
    is_lossy: bool
    ext: str | None
    profile: str | None

    def __init__(self, display_name: str, codec_name: str, codec_long_name: str, is_lossy: bool, ext: str | None = None, profile: str | None = None):
        self._value_ = display_name
        self.display_name = display_name
        self.codec_name = codec_name
        self.codec_long_name = codec_long_name
        self.is_lossy = is_lossy
        self.ext = ext
        self.profile = profile

    @staticmethod
    def from_track(track: streamType) -> Optional["AudioFormat"]:
        matched_by_profile: AudioFormat | None = None
        for form in AudioFormat:
            if not form.profile:
                continue
            if form == track:
                matched_by_profile = form
                break

        if matched_by_profile:
            return matched_by_profile

        matches = [form for form in AudioFormat if not form.profile and form == track]
        return matches[0] if matches else None

    @property
    def extension(self) -> str:
        if not self.ext:
            return self.codec_name.lower()

        return self.ext

    def should_not_transcode(self) -> bool:
        if self.is_lossy:
            return True
        if self in (AudioFormat.DTS_HD_X, AudioFormat.TRUEHD_ATMOS):
            return True
        return False

    def __eq__(self, value: Any) -> bool:
        if isinstance(value, streamType):
            profile_matches = bool(value.profile and self.profile and self.profile.casefold() == value.profile.casefold())
            if self.profile and not profile_matches:
                return False

            # Special case
            if self.display_name == "PCM" and value.codec_name and self.codec_name and "pcm" in value.codec_name:
                return bool(re.match(self.codec_name.replace("*", ".*"), value.codec_name, re.I))
            else:
                codec_matches = bool(value.codec_name and self.codec_name.casefold() == value.codec_name.casefold())
                codec_long_matches = bool(value.codec_long_name and self.codec_long_name.casefold() == value.codec_long_name.casefold())

                if self.profile:
                    return profile_matches and (codec_matches or codec_long_matches)
                else:
                    return codec_matches and codec_long_matches
        else:
            return super().__eq__(value)

    # Common lossy codecs
    AC3 = "AC-3", "ac3", "ATSC A/52A (AC-3)", True
    """[Dolby Digital](https://en.wikipedia.org/wiki/Dolby_Digital)"""
    EAC3 = "EAC-3", "eac3", "ATSC A/52B (AC-3, E-AC-3)", True
    """[Dolby Digital Plus](https://en.wikipedia.org/wiki/Dolby_Digital_Plus)"""
    EAC3_ATMOS = "EAC-3 Atmos", "eac3", "ATSC A/52B (AC-3, E-AC-3)", True, None, "Dolby Digital Plus + Dolby Atmos"
    """[Dolby Digital Plus](https://en.wikipedia.org/wiki/Dolby_Digital_Plus) with [Atmos](https://en.wikipedia.org/wiki/Dolby_Atmos) metadata."""
    AAC = "AAC", "aac", "AAC (Advanced Audio Coding)", True
    """[Advanced Audio Coding](https://en.wikipedia.org/wiki/Advanced_Audio_Coding)"""
    AAC_XHE = "xHE-AAC", "aac", "AAC (Advanced Audio Coding)", True, None, "xHE-AAC"
    """
    A profile of AAC also sometimes known as [USAC](https://en.wikipedia.org/wiki/Unified_Speech_and_Audio_Coding).\n
    Compat for this is still not a given outside of mobile devices so transcoding may be recommended.
    """
    OPUS = "Opus", "opus", "Opus (Opus Interactive Audio Codec)", True
    """[Opus](https://en.wikipedia.org/wiki/Opus_(audio_format))"""
    VORBIS = "Vorbis", "vorbis", "Vorbis", True, "ogg"
    """[Vorbis](https://en.wikipedia.org/wiki/Vorbis)"""
    MP3 = "MP3", "mp3", "MP3 (MPEG audio layer 3)", True
    """[MPEG-1 Audio Layer III](https://en.wikipedia.org/wiki/MP3)"""

    # Common lossless codecs
    FLAC = "FLAC", "flac", "FLAC (Free Lossless Audio Codec)", False
    """[Free Lossless Audio Codec](https://en.wikipedia.org/wiki/FLAC)"""
    TRUEHD = "TrueHD", "truehd", "TrueHD", False, "thd"
    """[TrueHD](https://en.wikipedia.org/wiki/Dolby_TrueHD)"""
    TRUEHD_ATMOS = "TrueHD Atmos", "truehd", "TrueHD", False, "thd", "Dolby TrueHD + Dolby Atmos"
    """[TrueHD](https://en.wikipedia.org/wiki/Dolby_TrueHD) with [Atmos](https://en.wikipedia.org/wiki/Dolby_Atmos) metadata."""
    PCM = "PCM", "pcm_*", "PCM *", False, "wav"
    """[Pulse-code modulation](https://en.wikipedia.org/wiki/Pulse-code_modulation)"""

    # DTS Codecs
    DTS = "DTS", "dts", "DCA (DTS Coherent Acoustics)", True
    """[DTS](https://en.wikipedia.org/wiki/DTS,_Inc.#DTS_Digital_Surround)"""
    DTS_HD = "DTS-HD MA", "dts", "DCA (DTS Coherent Acoustics)", False, None, "DTS-HD MA"
    """
    [DTS-HD Master Audio](https://en.wikipedia.org/wiki/DTS-HD_Master_Audio)\n
    is the lossless extension for DTS.
    """
    DTS_HD_X = "DTS-X", "dts", "DCA (DTS Coherent Acoustics)", False, None, "DTS-HD MA + DTS:X"
    """[DTS-HD MA](https://en.wikipedia.org/wiki/DTS-HD_Master_Audio) with metadata for object-based surround sound similar to Atmos."""
    DTS_HRA = "DTS-HR", "dts", "DCA (DTS Coherent Acoustics)", True, None, "DTS-HD HRA"
    """Another lossy DTS variant with the supposed purpose of being higher bitrate and quality than DTS but still being substantially lower in size than lossless MA."""
    DTS_ES = "DTS-ES", "dts", "DCA (DTS Coherent Acoustics)", True, None, "DTS-ES"
    """Another lossy DTS variant that I honestly have no idea about in terms of what it's supposed to be used for."""
