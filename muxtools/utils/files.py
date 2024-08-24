import os
import re
import binascii
from typing import Any
from pathlib import Path
from shutil import rmtree
from copy import deepcopy
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pymediainfo import Track, MediaInfo

from .log import crit, error, LoggingException
from .glob import GlobSearch
from .types import PathLike, TrackType
from .env import get_temp_workdir, get_workdir

__all__ = [
    "ensure_path",
    "uniquify_path",
    "get_crc32",
    "make_output",
    "ensure_path_exists",
    "clean_temp_files",
    "get_absolute_track",
    "get_track_list",
    "find_tracks",
]


def ensure_path(pathIn: PathLike, caller: Any) -> Path:
    """
    Utility function for other functions to make sure a path was passed to them.

    :param pathIn:      Supposed passed Path
    :param caller:      Caller name used for the exception and error message
    """
    if pathIn is None:
        raise crit("Path cannot be None.", caller)
    else:
        return Path(pathIn).resolve()


def ensure_path_exists(pathIn: PathLike | list[PathLike] | GlobSearch, caller: Any, allow_dir: bool = False) -> Path:
    """
    Utility function for other functions to make sure a path was passed to them and that it exists.

    :param pathIn:      Supposed passed Path
    :param caller:      Caller name used for the exception and error message
    """
    from ..muxing.muxfiles import MuxingFile

    if isinstance(pathIn, MuxingFile):
        return ensure_path_exists(pathIn.file, caller)
    if isinstance(pathIn, GlobSearch):
        pathIn = pathIn.paths
    if isinstance(pathIn, list):
        pathIn = pathIn[0]
    path = ensure_path(pathIn, caller)
    if not path.exists():
        raise crit(f"Path target '{path}' does not exist.", caller)
    if not allow_dir and path.is_dir():
        raise crit("Path cannot be a directory.", caller)
    return path


def uniquify_path(path: PathLike) -> str:
    """
    Extends path to not conflict with existing files

    :param file:        Input file

    :return:            Unique path
    """

    if isinstance(path, Path):
        path = str(path.resolve())

    filename, extension = os.path.splitext(path)
    counter = 1

    while os.path.exists(path):
        path = filename + " (" + str(counter) + ")" + extension
        counter += 1

    return path


def get_crc32(file: PathLike) -> str:
    """
    Generates crc32 checksum for file

    :param file:        Input file

    :return:            Checksum for file
    """
    buf = open(file, "rb").read()
    buf = binascii.crc32(buf) & 0xFFFFFFFF
    return "%08X" % buf


def clean_temp_files():
    rmtree(get_temp_workdir())


def create_tags_xml(fileOut: PathLike, tags: dict[str, Any]) -> None:
    main = ET.Element("Tags")
    tag = ET.SubElement(main, "Tag")
    target = ET.SubElement(tag, "Targets")
    targettype = ET.SubElement(target, "TargetTypeValue")
    targettype.text = "50"

    for k, v in tags.items():
        if not v:
            continue
        simple = ET.SubElement(tag, "Simple")
        key = ET.SubElement(simple, "Name")
        key.text = k

        value = ET.SubElement(simple, "String")
        value.text = str(v)

    with open(fileOut, "w") as f:
        ET.ElementTree(main).write(f, "unicode")


def make_output(source: PathLike, ext: str, suffix: str = "", user_passed: PathLike | None = None, temp: bool = False) -> Path:
    workdir = get_temp_workdir() if temp else get_workdir()
    source_stem = Path(source).stem

    if user_passed:
        user_passed = Path(user_passed)
        if user_passed.exists() and user_passed.is_dir():
            return Path(user_passed, f"{source_stem}.{ext}").resolve()
        else:
            return user_passed.with_suffix(f".{ext}").resolve()
    else:
        return Path(uniquify_path(os.path.join(workdir, f"{source_stem}{f'_{suffix}' if suffix else ''}.{ext}"))).resolve()


def get_track_list(file: PathLike, caller: Any = None) -> list[Track]:
    """Makes a sanitized mediainfo track list"""
    caller = caller if caller else get_track_list
    file = ensure_path_exists(file, caller)
    mediainfo = MediaInfo.parse(file)

    filler_tracks = 0
    is_m2ts = False
    relative_indices = dict[str, int]()
    sanitized_list = []

    for t in mediainfo.tracks:
        ttype = t.track_type.lower()

        if ttype == "general":
            is_m2ts = getattr(t, "format", None) == "BDAV"
        if ttype not in ["video", "audio", "text"]:
            continue
        sanitized_list.append(t)

        if is_m2ts and "-" in t.streamorder:
            t.streamorder = str(t.streamorder).split("-")[1]
        order = t.streamorder
        order = -1 if order is None else int(order)
        t.streamorder = order + filler_tracks

        relative = relative_indices.get(ttype, 0)
        setattr(t, "relative_id", relative)
        relative_indices[ttype] = relative + 1

        if "truehd" in (getattr(t, "commercial_name", "") or "").lower() and "extension" in (getattr(t, "muxing_mode", "") or "").lower():
            identifier = getattr(t, "format_identifier", "AC-3") or "AC-3"
            compat_track = deepcopy(t)
            compat_track.format = identifier
            compat_track.codec_id = f"A_{identifier.replace('-', '')}"
            compat_track.commercial_name = ""
            compat_track.compression_mode = "Lossy"
            compat_track.streamorder = t.streamorder + 1

            relative = relative_indices.get(ttype, 0)
            setattr(compat_track, "relative_id", relative)
            relative_indices[ttype] = relative + 1

            sanitized_list.append(compat_track)
            filler_tracks += 1

    # the actual ID is really just absolutely useless so lets try and use the order
    for t in sanitized_list:
        if isinstance(t.streamorder, int) and t.streamorder > -1:
            t.track_id = t.streamorder

    return sanitized_list


