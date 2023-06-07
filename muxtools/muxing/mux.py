from shlex import split as splitcommand
from shutil import rmtree
from pathlib import Path
import wget
import re
import os


from .tmdb import TmdbConfig
from .muxfiles import MuxingFile
from ..utils.types import PathLike
from ..subtitle.sub import FontFile
from ..utils.glob import GlobSearch
from ..misc.chapters import Chapters
from .tracks import Attachment, _track
from ..utils.log import debug, error, warn
from ..utils.download import get_executable
from ..utils.files import ensure_path, ensure_path_exists, get_crc32
from ..utils.env import get_setup_attr, get_workdir, run_commandline

__all__ = ["mux"]


def mux(*tracks, tmdb: TmdbConfig | None = None, outfile: PathLike | None = None, quiet: bool = True) -> PathLike:
    """
    Runs the mux.

    :param *tracks:     Any amount of track objects and a Chapters object
    :param tmdb:        A TMDB Config used for additional tagging if you so desire.
    :param outfile:     If you want to overwrite the output file path
    :param quiet:       Whether or not to print the mkvmerge output
    """

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
        if " " in episode:
            episode = str(episode).split(" ")[0]
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
            track = track.to_track()
            args.extend(splitcommand(track.mkvmerge_args()))
            continue
        elif isinstance(track, Chapters):
            args.extend(["--chapters", track.to_file()])
            continue
        elif isinstance(track, Path) or isinstance(track, str) or isinstance(track, GlobSearch):
            # Failsave for if someone passes Chapters().to_file() or a txt/xml file
            track = ensure_path_exists(track, "Mux")
            if track.suffix.lower() in [".txt", ".xml"]:
                args.extend(["--chapters", track.resolve()])
                continue

        raise error("Only _track, MuxingFiles or Chapters types are supported as muxing input!", "Mux")

    if mkvtitle:
        args.extend(["--title", mkvtitle])

    debug("Running the mux...", "Mux")
    if run_commandline(args, quiet) > 1:
        raise error("Muxing failed!", "Mux")

    if "#crc32#" in outfile.stem:
        debug("Generating CRC32 for the muxed file...", "Mux")
        outfile = outfile.rename(outfile.with_stem(re.sub(re.escape("#crc32#"), get_crc32(outfile), outfile.stem)))

    if get_setup_attr("clean_work_dirs", False):
        if os.path.samefile(get_workdir(), os.getcwd()):
            error("Clearing workdir not supported when your workdir is cwd.", "Mux")
        else:
            rmtree(get_workdir())

    debug("Done", "Mux")
    return outfile
