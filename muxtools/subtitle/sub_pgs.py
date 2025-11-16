from typing_extensions import Self
from video_timestamps import TimeType
from shutil import move

from ..utils import (
    ParsedFile,
    make_output,
    get_executable,
    run_commandline,
    error,
    clean_temp_files,
    resolve_timesource_and_scale,
    ensure_path,
    info,
    GlobSearch,
)
from ..utils.types import PathLike, TimeSourceT, TimeScaleT, TrackType
from ..muxing.muxfiles import MuxingFile
from ..muxing.tracks import SubTrack

__all__ = ["SubFilePGS"]


class SubFilePGS(MuxingFile):
    """
    Utility class representing a PGS/SUP subtitle file.
    """

    def __init__(
        self,
        file: PathLike | list[PathLike] | GlobSearch,
        container_delay: int = 0,
        source: PathLike | None = None,
        tags: dict[str, str] | None = None,
    ):
        """
        :param file:            Can be a string, Path object or GlobSearch.
        :param container_delay: Set a container delay used in the muxing process later.
        :param source:          The file this sub originates from.
        :param tags:            Custom matroska tags to assign to this as a track later on.
        """
        super().__init__(file, container_delay, source, tags)
        parsed = ParsedFile.from_file(self.file, self)
        parsed_track = parsed.find_tracks(type=TrackType.SUB, relative_id=0, error_if_empty=True, caller=self)[0]
        if parsed_track.codec_name.lower() != "hdmv_pgs_subtitle":
            raise error(f"The passed file is not a PGS subtitle file. ({parsed_track.codec_name})", caller=self)

    def to_track(
        self,
        name: str = "",
        lang: str = "en",
        default: bool | None = None,
        forced: bool | None = None,
        args: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> SubTrack:
        return SubTrack(self.file, name, lang, default or True, forced or False, self.container_delay, args, tags or self.tags)

    def shift(self, shift: int, shift_is_ms: bool = False, timesource: TimeSourceT = None, timescale: TimeScaleT = None, quiet: bool = True) -> Self:
        """
        Shifts all lines by any frame number with supmover.

        :param shift:               Number of frames to shift by
        :param shift_is_ms:         If True, the shift is in milliseconds.
        :param timesource:          The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                    For details check the docstring on the type.
        :param quiet:               If True, suppresses supmover output.
        """
        supmover = get_executable("SupMover")
        out = make_output(self.file, "sup", temp=True)
        fileIn = ensure_path(self.file, self)
        args = [supmover, str(fileIn), str(out), "--delay"]
        if shift_is_ms:
            args.append(str(shift))
        else:
            resolved_ts = resolve_timesource_and_scale(timesource, timescale, fetch_from_setup=True, caller=self)
            ms = resolved_ts.frame_to_time(abs(shift), TimeType.START, 3)
            args.append(str(ms) if shift >= 0 else f"-{ms}")

        if run_commandline(args, quiet):
            clean_temp_files()
            raise error("Failed to shift subtitle file.", caller=self)

        fileIn.unlink(missing_ok=True)
        move(out, fileIn)
        clean_temp_files()
        return self

    @classmethod
    def extract_from(cls: type[Self], fileIn: PathLike, track: int = 0, preserve_delay: bool = False, quiet: bool = True) -> Self:
        """
        Extract a PGS subtitle track from a file using ffmpeg.\n

        :param fileIn:          The input file to extract from.
        :param track:           The track number to extract.
        :param preserve_delay:  If True, the container delay will be preserved.
        :param quiet:           If True, suppresses ffmpeg output.
        :return:                An instance of SubFilePGS containing the extracted subtitle.
        """
        caller = "SubFilePGS.extract_from"
        parsed = ParsedFile.from_file(fileIn, caller)
        parsed_track = parsed.find_tracks(type=TrackType.SUB, relative_id=track, error_if_empty=True, caller=caller)[0]

        if parsed_track.codec_name.lower() != "hdmv_pgs_subtitle":
            raise error(f"The specified track is not a PGS subtitle. ({parsed_track.codec_name})", caller=caller)

        info(f"Extracting PGS subtitle track {track} from '{parsed.source.name}'", caller=caller)
        ffmpeg = get_executable("ffmpeg")

        out = make_output(fileIn, "sup", str(parsed_track.index))
        args = [ffmpeg, "-hide_banner", "-i", str(parsed.source), "-map", f"0:s:{str(track)}", "-c", "copy", str(out)]
        if run_commandline(args, quiet):
            raise error("Failed to extract subtitle track from file.", caller=caller)

        delay = 0 if not preserve_delay else parsed_track.container_delay

        return cls(out, delay, fileIn)
