import re
import os
import subprocess
from pathlib import Path
from fractions import Fraction
from typing import Any
from pyparsebluray import mpls
from .types import Chapter, PathLike, AudioInfo, AudioStats, AudioFrame
from .files import ensure_path_exists
from .log import error, warn, debug, info
from .download import get_executable
from .convert import (
    timedelta_from_formatted,
    timedelta_to_frame,
    frame_to_timedelta,
    mpls_timestamp_to_timedelta,
    format_timedelta,
)


__all__: list[str] = ["parse_ogm", "parse_xml", "parse_chapters_bdmv", "parse_m2ts_path", "parse_audioinfo"]

OGM_REGEX = r"(^CHAPTER(?P<num>\d+)=(?P<time>.*)\nCHAPTER\d\dNAME=(?P<name>.*))"
XML_REGEX = r"(\<ChapterAtom\>.*?\<ChapterTimeStart\>(?P<time>[^\<]*).*?\<ChapterString\>(?P<name>[^\<]*)\<\/ChapterString\>.*?\<\/ChapterAtom\>)"
AUDIOFRAME_REGEX = r"\[Parsed_ashowinfo.*\] n:(?P<n>\d+).*pts:(?P<pts>\d+).*pts_time:(?P<pts_time>\d+\.?\d+).+nb_samples:(?P<samples>\d+)"
AUDIOSTATS_REGEX = r"\[Parsed_astats.*\] (?:(?:(?P<key>.+): (?P<val>.+))|(?P<other>Overall))"


def parse_ogm(file: Path) -> list[Chapter]:
    """
    Parses chapters from an OGM file

    :param file:    Input file

    :return:        List of parsed chapters
    """
    return _parse_chapters(file, OGM_REGEX, re.I | re.M)


def parse_xml(file: Path) -> list[Chapter]:
    """
    Parses chapters from an XML file

    :param file:    Input file

    :return:        List of parsed chapters
    """
    return _parse_chapters(file, XML_REGEX, re.I | re.M | re.S)


def _parse_chapters(file: Path, reg: str, flags: int = 0) -> list[Chapter]:
    chapters: list[Chapter] = []
    with file.open("r", encoding="utf-8") as f:
        for match in re.finditer(re.compile(reg, flags), f.read()):
            chapters.append((timedelta_from_formatted(match.group("time")), match.group("name")))

    return chapters


def parse_m2ts_path(dgiFile: Path) -> Path:
    """
    Parses actual source location from a dgi file.

    :param dgiFile: Input file

    :return:        Path of source file
    """
    with open(dgiFile, "r") as fp:
        for i, line in enumerate(fp):
            for match in re.finditer(re.compile(r"^(.*\.m2ts) \d+$", re.IGNORECASE), line):
                m2tsFile = Path(match.group(1))
                if m2tsFile.exists():
                    return m2tsFile
    print("Warning!\nCould not resolve origin file path from the dgindex input!")
    return dgiFile


def parse_audioinfo(
    file: PathLike, track: int = 0, caller: Any = None, is_thd: bool = False, full_analysis: bool = False, quiet: bool = False
) -> AudioInfo:
    f_compiled = re.compile(AUDIOFRAME_REGEX, re.IGNORECASE)
    s_compiled = re.compile(AUDIOSTATS_REGEX, re.IGNORECASE)
    file = ensure_path_exists(file, parse_audioinfo)
    ffmpeg = get_executable("ffmpeg")
    out_var = "NUL" if os.name == "nt" else "/dev/null"
    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-i",
        str(file.resolve()),
    ]
    if not full_analysis:
        args.extend(
            [
                "-t",
                "4" if is_thd else "10",
            ]
        )
    args.extend(
        [
            "-map",
            f"0:a:{track}",
            "-filter:a",
            "astats=metadata=1,ashowinfo",
            "-f",
            "wav",
            out_var,
        ]
    )
    if not quiet:
        if not caller:
            caller = parse_audioinfo
            debug(f"Parsing frames and stats for '{file.stem}'", caller)
        else:
            debug("Parsing frames and stats...", caller)
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    frames = []
    stats = AudioStats()
    is_overall = False
    output = (out.stderr or "") + (out.stdout or "")
    for line in output.splitlines():
        if not line.strip().startswith("["):
            continue
        match = f_compiled.match(line)
        if match:
            frames.append(AudioFrame(int(match.group("n")), int(match.group("pts")), float(match.group("pts_time")), int(match.group("samples"))))
            continue
        match = s_compiled.match(line)
        if match:
            if not is_overall:
                if match.group("other") == "Overall":
                    is_overall = True
                continue
            for attr in dir(stats):
                if attr.startswith("_"):
                    continue
                if attr.casefold() == match.group("key").replace(" ", "_").casefold():
                    val = match.group("val")
                    val = float(val) if isinstance(getattr(stats, attr), float) else val
                    val = int(val) if isinstance(getattr(stats, attr), int) else val
                    setattr(stats, attr, val)
    if not quiet:
        debug("Done", caller)
    return AudioInfo(stats, frames)


