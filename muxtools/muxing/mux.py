from shlex import join as joincommand
from pymediainfo import MediaInfo
from typing import Any
from shutil import rmtree
from pathlib import Path
import subprocess
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
from ..utils.log import debug, error, info, warn
from ..utils.download import get_executable
from ..utils.files import ensure_path, ensure_path_exists, get_crc32
from ..utils.env import get_setup_attr, get_setup_dir, get_workdir, run_commandline

__all__ = ["mux"]


def mux(*tracks, tmdb: TmdbConfig | None = None, outfile: PathLike | None = None, quiet: bool = True, print_cli: bool = False) -> PathLike:
    """
    Runs the mux.

    :param *tracks:     Any amount of track objects and a Chapters object
    :param tmdb:        A TMDB Config used for additional tagging if you so desire.
    :param outfile:     If you want to overwrite the output file path
    :param quiet:       Whether or not to print the mkvmerge output
    :param print_cli:   Print the final muxing command before running it if True
    """
    check_mkvmerge_version()
    tracks = list(tracks)
    out_dir = ensure_path(get_setup_attr("out_dir", "premux"), "Mux")
    args: list[str] = [get_executable("mkvmerge")]

    filename, mkvtitle = output_names(tmdb, args, tracks)

    if not outfile:
        outfile = Path(out_dir, f"{filename}.mkv")

    outfile = ensure_path(outfile, "Mux")

    args.extend(["-o", str(outfile)])

    for track in tracks:
        if isinstance(track, _track):
            args.extend(track.mkvmerge_args())
            continue
        elif isinstance(track, MuxingFile):
            if not isinstance(track, FontFile):
                warn("It's strongly recommended to pass tracks to ensure naming and tagging instead of MuxingFiles directly!", "Mux", 1)
            track = track.to_track()
            args.extend(track.mkvmerge_args())
            continue
        elif isinstance(track, Chapters):
            if not track.chapters:
                warn("Chapters are None or empty!", "Mux")
                continue

            args.extend(["--chapters", track.to_file()])
            continue
        elif isinstance(track, Path) or isinstance(track, str) or isinstance(track, GlobSearch):
            # Failsave for if someone passes Chapters().to_file() or a txt/xml file
            track = ensure_path_exists(track, "Mux")
            if track.suffix.lower() in [".txt", ".xml"]:
                args.extend(["--chapters", track.resolve()])
                continue
        elif track is None:
            continue

        raise error("Only _track, MuxingFiles or Chapters types are supported as muxing input!", "Mux")

    if mkvtitle:
        args.extend(["--title", mkvtitle])

    if print_cli:
        info(joincommand(args), "Mux")

    debug("Running the mux...", "Mux")
    if run_commandline(args, quiet, mkvmerge=True) > 1:
        raise error("Muxing failed!", "Mux")

    try:
        from importlib.metadata import version

        minfo = MediaInfo.parse(outfile, parse_speed=0.375)
        container_info = minfo.general_tracks[0]
        mkvpropedit = get_executable("mkvpropedit", False, False)
        muxtools_version = version("muxtools")
        version_tag = f" + muxtools v{muxtools_version}"
        if mkvpropedit and (muxing_application := getattr(container_info, "writing_library", None)) and "muxtools" not in muxing_application:
            args = [mkvpropedit, "--edit", "info", "--set", f"muxing-application={muxing_application + version_tag}", str(outfile.resolve())]
            run_commandline(args)
    except:
        pass

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


def clean_name(name: str) -> str:
    """
    This removes every unused token and delimiter aswell as empty brackets/parentheses.
    Ideally should be called before inserting the show name to not cause false positives with that.
    The .hack series would definitely cause some :)
    """
    stripped = name.strip()

    dont_match = [R"$show$", R"$ep$", "$crc32$"]
    for match in re.findall(r"\$[^ ]+\$", name):
        if match not in dont_match:
            stripped = stripped.replace(match, "").strip()
            warn(f"Unknown token '{match}' was removed.", "Mux")

    delimiters = ["-", "/"]
    if not stripped.endswith("..."):
        delimiters.append(".")

    while any([stripped.startswith(delim) for delim in delimiters]):
        stripped = stripped.lstrip("".join(delimiters)).strip()

    while any([stripped.endswith(delim) for delim in delimiters]):
        stripped = stripped.rstrip("".join(delimiters)).strip()

    stripped = stripped.replace("()", "")
    stripped = stripped.replace("[]", "")

    return stripped


def output_names(tmdb: TmdbConfig | None = None, args: list[str] = [], tracks: list[Any] = []) -> tuple[str, str]:
    show_name = get_setup_attr("show_name", "Example")
    episode = get_setup_attr("episode", "01")
    filename = get_setup_attr("out_name", R"$show$ - $ep$ (premux)")
    title = get_setup_attr("mkv_title_naming", R"$show$ - $ep$")

    try:
        if " " in episode:
            episode = str(episode).split(" ")[0]
        epint = int(episode)
    except:
        if tmdb and not tmdb.movie:
            warn(f"{episode} is not a valid integer! TMDB will be skipped.", "Mux", 3)
            tmdb = None
            filename = clean_name(re.sub(re.escape(R"$title$"), "", filename))
            title = clean_name(re.sub(re.escape(R"$title$"), "", title))

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
            title = re.sub(re.escape(R"$title$"), epmeta.title, title)

    for attribute in get_setup_dir():
        attr = get_setup_attr(attribute, None)
        if not attr or not isinstance(attr, str):
            continue
        try:
            replace = re.escape(Rf"${str(attribute)}$")
            filename = re.sub(replace, attr, filename)
            title = re.sub(replace, attr, title)
        except:
            continue

    filename = clean_name(filename)
    title = clean_name(title)

    filename = re.sub(re.escape(R"$show$"), show_name, filename)
    filename = re.sub(re.escape(R"$ep$"), episode, filename)
    filename = re.sub(re.escape(R"$crc32$"), "#crc32#", filename)

    title = re.sub(re.escape(R"$show$"), show_name, title)
    title = re.sub(re.escape(R"$ep$"), episode, title)

    return (filename, title)


def check_mkvmerge_version():
    out = subprocess.run([get_executable("mkvmerge"), "--version"], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    output = ((out.stderr or "") + (out.stdout or "")).strip()
    version_regex = re.compile(r".*mkvmerge v(?P<version>\d+(?:\.\d+)?).*", re.I)
    match = version_regex.match(output)
    try:
        if match:
            version = match.group("version")
            if version and float(version) < 77:
                warn("Please update your mkvtoolnix/mkvmerge for optimal behavior.", sleep=10)
    except:
        pass
