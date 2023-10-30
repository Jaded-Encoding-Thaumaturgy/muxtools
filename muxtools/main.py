from __future__ import annotations

import json
import os
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from .utils.git import gitignore
from .utils.log import error, info
from .utils.types import TrueInputs

__all__ = ["Setup"]


@dataclass
class Setup:
    """
    Something like an environment used for a lot of functions in this package.
    Mostly used for muxing and data locations (work directory and what not).

    If you want to change any of the variables AFTER initialization make sure to use the `Setup.edit` function to do so.
    Read its docstring to get why.

    :param episode:                 Episode identifier used for workdir and muxing
    :param config_file:             An ini file where the config will be loaded from.
                                    You can disable this by leaving it empty or setting None.
                                    Make sure you set the relevant variables in this constructor in that case.
                                    You can also set other, technically, not existing variables in there and access them from python after.

    :param bdmv_dir:                Convenience path for sources and what not.
    :param show_name:               The name of the show. Used for the $show$ placeholder in muxing.
    :param allow_binary_download:   This will download any executables needed for doing what you're requesting to do.
                                    For example x265, opusenc, etc.
    :param clean_work_dirs:         Cleanup the work directories after muxing. Might be useful if you're muxing a ton of stuff.
    :param out_dir:                 The folder the muxed files will go into.
    :param out_name:                The naming template applied to the muxed files.
    :param mkv_title_naming:        The naming template applied to the mkv title.
    :param work_dir:                In case you want to set a custom work directory for all the temp files.
    :param debug:                   Enable or Disable various, possibly interesting, debug output of all functions in this package.
    """

    episode: str = "01"
    config_file: str = "config.ini"
    auth_file: str = "auth.ini"

    bdmv_dir: str = "BDMV"
    show_name: str = "Nice Series"
    allow_binary_download: bool = True
    clean_work_dirs: bool = False
    out_dir: str = "premux"
    out_name: str = "$show$ - $ep$ (premux)"
    mkv_title_naming: str = r"$show$ - $ep$"
    work_dir: str | None = None
    debug: bool = True

    def __post_init__(self):
        if name := self.auth_file:
            if not Path(name).exists():
                gitignore(name)

            self._touch_ini(
                name, sections="FTP", raise_on_new=False, fields={
                    "host": "",
                    "port": "",
                    "sftp": False,
                    "username": "",
                    "password": "",  # TODO: Figure out a better way to store user passwords
                    "target_dir": "/"
                }
            )

        if name := self.config_file:
            self._touch_ini(
                name=name, sections="SETUP", fields={
                    "bdmv_dir": self.bdmv_dir,
                    "show_name": self.show_name,
                    "allow_binary_download": self.allow_binary_download,
                    "clean_work_dirs": self.clean_work_dirs,
                    "out_dir": self.out_dir,
                    "out_name": self.out_name,
                    "mkv_title_naming": self.mkv_title_naming,
                    "debug": self.debug,
                }
            )

        if not self.work_dir:
            self.work_dir = Path(os.getcwd(), "_workdir", self.episode)

        self.work_dir = Path(self.work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = str(self.work_dir)

        from .utils.env import save_setup

        save_setup(self)

    def edit(self: SetupSelf, attr: str, value: Any) -> SetupSelf:
        """
        Sets a variable inside of Setup and saves it to the environment variables.
        You should use this to apply any changes because other functions will not make use of them otherwise!

        :param attr:        The name of the variable/attribute you want to change
        :param value:       The value this variable/attribute will have.
        """
        setattr(self, attr, value)

        from .utils.env import save_setup

        save_setup(self)
        return self

    def _toJson(self) -> str:
        return json.dumps(self.__dict__)

    def _touch_ini(
        self, name: str, sections: list[str] | str,
        fields: list[dict[str, Any]] | dict[str, Any] = [],
        raise_on_new: bool = True, caller: str = ""
    ) -> ConfigParser:
        """
        Touch, populate, and sanitize an ini file.

        If the ini file does not exist yet, it will create it.
        Optionally, if `raise_on_new` is True, it will raise an error
        prompting the user to configure the ini file.

        `sections` and `fields` are a list to allow for multiple sections
        to be populated trivially in case they get expanded in the future.
        This is mostly useful for the `auth` config file.
        """
        config = ConfigParser()

        if isinstance(sections, str):
            sections = [sections]

        if isinstance(fields, dict):
            fields = [fields]

        if not os.path.exists(name):
            info(f"Writing {Path(name).resolve()}...", caller)

            for section, field_dict in zip(sections, fields):
                config[section] = field_dict

                with open(name, "w") as f:
                    config.write(f)

                if raise_on_new:
                    raise error(f"Template config created at {Path(name).resolve()}.\nPlease configure it!")

        config.read(name)

        for section in sections:
            settings = config[section]

            for key in settings:
                if hasattr(self, key) and isinstance(getattr(self, key), bool):
                    setattr(self, key, True if settings[key].lower() in TrueInputs else False)
                else:
                    setattr(self, key, settings[key])

        return config


SetupSelf = TypeVar("SetupSelf", bound=Setup)
