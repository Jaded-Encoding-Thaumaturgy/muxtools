import re
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typed_ffmpeg.ffprobe.schema import streamType

__all__ = ["AudioFormat", "FormatDefinition"]


@dataclass
class FormatDefinition:
    display_name: str
    codec_name: str
    codec_long_name: str
    is_lossy: bool
    ext: str | None = None
    profile: str | None = None

    @property
    def extension(self) -> str:
        if not self.ext:
            return self.codec_name.lower()

        return self.ext

    def __eq__(self, value: Any) -> bool:
        if isinstance(value, streamType):
            profile_matches = value.profile and self.profile and self.profile.casefold() == value.profile.casefold()
            if self.profile and not profile_matches:
                return False

            # Special case
            if self.display_name == "PCM" and value.codec_name and self.codec_name and "pcm" in value.codec_name:
                return re.match(self.codec_name.replace("*", ".*"), value.codec_name, re.I)
            else:
                codec_matches = value.codec_name and self.codec_name.casefold() == value.codec_name.casefold()
                codec_long_matches = value.codec_long_name and self.codec_long_name.casefold() == value.codec_long_name.casefold()

                if self.profile:
                    return profile_matches and (codec_matches or codec_long_matches)
                else:
                    return codec_matches and codec_long_matches
        else:
            return super.__eq__(self, value)


class AudioFormat(FormatDefinition, Enum):
    # Common lossy codecs
    AC3 = ("AC-3", "ac3", "ATSC A/52A (AC-3)", True)
    EAC3 = ("EAC-3", "eac3", "ATSC A/52B (AC-3, E-AC-3)", True)
    EAC3_ATMOS = ("EAC-3 Atmos", "eac3", "ATSC A/52B (AC-3, E-AC-3)", True, None, "Dolby Digital Plus + Dolby Atmos")
    AAC = ("AAC", "aac", "AAC (Advanced Audio Coding)", True)
    OPUS = ("Opus", "opus", "Opus (Opus Interactive Audio Codec)", True)
    VORBIS = ("Vorbis", "vorbis", "Vorbis", True, "ogg")
    MP3 = ("MP3", "mp3", "MP3 (MPEG audio layer 3)", True)

    # Common lossless codecs
    FLAC = ("FLAC", "flac", "FLAC (Free Lossless Audio Codec)", False)
    TRUEHD = ("TrueHD", "truehd", "TrueHD", False, "thd")
    TRUEHD_ATMOS = ("TrueHD Atmos", "truehd", "TrueHD", False, None, "Dolby TrueHD + Dolby Atmos")
    PCM = ("PCM", "pcm_*", "PCM *", False, "wav")

    # DTS Codecs
    DTS = ("DTS", "dts", "DCA (DTS Coherent Acoustics)", True)
    DTS_HD = ("DTS-HD MA", "dts", "DCA (DTS Coherent Acoustics)", False, None, "DTS-HD MA")
    DTS_HD_X = ("DTS-X", "dts", "DCA (DTS Coherent Acoustics)", False, None, "DTS-HD MA + DTS:X")
    DTS_HRA = ("DTS-HR", "dts", "DCA (DTS Coherent Acoustics)", True, None, "DTS-HD HRA")
    DTS_ES = ("DTS-ES", "dts", "DCA (DTS Coherent Acoustics)", True, None, "DTS-ES")

    def __new__(cls, *args, **kwargs):
        obj = object.__new__(cls)
        FormatDefinition.__init__(obj, *args, **kwargs)
        return obj

    @staticmethod
    def from_track(track: streamType) -> FormatDefinition | None:
        matched_by_profile: FormatDefinition | None = None
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
