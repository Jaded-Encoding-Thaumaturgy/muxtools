from pathlib import Path
from datetime import timedelta
from typing import Any, Sequence
from abc import abstractmethod

from .tracks import AudioTrack, VideoTrack, _track

from ..utils.log import error
from ..utils.glob import GlobSearch
from ..utils.env import run_commandline
from ..utils.download import get_executable
from ..utils.types import PathLike, TrackType, FileMixin
from ..utils.files import ensure_path, ensure_path_exists
from ..utils.probe import TrackInfo, ContainerInfo, ParsedFile

__all__ = [
    "MuxingFile",
    "VideoFile",
    "AudioFile",
]


class MuxingFile(FileMixin):
    def __init__(
        self,
        file: PathLike | Sequence[PathLike] | GlobSearch,
        container_delay: int = 0,
        source: PathLike | None = None,
        tags: dict[str, str] | None = None,
    ):
        super().__init__(ensure_path(file, self), container_delay, source, tags)

    @abstractmethod
    def to_track(self, *args) -> _track: ...


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
    ) -> VideoTrack:
        """
        :param timecode_file:       Pass a path for proper vfr playback if needed.
        :param crop:                Container based cropping with (horizontal, vertical) or (left, top, right, bottom).
                                    Will crop the same on all sides if passed a single integer.
        """
        return VideoTrack(self.file, name, lang, default, forced, self.container_delay, timecode_file, crop, args, tags or self.tags)


class AudioFile(MuxingFile):
    duration: timedelta | None = None
    container: ContainerInfo | None = None
    track_metadata: TrackInfo | None = None

    def __init__(
        self,
        file: PathLike | Sequence[PathLike] | GlobSearch,
        container_delay: int = 0,
        source: PathLike | None = None,
        tags: dict[str, str] | None = None,
        duration: timedelta | None = None,
    ):
        super().__init__(ensure_path(file, self), container_delay, source, tags)
        self.duration = duration

    def __post_init__(self):
        self.file = ensure_path_exists(self.file, self)

    def to_track(
        self,
        name: str = "",
        lang: str = "ja",
        default: bool = True,
        forced: bool = False,
        args: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> AudioTrack:
        return AudioTrack(self.file, name, lang, default, forced, self.container_delay, args, tags or self.tags)

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
    def from_file(pathIn: PathLike, caller: Any) -> "AudioFile":
        from ..utils.log import warn

        file = ensure_path_exists(pathIn, caller)
        if file.suffix.lower() != ".wav":
            warn("It's strongly recommended to explicitly extract tracks first!", caller, 1)

        return AudioFile(file, 0, file)
