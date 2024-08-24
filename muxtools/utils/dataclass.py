import os
from abc import ABC
from math import ceil
from typing import Any
from pathlib import Path
from psutil import Process
from shlex import split, join
from multiprocessing import cpu_count
from pydantic.dataclasses import ConfigDict, dataclass  # noqa: F401

from .log import error

__all__ = ["CLIKwargs", "allow_extra", "dataclass"]

allow_extra = ConfigDict(extra="allow", str_strip_whitespace=True, allow_inf_nan=False, arbitrary_types_allowed=True)

attribute_blacklist = ["executable", "resumable", "x265", "was_file", "affinity", "_no_print"]


class CLIKwargs(ABC):
    """
    This is an abstract class to enable the use of (pydantic) dataclass kwargs for custom cli args.

    Examples:
    ```py
    @dataclass(config=allow_extra)
    class Encoder(CLIKwargs):
        clip: vs.VideoNode

    test = Encoder(clip, colorspace="BT709")
    print(test.get_custom_args())
    # returns ['--colorspace', 'BT709']

    # if it starts with an _ it will be a single - argument
    # empty values will be stripped
    test = Encoder(clip, _vbr="")
    print(test.get_custom_args())
    # returns ['-vbr']

    # if it ends with an _ it will preserve underscores
    test = Encoder(clip, _color_range_="limited")
    print(test.get_custom_args())
    # returns ['-color_range', 'limited']
    ```

    Alternatively you can pass an `append` argument that's either a dict[str, Any], a string or a list of strings:
    ```py
    test = Encoder(clip, append="-vbr --bitrate 192")
    test = Encoder(clip, append=["-vbr", "--bitrate", "192"])
    test = Encoder(clip, append={"-vbr": "", "--bitrate": "192"})
    # all of them return ['-vbr', '--bitrate', '192']
    ```
    """

    def get_process_affinity(self) -> bool | list[int] | None:
        if not hasattr(self, "affinity"):
            return False

        threads = self.affinity

        if not threads:
            return []

        if isinstance(threads, float):
            if 0.0 <= threads or threads >= 1.0:
                threads = 1.0

            threads = ceil(cpu_count() * threads)

        if isinstance(threads, int):
            threads = range(0, threads)
        elif isinstance(threads, tuple):
            threads = range(*threads)

        threads = list(set(threads))
        return threads

    def update_process_affinity(self, pid: int):
        if not isinstance((affinity := self.get_process_affinity()), bool):
            Process(pid).cpu_affinity(affinity)

    def get_mediainfo_settings(self, args: list[str], skip_first: bool = True) -> str:
        to_delete = [it.casefold() for it in ["-hide_banner", "-"]]
        to_delete_with_next = [it.casefold() for it in ["-map", "-i", "-o", "-c:a", "-c:v", "--csv", "--output"]]

        new_args = list[str]()
        skip_next = False
        for param in args:
            if skip_first:
                skip_first = False
                continue

            if skip_next:
                skip_next = False
                continue

            if param.casefold() in to_delete:
                continue

            if param.casefold() in to_delete_with_next:
                skip_next = True
                continue

            if os.path.isfile(param):
                if "_keyframes" not in param.lower() and "qpfile" not in param.lower():
                    continue

                keyframes_file = Path(param)
                param = keyframes_file.name

            new_args.append(param)

        return join(new_args)

    def get_custom_args(self) -> list[str]:
        init_args: dict[str, Any]
        if not (init_args := getattr(self, "__pydantic_fields__", None)):
            return []

        args = list[str]()
        attributes = vars(self)
        init_keys = list(init_args.keys())

        for k, v in attributes.items():
            if k == "append":
                if isinstance(v, list):
                    args.extend([str(x) for x in v])
                elif isinstance(v, str):
                    args.extend(split(v))
                elif isinstance(v, dict):
                    for append_k, append_v in v.items():
                        args.append(str(append_k))
                        if stripped := str(append_v).strip():
                            args.append(stripped)
                else:
                    raise error("Append is not a string, list of strings or dict!", self)
                continue

            if not any([isinstance(v, str), isinstance(v, int), isinstance(v, float)]):
                continue
            if k in init_keys or k in attribute_blacklist:
                continue

            prefix = "--"
            keep_underscores = False

            if k.endswith("_"):
                keep_underscores = True
                k = k[:-1]
            if k.startswith("_"):
                prefix = "-"
                k = k[1:]
            args.append(f"{prefix}{k.replace('_', '-') if not keep_underscores else k}")
            if not isinstance(v, str):
                args.append(str(v))
            else:
                if stripped := v.strip():
                    args.append(stripped)
        return args
