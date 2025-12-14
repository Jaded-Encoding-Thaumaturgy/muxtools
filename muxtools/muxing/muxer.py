from shlex import join as joincommand
from shutil import rmtree
from pathlib import Path
import subprocess
import wget  # type: ignore[import-untyped]
import re
import os


from .tmdb import TmdbConfig
from .muxfiles import MuxingFile
from .token_handling import apply_dynamic_tokens, replace_with_temp_tokens
from ..utils.types import PathLike
from ..subtitle.sub import FontFile
from ..utils.glob import GlobSearch
from ..misc.chapters import Chapters
from .tracks import Attachment, _track
from ..utils.download import get_executable
from ..utils.log import debug, error, info, warn, danger
from ..utils.env import get_setup_attr, get_setup_dir, get_workdir, run_commandline
from ..utils.files import ensure_path, ensure_path_exists, get_crc32, clean_temp_files
from ..utils.probe import ParsedFile

__all__ = ["mux"]


writing_lib_regex = re.compile(r"libebml.v(\d.\d.\d).+?libmatroska.v(\d.\d.\d)", re.I)


def mux(*tracks: _track, tmdb: TmdbConfig | None = None, outfile: PathLike | None = None, quiet: bool = True, print_cli: bool = False) -> Path:
    """
    Runs the mux.

    :param *tracks:     Any amount of track objects and a Chapters object
    :param tmdb:        A TMDB Config used for additional tagging if you so desire.
    :param outfile:     If you want to overwrite the output file path
    :param quiet:       Whether or not to print the mkvmerge output
    :param print_cli:   Print the final muxing command before running it if True
    """
    check_mkvmerge_version()
    tracklist = list(tracks)
    out_dir = ensure_path(get_setup_attr("out_dir", "premux"), "Mux")
    args: list[str] = [get_executable("mkvmerge")]

    filename, mkvtitle = output_names(tmdb, args, tracklist)

    if not outfile:
        outfile = Path(out_dir, f"{filename}.mkv")

    outfile = ensure_path(outfile, "Mux")

    args.extend(["-o", str(outfile)])

    for track in tracklist:
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

            args.extend(["--chapters", str(track.to_file())])
            continue
        elif isinstance(track, Path) or isinstance(track, str) or isinstance(track, GlobSearch):
            # Failsave for if someone passes Chapters().to_file() or a txt/xml file
            track = ensure_path_exists(track, "Mux")
            if track.suffix.lower() in [".txt", ".xml"]:
                args.extend(["--chapters", str(track.resolve())])
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

    if not get_setup_attr("skip_mux_branding", False):
        try:
            parsed = ParsedFile.from_file(outfile, "Mux")
            tags = parsed.container_info.tags
            if not tags:
                debug("File does not contain writing library tags. Skipping the muxtools branding.", "Mux")

            mkvpropedit = get_executable("mkvpropedit", False, False)
            if not mkvpropedit:
                warn("Mkvpropedit could not be found!", "Mux", 0)

            from muxtools import __version__

            version_tag = f" + muxtools v{__version__}"

            muxing_application = tags.get("encoder", None)

            if mkvpropedit and muxing_application and (match := writing_lib_regex.search(muxing_application)):
                muxing_application = f"libebml v{match.group(1)} + libmatroska v{match.group(2)}" + version_tag
                args = [mkvpropedit, "--edit", "info", "--set", f"muxing-application={muxing_application}", str(outfile.resolve())]
                if run_commandline(args, mkvmerge=True) > 1:
                    danger("Failed to add muxtools information via mkvpropedit!", "Mux")
        except Exception as e:
            print(e)
            danger("Failed to add muxtools information via mkvpropedit!", "Mux")

    new_name = apply_dynamic_tokens(outfile.name, outfile, True, caller="Mux")
    if outfile.name != new_name:
        outfile = outfile.rename(outfile.parent / new_name)

    if "#crc32#" in outfile.stem:
        debug("Generating CRC32 for the muxed file...", "Mux")
        outfile = outfile.rename(outfile.with_stem(re.sub(re.escape("#crc32#"), get_crc32(outfile), outfile.stem)))

    if get_setup_attr("clean_work_dirs", False):
        if os.path.samefile(get_workdir(), os.getcwd()):
            error("Clearing workdir not supported when your workdir is cwd.", "Mux")
        else:
            rmtree(get_workdir())

    clean_temp_files()
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
    for match in re.findall(r"\$[^ ]+?\$", name):
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


def output_names(tmdb: TmdbConfig | None = None, args: list[str] = [], tracks: list[_track] = []) -> tuple[str, str]:
    show_name = get_setup_attr("show_name", "Example")
    episode = get_setup_attr("episode", "01")
    filename = get_setup_attr("out_name", R"$show$ - $ep$ (premux)")
    title = get_setup_attr("mkv_title_naming", "")

    try:
        ep_temp = str(episode)
        if " " in ep_temp:
            ep_temp = ep_temp.split(" ")[0]
        epint = int(ep_temp)
    except:
        if tmdb and not tmdb.movie:
            danger(f"{episode} is not a valid integer! TMDB will be skipped.", "Mux", 3)
            tmdb = None
            filename = clean_name(re.sub(re.escape(R"$title$"), "", filename))
            title = clean_name(re.sub(re.escape(R"$title$"), "", title))

    if tmdb:
        debug("Fetching tmdb metadata...", "Mux")
        mediameta = tmdb.get_media_meta()
        epmeta = tmdb.get_episode_meta(epint) if not tmdb.movie else None
        if tmdb.needs_xml():
            xml = tmdb.make_xml(mediameta, epmeta)
            args.extend(["--global-tags", str(xml)])

        if not tmdb.movie and epmeta:
            if tmdb.write_cover and epmeta.thumb_url:
                cover = Path(get_workdir(), f"cover_land{Path(epmeta.thumb_url).suffix}")
                if wget.download(epmeta.thumb_url, str(cover), None):
                    tracks.append(Attachment(cover, "image/jpeg" if cover.suffix.lower() == ".jpg" else "image/png"))

            filename = re.sub(re.escape(R"$title$"), epmeta.title, filename)
            title = re.sub(re.escape(R"$title$"), epmeta.title, title)
            filename = re.sub(re.escape(R"$title_sanitized$"), epmeta.title_sanitized, filename)
            title = re.sub(re.escape(R"$title_sanitized$"), epmeta.title_sanitized, title)

    filename = replace_with_temp_tokens(filename)

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
                danger("Please update your mkvtoolnix/mkvmerge for optimal behavior.", sleep=10)
    except:
        pass
