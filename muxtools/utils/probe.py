import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Callable
from typed_ffmpeg import probe_obj
from typed_ffmpeg.ffprobe.schema import streamType, ffprobeType, tagsType, formatType
from mkvinfo import MKVInfo, Track as MkvInfoTrack, Container as MkvInfoContainer
from itertools import groupby

from .log import error, warn
from .types import PathLike, TrackType
from .files import ensure_path_exists
from .download import get_executable
from .formats import AudioFormat

__all__ = ["ParsedFile", "TrackInfo", "ContainerInfo"]


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
    type: TrackType
    codec_name: str
    codec_long_name: str | None
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
        if not self.type == TrackType.AUDIO:
            return None
        return AudioFormat.from_track(self.raw_ffprobe)

    @property
    def bit_depth(self) -> int | None:
        raw_bits = self.raw_ffprobe.bits_per_raw_sample
        if self.type == TrackType.AUDIO:
            sample_fmt = self.raw_ffprobe.sample_fmt
            if raw_bits:
                return raw_bits
            elif sample_fmt and sample_fmt.lower() in ["s32", "s32p"]:
                return 24
            elif sample_fmt and sample_fmt.lower() in ["s16", "s16p"]:
                return 16
            else:
                return None
        else:
            return raw_bits if raw_bits else self.raw_ffprobe.bits_per_sample


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
    source: Path

    raw_ffprobe: ffprobeType
    raw_mkvmerge: MKVInfo | None

    @staticmethod
    def from_file(path: PathLike, caller: Any | None = None, allow_mkvmerge_warning: bool = True) -> Optional["ParsedFile"]:
        """
        Parses a file with ffprobe and, if given and a video track is found, mkvmerge.

        :param path:                    Any file.
        :param caller:                  Caller used for logging. Mostly intended for internal use.
        :param allow_mkvmerge_warning:  If the warning for a missing mkvmerge install should actually be printed.\n
                                        Again, for internal use.
        """
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

                track_type = [ttype for ttype in TrackType if ttype.name.lower() in type.lower()]
                if not track_type:
                    raise error(f"Unknown track type for '{type}' in '{path.stem}'!", caller)

                trackinfo = TrackInfo(
                    index=track.index,
                    relative_index=i,
                    codec_name=track.codec_name,
                    codec_long_name=track.codec_long_name,
                    type=track_type[0],
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

        return ParsedFile(container_info, tracks, is_video_file, path, out, mkvmerge_out)

    def find_tracks(
        self,
        name: str | None = None,
        lang: str | None = None,
        type: TrackType | None = None,
        relative_id: int | list[int] | None = None,
        use_regex: bool = True,
        reverse_lang: bool = False,
        custom_condition: Callable[[TrackInfo], bool] | None = None,
        error_if_empty: bool = False,
        caller: Any | None = None,
    ) -> list[TrackInfo]:
        """
        Convenience function to find tracks with some conditions.

        :param name:                Name to match, case insensitively and preceeding/leading whitespace removed.
        :param lang:                Language to match. This can be any of the possible formats like English/eng/en and is case insensitive.
        :param type:                Track Type to search for.
        :param relative_id:         What relative (to the type) indices the tracks should have.
        :param use_regex:           Use regex for the name search instead of checking for equality.
        :param reverse_lang:        If you want the `lang` param to actually exclude that language.
        :param custom_condition:    Here you can pass any function to create your own conditions. (They have to return a bool)\n
                                    For example: `custom_condition=lambda track: track.codec_name == "eac3"`
        :param error_if_empty:      Throw an error instead of returning an empty list if nothing was found for the given conditions.
        :param caller:              Caller to use for logging. Mostly intended for internal use.
        """

        if not name and not lang and not type and relative_id is None and custom_condition is None:
            return []
        if relative_id is not None and type is None:
            raise error("You can only search for a relative id with a specific track type!", caller or self.find_tracks)

        tracks = self.tracks

        def name_matches(title: str) -> bool:
            if title.casefold().strip() == name.casefold().strip():
                return True
            if use_regex:
                return re.match(name, title, re.I)
            return False

        def get_languages(track: TrackInfo) -> list[str]:
            languages = list[str | None]()
            languages.append(track.language)
            if track.raw_mkvmerge:
                languages.append(track.raw_mkvmerge.properties.language)
                languages.append(track.raw_mkvmerge.properties.language_ietf)
            return [lang.casefold() for lang in languages if lang]

        if name:
            tracks = [track for track in tracks if name_matches(track.title or "")]

        if lang:
            if reverse_lang:
                tracks = [track for track in tracks if lang.casefold() not in get_languages(track)]
            else:
                tracks = [track for track in tracks if lang.casefold() in get_languages(track)]

        if type:
            if type not in (TrackType.VIDEO, TrackType.AUDIO, TrackType.SUB):
                raise error("You can only search for video, audio and subtitle tracks!", caller or self.find_tracks)
            tracks = [track for track in tracks if track.type == type]

        if relative_id is not None:
            if not isinstance(relative_id, list):
                relative_id = [relative_id]
            tracks = [track for track in tracks if track.relative_index in relative_id]

        if custom_condition:
            tracks = [track for track in tracks if custom_condition(track)]

        if not tracks and error_if_empty:
            raise error(f"Could not find requested track in '{self.source.name}'!", caller or self.find_tracks)

        return tracks