def parse_chapters_bdmv(
    src: PathLike,
    clip_fps: Fraction | PathLike = Fraction(24000, 1001),
    clip_frames: int = -1,
    _print: bool = False,
) -> list[Chapter]:
    """
    Attempts to parse chapters from the bluray metadata

    :param src:         The m2ts file you're currently using
    :param clip_fps:    The fps of the clip. Also accepts a timecode (v2) file.
    :param clip_frames: Total frames of the clip
    :param _print:      Prints the chapters after parsing if true

    :return:            List of parsed chapters
    """
    src = ensure_path_exists(src, parse_chapters_bdmv)
    stream_dir = src.parent
    if stream_dir.name.lower() != "stream":
        print("Your source file is not in a default bdmv structure!\nWill skip chapters.")
        return None
    playlist_dir = Path(os.path.join(stream_dir.parent, "PLAYLIST"))
    if not playlist_dir.exists():
        print("PLAYLIST folder couldn't have been found!\nWill skip chapters.")
        return None

    chapters: list[Chapter] = []
    for f in playlist_dir.rglob("*"):
        if not os.path.isfile(f) or f.suffix.lower() != ".mpls":
            continue
        with f.open("rb") as file:
            header = mpls.load_movie_playlist(file)
            file.seek(header.playlist_start_address, os.SEEK_SET)
            playlist = mpls.load_playlist(file)
            if not playlist.play_items:
                continue

            file.seek(header.playlist_mark_start_address, os.SEEK_SET)
            playlist_mark = mpls.load_playlist_mark(file)
            if (plsmarks := playlist_mark.playlist_marks) is not None:
                marks = plsmarks
            else:
                raise error("There are no playlist marks in this file!", parse_chapters_bdmv)

        for i, playitem in enumerate(playlist.play_items):
            if playitem.clip_information_filename == src.stem and playitem.clip_codec_identifier.lower() == src.suffix.lower().split(".")[1]:
                if _print:
                    info(f'Found chapters for "{src.name}" in "{f.name}":')
                linked_marks = [mark for mark in marks if mark.ref_to_play_item_id == i]
                try:
                    assert playitem.intime
                    offset = min(playitem.intime, linked_marks[0].mark_timestamp)
                except IndexError:
                    continue
                if (
                    playitem.stn_table
                    and playitem.stn_table.length != 0
                    and playitem.stn_table.prim_video_stream_entries
                    and (fps_n := playitem.stn_table.prim_video_stream_entries[0][1].framerate)
                ):
                    try:
                        fps = mpls.FRAMERATE[fps_n]
                    except:
                        warn("Couldn't parse fps from playlist! Will take fps from source clip.", parse_chapters_bdmv)
                        fps = clip_fps

                    for i, lmark in enumerate(linked_marks, start=1):
                        time = mpls_timestamp_to_timedelta(lmark.mark_timestamp - offset)
                        if clip_frames > 0 and time > frame_to_timedelta(clip_frames - 50, fps):
                            continue
                        chapters.append((time, f"Chapter {i:02.0f}"))
                    if chapters and _print:
                        for time, name in chapters:
                            print(f"{name}: {format_timedelta(time)} | {timedelta_to_frame(time, fps)}")

        if chapters:
            break

    return chapters
