import os
from typing import Any, Sequence
from pathlib import Path
from shutil import rmtree
import xml.etree.ElementTree as ET

from .log import crit, warn
from .glob import GlobSearch
from .types import PathLike, FileMixin
from .env import get_temp_workdir, get_workdir

__all__ = [
    "ensure_path",
    "uniquify_path",
    "get_crc32",
    "make_output",
    "ensure_path_exists",
    "clean_temp_files",
]


def ensure_path(pathIn: PathLike | Sequence[PathLike] | GlobSearch | FileMixin, caller: Any) -> Path:
    """
    Utility function for other functions to make sure a path was passed to them.

    :param pathIn:      Supposed passed Path
    :param caller:      Caller name used for the exception and error message
    """
    if pathIn is None:
        raise crit("Path cannot be None.", caller)
    else:
        if isinstance(pathIn, FileMixin):
            pathIn = pathIn.file
        if isinstance(pathIn, GlobSearch):
            pathIn = pathIn.paths
        if isinstance(pathIn, Sequence) and not isinstance(pathIn, str):
            pathIn = pathIn[0]

        if not isinstance(pathIn, Path) and not isinstance(pathIn, str):
            raise crit("Path is not a Path object or a string!", caller)

        return Path(pathIn).resolve()


def ensure_path_exists(pathIn: PathLike | Sequence[PathLike] | GlobSearch | FileMixin, caller: Any, allow_dir: bool = False) -> Path:
    """
    Utility function for other functions to make sure a path was passed to them and that it exists.

    :param pathIn:      Supposed passed Path
    :param caller:      Caller name used for the exception and error message
    """
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

    path = str(ensure_path(path, None))

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
    try:
        from zlib import crc32
    except ImportError:
        from binascii import crc32

    buffer_size = 1024 * 1024 * 32
    val = 0
    with open(ensure_path(file, get_crc32), "rb") as f:
        buffer = f.read(buffer_size)
        while len(buffer) > 0:
            val = crc32(buffer, val)
            buffer = f.read(buffer_size)

    val = val & 0xFFFFFFFF
    return "%08X" % val


def clean_temp_files():
    try:
        rmtree(get_temp_workdir())
    except (FileNotFoundError, PermissionError) as e:
        warn(f"Could not clean temp files! {e}", clean_temp_files)


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

    ET.ElementTree(main).write(ensure_path(fileOut, create_tags_xml), "utf-8")


def make_output(source: PathLike, ext: str, suffix: str = "", user_passed: PathLike | None = None, temp: bool = False) -> Path:
    workdir = get_temp_workdir() if temp else get_workdir()
    source_stem = ensure_path(source, make_output).stem

    if user_passed:
        user_passed = Path(user_passed)
        if user_passed.exists() and user_passed.is_dir():
            return Path(user_passed, f"{source_stem}.{ext}").resolve()
        else:
            return user_passed.with_suffix(f".{ext}").resolve()
    else:
        return Path(uniquify_path(os.path.join(workdir, f"{source_stem}{f'_{suffix}' if suffix else ''}.{ext}"))).resolve()
