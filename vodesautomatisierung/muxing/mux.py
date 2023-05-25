from shlex import split as splitcommand
from pathlib import Path
import wget
import re


from .tmdb import TmdbConfig
from ..subtitle.sub import SubFile
from ..utils.types import PathLike
from ..utils.glob import GlobSearch
from ..utils.log import debug, error, warn
from ..misc.chapters import Chapters
from ..utils.env import get_setup_attr, get_workdir, run_commandline
from ..utils.download import get_executable
from .tracks import Attachment, AudioTrack, SubTrack, VideoTrack, _track
from ..utils.files import AudioFile, FontFile, MuxingFile, VideoFile, ensure_path, ensure_path_exists, get_crc32


def mux(*tracks, tmdb: TmdbConfig | None = None, outfile: PathLike | None = None, quiet: bool = True) -> PathLike:
    tracks = list(tracks)
    show_name = get_setup_attr("show_name", "Example")
    out_name = get_setup_attr("out_name", R"$show$ - $ep$ (premux)")
    out_dir = ensure_path(get_setup_attr("out_dir", "premux"), "Mux")
    mkv_title_naming = get_setup_attr("mkv_title_naming", R"$show$ - $ep$")
    args: list[str] = [get_executable("mkvmerge")]
    episode = get_setup_attr("episode", "01")

    filename = re.sub(re.escape(R"$show$"), show_name, out_name)
    filename = re.sub(re.escape(R"$ep$"), episode, filename)
    filename = re.sub(re.escape(R"$crc32$"), "#crc32#", filename)

    mkvtitle = re.sub(re.escape(R"$show$"), show_name, mkv_title_naming)
    mkvtitle = re.sub(re.escape(R"$ep$"), episode, mkvtitle)

    try:
        epint = int(episode)
    except:
        if tmdb and not tmdb.movie:
            warn(f"{episode} is not a valid integer! TMDB will be skipped.", "Mux", 3)
            tmdb = None
    if tmdb:
        debug("Fetching tmdb metadata...", "Mux")
        mediameta = tmdb.get_media_meta()
        epmeta = tmdb.get_episode_meta(epint) if not tmdb.movie else None
        if tmdb.needs_xml():
            xml = tmdb.make_xml(mediameta, epmeta)
            args.extend(["--global-tags", xml])

        if not tmdb.movie:
            if tmdb.write_cover and epmeta.thumb_url:
                cover = Path(get_workdir(), f"cover_land{Path(epmeta.thumb_url).suffix}")
                if wget.download(epmeta.thumb_url, str(cover), None):
                    tracks.append(Attachment(cover, "image/jpeg" if cover.suffix.lower() == ".jpg" else "image/png"))

            filename = re.sub(re.escape(R"$title$"), epmeta.title, filename)
            mkvtitle = re.sub(re.escape(R"$title$"), epmeta.title, mkvtitle)

    if not outfile:
        outfile = Path(out_dir, f"{filename}.mkv")

    outfile = ensure_path(outfile, "Mux")

    args.extend(["-o", str(outfile)])

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

    if mkvtitle:
        args.extend(["--title", mkvtitle])

    debug("Running the mux...", "Mux")
    result = run_commandline(args, quiet)

    if "#crc32#" in outfile.stem:
        debug("Generating CRC32 for the muxed file...", "Mux")
        outfile = outfile.rename(outfile.with_stem(re.sub(re.escape("#crc32#"), get_crc32(outfile), outfile.stem)))

    debug("Done", "Mux")
    return outfile


def track_for_file(mf: MuxingFile) -> _track:
    if isinstance(mf, VideoFile):
        return VideoTrack(mf)
    elif isinstance(mf, AudioFile):
        return AudioTrack(mf)
    elif isinstance(mf, SubFile):
        return SubTrack(mf)
    else:
        return Attachment(mf)
