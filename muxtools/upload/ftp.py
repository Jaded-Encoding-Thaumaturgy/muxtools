import re
import subprocess as sp
from configparser import ConfigParser
from pathlib import Path
from typing import Any

import rclone

from ..utils.log import error, debug, warn
from ..utils.types import PathLike
from ..utils.download import get_executable

__all__: list[str] = ["upload_ftp"]


def upload_ftp(
    file: PathLike,
    target: PathLike | None = None,
    section: str = "FTP",
    **rclone_kwargs: Any
) -> bool:
    """
    Upload a given file to the target location via (S)FTP.

    For security purposes, all details concerning the FTP instance will be read from the `auth.ini` file
    created upon setup, and are not exposed as arguments to this function.

    :param file:            The file to upload.
    :param target:          Target location for the file. If None is passed, get it from the `auth.ini` file.
    :param section:         The section in `auth.ini` to get the FTP details from.
                            This param allows you to select different FTPs by adding them to the `auth.ini` file.
    :param rclone_kwargs:   Additional kwargs to pass to rclone.

    :return:                Bool representing whether the upload was succesful or not.
    """
    warn("This function is still a WIP! Certain functionality may not work yet!", upload_ftp)

    if not get_executable("rclone"):
        return False

    config = ConfigParser()

    config.read("auth.ini")

    if not config.has_section(section):
        error(f"The section \"{section}\" could not be found!", upload_ftp)

        return False

    args = dict(config.items(section))

    if secure_pwd := args.get("password", False):
        secure_pwd = sp.check_output([
            "echo", args.get("password", "").strip(), "|", "rclone", "obscure", "-"
        ], shell=True).decode("utf-8").strip()

    is_sftp = args.get('sftp', False)

    if port := args.get("port", " ") is not True:
        port = str(22 if is_sftp else 21)

    target_dir = str(target if target is not None else args.get("target_dir", ""))

    if len(target_dir) > 1 and target_dir.startswith("/"):
        target_dir = re.sub(r"^/+", r"", target_dir)

    cfg_args = [f"[{section}]"]
    cfg_args += [f"type = {'s' if is_sftp else ''}ftp"]
    cfg_args += [f"host = {args.get('host', '')}"] if args.get("host", False) else []
    cfg_args += [f"port = {port}"]
    cfg_args += [f"user = {args.get('username', '')}"] if args.get('username', False) else []
    cfg_args += [f"pass = {secure_pwd}"] if secure_pwd else []

    if rclone_kwargs:
        for items in rclone_kwargs.items():
            cfg_args += [" = ".join(str(item).lower() if isinstance(item, bool) else str(item) for item in items)]

    cfg = "\n".join(cfg_args)
    rc = rclone.with_config(cfg)

    debug(f"Uploading file \"{file}\" to \"{target_dir}\"...", upload_ftp)

    # TODO: Figure out why connecting to my seedbox keeps throwing an error
    print(rc.lsjson(f"{section}:"))
