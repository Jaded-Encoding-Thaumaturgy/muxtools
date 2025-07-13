from pathlib import Path
from dataclasses import dataclass
from pymediainfo import MediaInfo, Track
from datetime import timedelta
from typing import Any

from .tracks import VideoTrack

from ..utils.log import error
from ..utils.glob import GlobSearch
from ..utils.env import run_commandline
from ..utils.download import get_executable
from ..utils.types import AudioInfo, PathLike, TrackType
from ..utils.files import ensure_path, ensure_path_exists
from ..utils.probe import TrackInfo, ContainerInfo, ParsedFile

__all__ = [
    "FileMixin",
    "MuxingFile",
    "VideoFile",
    "AudioFile",
]


@dataclass
class FileMixin:
    file: PathLike | list[PathLike] | GlobSearch
    container_delay: int = 0
    source: PathLike | None = None
    tags: dict[str, str] | None = None


@dataclass
class MuxingFile(FileMixin):
    from ..muxing.tracks import _track

    def __post_init__(self):
        self.file = ensure_path(self.file, self)

    def to_track(
        self,
        name: str = "",
        lang: str = "",
        default: bool | None = None,
        forced: bool | None = None,
        args: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> _track:
        from ..muxing.tracks import AudioTrack, SubTrack, Attachment
        from ..subtitle.sub import SubFile

        new_args = dict(
            file=self.file,
            name=name,
            delay=self.container_delay,
            default=True if default is None else default,
            forced=False if forced is None else forced,
            args=args,
            tags=tags or self.tags,
        )
        if isinstance(self, AudioFile):
            return AudioTrack(**new_args, lang=lang if lang else "ja")
        elif isinstance(self, SubFile):
            return SubTrack(**new_args, lang=lang if lang else "en")
        else:
            return Attachment(self.file)


@dataclass
class VideoFile(MuxingFile):
    def to_track(
        self,
        name: str = "",
        lang: str = "ja",
        default: bool = True,
        forced: bool = False,
        timecode_file: PathLike | GlobSearch | None = None,
        crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None,
        args: list[str] = [],
        tags: dict[str, str] | None = None,
    ):
        """
        :param timecode_file:       Pass a path for proper vfr playback if needed.
        :param crop:                Container based cropping with (horizontal, vertical) or (left, top, right, bottom).
                                    Will crop the same on all sides if passed a single integer.
        """
        return VideoTrack(self.file, name, lang, default, forced, self.container_delay, timecode_file, crop, args, tags or self.tags)


@dataclass
class AudioFile(MuxingFile):
    duration: timedelta | None = None
    container: ContainerInfo | None = None
    track_metadata: TrackInfo | None = None

    def __post_init__(self):
        self.file = ensure_path_exists(self.file, self)

    def get_containerinfo(self) -> ContainerInfo:
        if not self.container:
            parsed = ParsedFile.from_file(self.file, allow_mkvmerge_warning=False)
            if not parsed.container_info.nb_streams:
                raise error("No valid container found!", self)
            self.container = parsed.container_info
        return self.container

    def get_trackinfo(self) -> TrackInfo:
        if not self.track_metadata:
            parsed = ParsedFile.from_file(self.file, allow_mkvmerge_warning=False)
            self.track_metadata = parsed.find_tracks(relative_id=0, type=TrackType.AUDIO, error_if_empty=True)[0]

        return self.track_metadata

    def has_multiple_tracks(self, caller: Any = None) -> bool:
        return self.get_containerinfo().nb_streams > 1

    def to_mka(self, delete: bool = True, quiet: bool = True) -> Path:
        """
        Muxes the AudioFile to an MKA file with specified container delay applied.

        :param delete:      Deletes the current file after muxing
        :return:            Path object of the resulting mka file
        """
        mkv = get_executable("mkvmerge")
        self.file = ensure_path_exists(self.file, self)
        out = self.file.with_suffix(".mka")
        args = [mkv, "-o", str(out.resolve()), "--audio-tracks", "0"]
        if self.container_delay:
            args.extend(["--sync", f"0:{self.container_delay}"])
        args.append(str(self.file))
        if run_commandline(args, quiet) in [0, 1]:
            if delete:
                self.file.unlink()
            return out
        else:
            raise error("Failed to mux AudioFile to mka.", self)

    @staticmethod
    def from_file(pathIn: PathLike, caller: Any):
        from ..utils.log import warn

        file = ensure_path_exists(pathIn, caller)
        if file.suffix.lower() != ".wav":
            warn("It's strongly recommended to explicitly extract tracks first!", caller, 1)

        return AudioFile(file, 0, file)
