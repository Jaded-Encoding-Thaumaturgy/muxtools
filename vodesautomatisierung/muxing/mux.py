from shlex import split as splitcommand
from pathlib import Path
import re

from ..subtitle.sub import SubFile
from ..utils.types import PathLike
from ..utils.glob import GlobSearch
from ..utils.log import error, warn
from ..misc.chapters import Chapters
from ..utils.env import get_setup_attr
from ..utils.download import get_executable
from .tracks import Attachment, AudioTrack, SubTrack, VideoTrack, _track
from ..utils.files import AudioFile, FontFile, MuxingFile, VideoFile, ensure_path, ensure_path_exists


def mux(*tracks, tmdb: int = 0, movie: bool = False, season: int = 1, outfile: PathLike | None = None, quiet: bool = True, **kwargs):
    show_name = get_setup_attr("show_name", "Example")
    out_name = get_setup_attr("out_name", R"$show$ - $ep$ (premux)")
    out_dir = ensure_path(get_setup_attr("out_dir", "premux"), "Mux")
    mkv_title_naming = get_setup_attr("mkv_title_naming", R"$show$ - $ep$")
    args: list[str] = [get_executable("mkvmerge")]

    if not outfile:
        episode = get_setup_attr("episode", "01")
        filename = re.sub(R"$show$", show_name, out_name)
        filename = re.sub(R"$ep$", episode, filename)
        filename = re.sub(R"$crc32$", "#crc32#", filename)
        outfile = Path(out_dir, filename)

        mkvtitle = re.sub(R"$show$", show_name, mkv_title_naming)
        mkvtitle = re.sub(R"$ep$", episode, mkvtitle)

    for track in tracks:
        if isinstance(track, _track):
            args.extend(splitcommand(track.mkvmerge_args()))
            continue
        elif isinstance(track, MuxingFile):
            if not isinstance(track, FontFile):
                warn("It's strongly recommended to pass tracks to ensure naming and tagging instead of MuxingFiles directly!", "Mux", 1)
            track = track_for_file(track)
            args.extend(splitcommand(track.mkvmerge_args()))
            continue
        elif isinstance(track, Chapters):
            args.extend(["--chapters", track.to_file()])
            continue
        elif isinstance(track, PathLike) or isinstance(track, GlobSearch):
            # Failsave for if someone passes Chapters().to_file() or a txt/xml file
            track = ensure_path_exists(track, "Mux")
            if track.suffix.lower() in [".txt", ".xml"]:
                args.extend(["--chapters", track.resolve()])
                continue

        raise error("Only _track, MuxingFiles or Chapters types are supported as muxing input!", "Mux")


def track_for_file(mf: MuxingFile) -> _track:
    if isinstance(mf, VideoFile):
        return VideoTrack(mf)
    elif isinstance(mf, AudioFile):
        return AudioTrack(mf)
    elif isinstance(mf, SubFile):
        return SubTrack(mf)
    else:
        return Attachment(mf)
