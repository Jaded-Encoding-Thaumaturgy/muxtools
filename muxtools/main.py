from __future__ import annotations

import os
import json
from typing import Any, TypeVar
from pathlib import Path
from dataclasses import dataclass
from configparser import ConfigParser

from .utils.log import error
from .utils.types import TimeScale
from .utils.glob import GlobSearch

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
    :param error_on_danger:         Raise an error when normally a "danger" log would be printed.
    """

    episode: str = "01"
    config_file: str = "config.ini"

    bdmv_dir: str = "BDMV"
    show_name: str = "Nice Series"
    allow_binary_download: bool = True
    clean_work_dirs: bool = False
    out_dir: str = "premux"
    out_name: str = "$show$ - $ep$ (premux)"
    mkv_title_naming: str = r"$show$ - $ep$"
    work_dir: str | None = None
    debug: bool = True
    error_on_danger: bool = False

    def __post_init__(self):
        if self.config_file:
            config = ConfigParser()
            config_name = self.config_file

            if not os.path.exists(config_name):
                config["SETUP"] = {
                    "bdmv_dir": self.bdmv_dir,
                    "show_name": self.show_name,
                    "allow_binary_download": self.allow_binary_download,
                    "clean_work_dirs": self.clean_work_dirs,
                    "out_dir": self.out_dir,
                    "out_name": self.out_name,
                    "mkv_title_naming": self.mkv_title_naming,
                    "debug": self.debug,
                    "error_on_danger": self.error_on_danger,
                }

                with open(config_name, "w", encoding="utf-8") as config_file:
                    config.write(config_file)

                raise error(f"Template config created at {Path(config_name).resolve()}.\nPlease set it up!")

            config.read(config_name, encoding="utf-8")
            settings = config["SETUP"]

            valid_bools = ["true", "1", "t", "y", "yes"]
            for key in settings:
                if hasattr(self, key) and isinstance(getattr(self, key), bool):
                    setattr(self, key, True if settings[key].lower() in valid_bools else False)
                else:
                    setattr(self, key, settings[key])

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

    def set_default_sub_timesource(
        self: SetupSelf,
        timesource: Path | GlobSearch | str | float | list[int],
        timescale: TimeScale | int | None = None,
    ) -> SetupSelf:
        """
        Set a default timesource and timescale for conversions in subtitle functions.

        The source selection for this is a bit more limited than the explicit params in the respective functions due to certain types being hard to store in the environment.

        :param timesource:          The source of timestamps/timecodes.\n
                                    This can be a video file, a timestamps txt file, actual timestamps as integers,
                                    a muxtools VideoMeta json file or FPS as a fraction string or float.
        :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                    For details check the docstring on the type.
        """
        if isinstance(timesource, GlobSearch):
            timesource = timesource.paths[0]

        if isinstance(timesource, Path):
            timesource = str(timesource.resolve())

        if isinstance(timescale, TimeScale):
            timescale = timescale.value

        self.edit("sub_timesource", timesource)
        return self.edit("sub_timescale", timescale)

    def _toJson(self) -> str:
        return json.dumps(self.__dict__)


SetupSelf = TypeVar("SetupSelf", bound=Setup)
