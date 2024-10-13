from typing import Any
from math import ceil
from datetime import timedelta
from re import Pattern, compile
from dataclasses import dataclass
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn
from shlex import split as splitcmd
from subprocess import Popen, PIPE, STDOUT

from .convert import timedelta_from_formatted

__all__ = ["ProgressBarConfig", "run_cmd_pb", "PERCENTAGE_PATTERN", "FFMPEG_TIME_PATTERN"]

PERCENTAGE_PATTERN = compile(r"(\d+(?:\.\d+)?)%")
FFMPEG_TIME_PATTERN = compile(r"time=(\d+:\d+:\d+.\d+)")


@dataclass
class ProgressBarConfig:
    description: str = ""
    target: int | timedelta = 100
    regex: Pattern | str | None = None
    groupnum: int = 1
    success_return: int = 0


def run_cmd_pb(cmd: str | list[str], silent: bool = True, pbc: ProgressBarConfig = ProgressBarConfig(), **kwargs: Any) -> int:
    args = splitcmd(cmd) if isinstance(cmd, str) else cmd
    process = Popen(args, stdout=PIPE, stderr=STDOUT, text=True, encoding="UTF-8", errors="ignore", bufsize=1, **kwargs)
    if not pbc.regex:
        pbc.regex = PERCENTAGE_PATTERN if isinstance(pbc.target, int) else FFMPEG_TIME_PATTERN
    if isinstance(pbc.regex, str):
        pbc.regex = compile(pbc.regex)

    with Progress(
        TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TimeRemainingColumn(), TimeElapsedColumn()
    ) as pro:
        task = pro.add_task(pbc.description)
        prev = 0

        for line in iter(process.stdout.readline, b""):
            if not silent:
                print(line, end="" if line.endswith("\n") else "\n")

            line = line.strip()
            matches = pbc.regex.search(line)

            if matches:
                if isinstance(pbc.target, int):
                    val = float(matches.group(pbc.groupnum))
                    rounded = round(val)
                    if prev < rounded:
                        pro.update(task, completed=rounded)
                        prev = rounded
                else:
                    current_string: str = matches[pbc.groupnum]
                    if current_string.count(":") == 1:
                        current_string = f"0:{current_string}"
                    current = timedelta_from_formatted(current_string)
                    percentage = current.total_seconds() / pbc.target.total_seconds() * 100
                    if prev < percentage:
                        pro.update(task, completed=ceil(percentage))
                        prev = percentage

            # Break this loop if process is done
            if process.poll() is not None:
                if process.returncode == pbc.success_return:
                    pro.update(task, completed=100)
                break

        pro.stop()
    return process.returncode
