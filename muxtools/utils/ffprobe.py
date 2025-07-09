import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from typed_ffmpeg import probe_obj
from typed_ffmpeg.ffprobe.schema import streamType, ffprobeType, tagsType, formatType
from mkvinfo import MKVInfo, Track as MkvInfoTrack, Container as MkvInfoContainer
from itertools import groupby

from .log import error, warn
from .types import PathLike
from .files import ensure_path_exists
from .download import get_executable

__all__ = ["AudioFormat"]


@dataclass
class ContainerInfo:
    nb_streams: int
    format_name: str
    format_long_name: str | None
    tags: dict[str, str]

    raw_ffprobe: formatType
    raw_mkvmerge: MkvInfoContainer | None


@dataclass
class TrackInfo:
    index: int
    relative_index: int
    codec_name: str
    codec_long_name: str | None
    codec_type: str
    profile: str | None

    language: str | None
    title: str | None
    is_default: bool
    is_forced: bool
    container_delay: int

    other_tags: dict[str, str]
    raw_ffprobe: streamType
    raw_mkvmerge: MkvInfoTrack | None

    def get_audio_format(self) -> Optional["AudioFormat"]:
        if not self.codec_type.lower() == "audio":
            return None
        return AudioFormat.from_track(self.raw_ffprobe)


def tags_to_dict(tags: tagsType | None) -> dict[str, str]:
    if not tags:
        return dict()
    new_dict = dict[str, str]()
    for tag in tags.tag:
        if not tag.key:
            continue
        new_dict[tag.key] = tag.value or ""
    return new_dict


@dataclass
class ParsedFile:
    container_info: ContainerInfo
    tracks: list[TrackInfo]
    is_video_file: bool

    raw_ffprobe: ffprobeType
    raw_mkvmerge: MKVInfo | None

    @staticmethod
    def from_file(path: PathLike, caller: Any | None = None, allow_mkvmerge_warning: bool = True) -> Optional["ParsedFile"]:
        path = ensure_path_exists(path, caller)
        ffprobe_exe = get_executable("ffprobe")
        try:
            out = probe_obj(path, cmd=ffprobe_exe)
            assert out
        except:
            raise error(f"Failed to parse file '{path.stem}' with ffprobe!", caller)

        if not out.streams or not out.streams.stream or not out.format or "tty" in out.format.format_name:
            return None

        is_video_file = bool([stream for stream in out.streams.stream if (stream.codec_type or "").lower() == "video"])
        container_info = ContainerInfo(
            out.format.nb_streams or 0, out.format.format_name or "", out.format.format_long_name, tags_to_dict(out.format.tags), out.format, None
        )
        mkvmerge_exe = get_executable("mkvmerge", can_error=False)
        mkvmerge_out = None
        if not mkvmerge_exe and is_video_file:
            if allow_mkvmerge_warning:
                warn("Could not find mkvmerge. This is required to parse any container-delay, so beware!", caller)
        elif is_video_file:
            try:
                mkvmerge_out = MKVInfo.from_file(path, mkvmerge=mkvmerge_exe)
                container_info.raw_mkvmerge = mkvmerge_out.container
            except:
                warn("Could not parse file with mkvmerge!", caller)

        sorted_streams = sorted(out.streams.stream, key=lambda s: -1 if not s.index else s.index)
        tracks = list[TrackInfo]()
        for type, values in groupby(sorted_streams, lambda v: v.codec_type):
            if not type:
                raise error(f"Could not get codec_type for some tracks in '{path.stem}'!", caller)
            for i, track in enumerate(values):
                mkvmerge_meta = None
                if mkvmerge_out and type in ["video", "audio", "subtitle"]:
                    found = [tr for tr in mkvmerge_out.tracks if tr.id == track.index and type in tr.type.name.lower()]
                    mkvmerge_meta = found[0] if found else None
                if not track.codec_name:
                    raise error(f"Track {track.index} in '{path.stem}' does not have a codec_name!", caller)
                is_default = bool(track.disposition.default) if track.disposition and track.disposition.default else False
                is_forced = bool(track.disposition.forced) if track.disposition and track.disposition.forced else False
                container_delay = 0
                if mkvmerge_out and mkvmerge_meta and mkvmerge_meta.properties.minimum_timestamp:
                    timescale = mkvmerge_out.container.properties.timestamp_scale
                    if timescale is None:
                        warn(f"Mkvmerge could not get a timestamp_scale from '{path.stem}'! Ignoring any possible container delays.", caller)
                    else:
                        min_timestamp = mkvmerge_meta.properties.minimum_timestamp / timescale
                        if mkvmerge_meta.properties.codec_delay:
                            min_timestamp = max(min_timestamp - (mkvmerge_meta.properties.codec_delay / timescale), 0)
                        container_delay = int(min_timestamp)

                tags = tags_to_dict(track.tags)
                language = tags.pop("language", None)
                title = tags.pop("title", None)

                trackinfo = TrackInfo(
                    index=track.index,
                    relative_index=i,
                    codec_name=track.codec_name,
                    codec_long_name=track.codec_long_name,
                    codec_type=type,
                    profile=track.profile,
                    language=language,
                    title=title,
                    is_default=is_default,
                    is_forced=is_forced,
                    container_delay=container_delay,
                    other_tags=tags,
                    raw_ffprobe=track,
                    raw_mkvmerge=mkvmerge_meta,
                )
                tracks.append(trackinfo)

        return ParsedFile(container_info, tracks, is_video_file, out, mkvmerge_out)


