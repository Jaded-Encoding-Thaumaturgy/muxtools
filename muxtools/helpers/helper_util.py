import re
from pathlib import Path
from typing import Any

from ..utils.log import debug
from ..utils.files import get_crc32

__all__ = ["replace_crc"]

CRC_REGEX = re.compile(r"[\.| |\[|\(|-](?P<crc>[0-9A-Z]{8})[\.| |\]|\)|-]")


def replace_crc(file: Path, caller: Any | None = None) -> Path:
    """
    Replace existing CRC32 in filename if any.

    :param file:        File to replace the CRC in

    :return:            The new Path to the file
    """
    match = re.search(CRC_REGEX, file.name)
    if not match:
        return file

    debug(f"Generating new CRC-32 for file '{file.name}'...", caller)
    new = get_crc32(file).upper()

    if new == match.group(1):
        debug("New crc matches input!", caller)
        return file

    return file.rename(file.with_name(file.name.replace(match.group(1), new)))