def find_tracks(
    file: PathLike,
    name: str | None = None,
    lang: str | None = None,
    type: TrackType | None = None,
    use_regex: bool = True,
    reverse_lang: bool = False,
    custom_condition: Callable[[Track], bool] | None = None,
) -> list[Track]:
    """
    Convenience function to find tracks with some conditions.

    :param file:                File to parse with MediaInfo.
    :param name:                Name to match, case insensitively.
    :param lang:                Language to match. This can be any of the possible formats like English/eng/en and is case insensitive.
    :param type:                Track Type to search for.
    :param use_regex:           Use regex for the name search instead of checking for equality.
    :param reverse_lang:        If you want the `lang` param to actually exclude that language.
    :param custom_condition:    Here you can pass any function to create your own conditions. (They have to return a bool)
                                For example: custom_condition=lambda track: track.codec_id == "A_EAC3"
    """

    if not name and not lang and not type and not custom_condition:
        return []
    tracks = get_track_list(file)

    def name_matches(title: str) -> bool:
        if title.casefold().strip() == name.casefold().strip():
            return True
        if use_regex:
            return re.match(name, title, re.I)
        return False

    def get_languages(track: MediaInfo) -> list[str]:
        languages: list[str] = getattr(track, "other_language", None) or list[str]()
        return [lang.casefold() for lang in languages]

    if name is not None:
        tracks = [track for track in tracks if name_matches(getattr(track, "title", "") or "")]

    if lang:
        if reverse_lang:
            tracks = [track for track in tracks if lang.casefold() not in get_languages(track)]
        else:
            tracks = [track for track in tracks if lang.casefold() in get_languages(track)]

    if type:
        if type not in (TrackType.VIDEO, TrackType.AUDIO, TrackType.SUB):
            raise error("You can only search for video, audio and subtitle tracks!", find_tracks)
        type_string = (str(type.name) if type != TrackType.SUB else "Text").casefold()
        tracks = [track for track in tracks if track.track_type.casefold() == type_string]

    if custom_condition:
        tracks = [track for track in tracks if custom_condition(track)]

    return tracks


def get_absolute_track(file: PathLike, track: int, type: TrackType, caller: Any = None, quiet_fail: bool = False) -> Track:
    """
    Finds the absolute track for a relative track number of a specific type.

    :param file:        String or pathlib based Path
    :param track:       Relative track number
    :param type:        TrackType of the requested relative track
    :param quiet_fail:  Raise an exception but don't print it before.
                        Only used for internals.
    """
    caller = caller if caller else get_absolute_track
    file = ensure_path_exists(file, caller)

    tracks = get_track_list(file, caller)
    videos = [track for track in tracks if track.track_type.casefold() == "Video".casefold()]
    audios = [track for track in tracks if track.track_type.casefold() == "Audio".casefold()]
    subtitles = [track for track in tracks if track.track_type.casefold() == "Text".casefold()]
    no_track_msg = "Your requested track doesn't exist."

    match type:
        case TrackType.VIDEO:
            if not videos:
                raise error(f"No video tracks have been found in '{file.name}'!", caller)
            try:
                return videos[track]
            except:
                raise error(no_track_msg, caller) if not quiet_fail else LoggingException(no_track_msg)
        case TrackType.AUDIO:
            if not audios:
                raise error(f"No audio tracks have been found in '{file.name}'!", caller)
            try:
                return audios[track]
            except:
                raise error(no_track_msg, caller) if not quiet_fail else LoggingException(no_track_msg)
        case TrackType.SUB:
            if not subtitles:
                raise error(f"No subtitle tracks have been found in '{file.name}'!", caller)
            try:
                return subtitles[track]
            except:
                raise error(no_track_msg, caller) if not quiet_fail else LoggingException(no_track_msg)
        case _:
            raise error("Not implemented for anything other than Video, Audio or Subtitles.", caller)


def get_absolute_tracknum(file: PathLike, track: int, type: TrackType, caller: Any = None) -> int:
    """
    Finds the absolute track number for a relative track number of a specific type.

    :param file:    String or pathlib based Path
    :param track:   Relative track number
    :param type:    TrackType of the requested relative track
    """
    return get_absolute_track(file, track, type, caller).track_id