class AudioFormat(Enum):
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

    def __eq__(self, value: Any) -> bool:
        if isinstance(value, streamType):
            profile_matches = value.profile and self.profile and self.profile.casefold() == value.profile.casefold()
            if self.profile and not profile_matches:
                return False

            # Special case
            if self.display_name == "PCM" and value.codec_name and self.codec_name and "pcm" in value.codec_name:
                return bool(re.match(self.codec_name.replace("*", ".*"), value.codec_name, re.I))
            else:
                codec_matches = value.codec_name and self.codec_name.casefold() == value.codec_name.casefold()
                codec_long_matches = value.codec_long_name and self.codec_long_name.casefold() == value.codec_long_name.casefold()

                if self.profile:
                    return profile_matches and (codec_matches or codec_long_matches)
                else:
                    return codec_matches and codec_long_matches
        else:
            return super.__eq__(self, value)

    # Common lossy codecs
    AC3 = "AC-3", "ac3", "ATSC A/52A (AC-3)", True
    EAC3 = "EAC-3", "eac3", "ATSC A/52B (AC-3, E-AC-3)", True
    EAC3_ATMOS = "EAC-3 Atmos", "eac3", "ATSC A/52B (AC-3, E-AC-3)", True, None, "Dolby Digital Plus + Dolby Atmos"
    AAC = "AAC", "aac", "AAC (Advanced Audio Coding)", True
    AAC_XHE = "xHE-AAC", "aac", "AAC (Advanced Audio Coding)", True, None, "xHE-AAC"
    OPUS = "Opus", "opus", "Opus (Opus Interactive Audio Codec)", True
    VORBIS = "Vorbis", "vorbis", "Vorbis", True, "ogg"
    MP3 = "MP3", "mp3", "MP3 (MPEG audio layer 3)", True

    # Common lossless codecs
    FLAC = "FLAC", "flac", "FLAC (Free Lossless Audio Codec)", False
    TRUEHD = "TrueHD", "truehd", "TrueHD", False, "thd"
    TRUEHD_ATMOS = "TrueHD Atmos", "truehd", "TrueHD", False, None, "Dolby TrueHD + Dolby Atmos"
    PCM = "PCM", "pcm_*", "PCM *", False, "wav"

    # DTS Codecs
    DTS = "DTS", "dts", "DCA (DTS Coherent Acoustics)", True
    DTS_HD = "DTS-HD MA", "dts", "DCA (DTS Coherent Acoustics)", False, None, "DTS-HD MA"
    DTS_HD_X = "DTS-X", "dts", "DCA (DTS Coherent Acoustics)", False, None, "DTS-HD MA + DTS:X"
    DTS_HRA = "DTS-HR", "dts", "DCA (DTS Coherent Acoustics)", True, None, "DTS-HD HRA"
    DTS_ES = "DTS-ES", "dts", "DCA (DTS Coherent Acoustics)", True, None, "DTS-ES"
