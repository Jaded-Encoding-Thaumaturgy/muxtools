from collections.abc import Sequence
from pathlib import Path

from ..utils.env import run_commandline
from ..utils.log import error


def _run(executable: str, args: list[str], quiet: bool, action: str) -> None:
    command = [executable, "-D", "--multi-threaded", "-V0" if quiet else "-V1", *args]
    try:
        code = run_commandline(command, quiet)
    except OSError as exc:
        raise error(f"Failed to {action} audio using SoX: {exc}", "Sox") from exc
    if code:
        raise error(f"Failed to {action} audio using SoX (exit code {code})!", "Sox")


def trim_file(
    executable: str,
    source: Path,
    output: Path,
    start: float,
    end: float | None = None,
    pad_start: float = 0.0,
    quiet: bool = True,
) -> None:
    """Trim between timestamps in seconds, then optionally prepend silence."""
    if start < 0 or pad_start < 0:
        raise ValueError("Trim start and padding must be non-negative.")
    if end is not None and end <= start:
        raise ValueError("Trim start must be smaller than the end.")

    args = [str(source.resolve()), str(output.resolve()), "trim", f"{start:f}"]
    if end is not None:
        args.append(f"{end - start:f}")
    if pad_start:
        args.extend(["pad", f"{pad_start:f}", "0.000000"])
    _run(executable, args, quiet, "trim")


def concat_files(executable: str, sources: Sequence[Path], output: Path, quiet: bool = True) -> None:
    """Concatenate the trimmer's WAV intermediates in the given order."""
    args = ["--combine", "concatenate"]
    for source in sources:
        args.extend(["-t", "wav", str(source.resolve())])
    args.append(str(output.resolve()))
    _run(executable, args, quiet, "concatenate")
