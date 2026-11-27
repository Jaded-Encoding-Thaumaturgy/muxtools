from typing import Any, IO
from math import ceil
from datetime import timedelta
from re import Pattern, compile
from threading import Thread
from dataclasses import dataclass
from shlex import split as splitcmd
from subprocess import Popen, PIPE, STDOUT, TimeoutExpired

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


def _drain_stream(stream: IO[Any], buf: list[str]) -> None:
    with stream:
        if data := stream.read():
            text = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else data
            buf.append(text.replace("\r\n", "\n"))


def _terminate_and_wait(process: Popen[Any]) -> int:
    if process.poll() is None:
        process.terminate()
        try:
            return process.wait(timeout=5)
        except TimeoutExpired:
            process.kill()
    return process.wait()


def _finish_upstream(upstream: Popen[Any], err_thread: Thread | None = None, terminate: bool = False) -> int:
    if upstream.stdout:
        upstream.stdout.close()
    if err_thread is None and upstream.stderr:
        upstream.stderr.close()
    code = _terminate_and_wait(upstream) if terminate else upstream.wait()
    if err_thread is not None:
        err_thread.join(timeout=2)
    return code


def run_cmd_pb(cmd: str | list[str], silent: bool = True, pbc: ProgressBarConfig = ProgressBarConfig(), **kwargs: Any) -> int:
    from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn

    regex = pbc.regex or (PERCENTAGE_PATTERN if isinstance(pbc.target, int) else FFMPEG_TIME_PATTERN)
    if isinstance(regex, str):
        regex = compile(regex)

    args = splitcmd(cmd) if isinstance(cmd, str) else cmd
    upstream = kwargs["stdin"] if isinstance(kwargs.get("stdin"), Popen) else None
    if upstream is not None:
        kwargs["stdin"] = upstream.stdout

    upstream_err: list[str] = []
    err_thread: Thread | None = None
    process: Popen[str] | None = None
    output: list[str] = []
    try:
        process = Popen(args, stdout=PIPE, stderr=STDOUT, text=True, encoding="UTF-8", errors="ignore", bufsize=1, **kwargs)
        if upstream is not None:
            # Close parent's pipe reference so downstream exit delivers EOF/SIGPIPE to upstream.
            if upstream.stdout:
                upstream.stdout.close()
            if upstream.stderr:
                err_thread = Thread(target=_drain_stream, args=(upstream.stderr, upstream_err), daemon=True)
                err_thread.start()

        with Progress(
            TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TimeRemainingColumn(), TimeElapsedColumn()
        ) as pro:
            task = pro.add_task(pbc.description)
            prev = 0
            assert process.stdout
            with process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if silent:
                        output.append(line)
                    else:
                        print(line, end="" if line.endswith("\n") else "\n")

                    matches = regex.search(line.strip())
                    if not matches:
                        continue

                    if isinstance(pbc.target, int):
                        rounded = round(float(matches.group(pbc.groupnum)))
                        if prev < rounded:
                            pro.update(task, completed=rounded)
                            prev = rounded
                    else:
                        current_string: str = matches[pbc.groupnum]
                        if current_string.count(":") == 1:
                            current_string = f"0:{current_string}"
                        percentage = timedelta_from_formatted(current_string).total_seconds() / pbc.target.total_seconds() * 100
                        if prev < percentage:
                            pro.update(task, completed=ceil(percentage))
                            prev = percentage

            returncode = process.wait()
            if upstream is not None:
                upstream_code = _finish_upstream(upstream, err_thread, terminate=returncode != pbc.success_return)
                if returncode == pbc.success_return and upstream_code:
                    returncode = upstream_code if upstream_code != pbc.success_return else -1

            if returncode == pbc.success_return:
                pro.update(task, completed=100)
    except BaseException:
        if process is not None:
            if process.stdout:
                process.stdout.close()
            _terminate_and_wait(process)
        if upstream is not None:
            _finish_upstream(upstream, err_thread, terminate=True)
        raise

    if returncode != pbc.success_return:
        parts = [s for s in ("".join(output).strip() if silent else "", "".join(upstream_err).strip()) if s]
        if parts:
            print("\n----------------------")
            print("\n".join(parts))
            print("----------------------")

    return returncode
