from __future__ import annotations

from typing import Any, Self
from pathlib import Path

from pydantic import ConfigDict

from .config import MuxSettings, discover_config

from .utils.types import TimeScale
from .utils.glob import GlobSearch

__all__ = ["Setup"]


class Setup(MuxSettings):
    """
    Something like an environment used for a lot of functions in this package.
    Mostly used for muxing and data locations (work directory and what not).

    If you want to change any of the variables AFTER initialization make sure to use the `Setup.edit` function to do so.
    Read its docstring to get why.

    :param episode:                 Episode identifier used for workdir and muxing
    :param config_path:             Optional explicit pyproject.toml or muxtools.toml path.

    :param show_name:               The name of the show. Used for the $show$ placeholder in muxing.
    :param clean_work_dirs:         Cleanup the work directories after muxing. Might be useful if you're muxing a ton of stuff.
    :param out_dir:                 The folder the muxed files will go into.
    :param out_name:                The naming template applied to the muxed files.
    :param mkv_title_naming:        The naming template applied to the mkv title.
    :param work_dir:                In case you want to set a custom work directory for all the temp files.
    :param debug:                   Enable or Disable various, possibly interesting, debug output of all functions in this package.
    :param error_on_danger:         Raise an error when normally a "danger" log would be printed.
    """

    model_config = ConfigDict(extra="allow", strict=True)

    episode: str = "01"
    config_path: str | None = None
    work_dir: str | None = None

    def __init__(
        self,
        episode: str = "01",
        config_path: str | Path | None = None,
        **options: Any,
    ) -> None:
        unknown = options.keys() - MuxSettings.model_fields.keys() - {"work_dir"}
        if unknown:
            raise TypeError(f"Unknown Setup setting: {', '.join(sorted(unknown))}")
        path = Path(config_path) if config_path else None
        config = discover_config(explicit=path)
        project_values = config.settings.model_dump(exclude={"binaries"}) if config else {}
        overrides = {key: value for key, value in options.items() if value is not None}
        values = {**project_values, **overrides, "episode": episode, "config_path": str(path) if path else None}
        super().__init__(**values)

        if not self.work_dir:
            self.work_dir = str(Path.cwd() / "_workdir" / self.episode)
        Path(self.work_dir).mkdir(parents=True, exist_ok=True)

        from .utils.env import save_setup

        save_setup(self)

    def edit(self, attr: str, value: Any) -> Self:
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
        self,
        timesource: Path | GlobSearch | str | float | list[int],
        timescale: TimeScale | int | None = None,
    ) -> Self:
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
        return self.model_dump_json()
