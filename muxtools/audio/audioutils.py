import os
import re
import subprocess
from datetime import timedelta
from typing import Any, Literal, overload
from collections.abc import Sequence

from .preprocess import Preprocessor, Resample
from ..utils.files import make_output, ensure_path_exists
from ..muxing.muxfiles import AudioFile
from ..utils.log import debug, warn, error, danger
from ..utils.download import get_executable
from ..utils.env import get_temp_workdir, communicate_stdout
from ..utils.types import Trim, ValidInputType, PathLike
from ..utils.subprogress import run_cmd_pb, ProgressBarConfig
from ..utils.probe import TrackInfo
from ..utils.formats import AudioFormat

__all__ = ["ensure_valid_in", "sanitize_trims", "qaac_compatcheck", "has_libFDK"]


def sanitize_pre(preprocess: Preprocessor | Sequence[Preprocessor] | None = None) -> list[Preprocessor]:
    if not preprocess:
        return []
    return list(preprocess) if isinstance(preprocess, Sequence) else [preprocess]


@overload
def ensure_valid_in(
    fileIn: AudioFile,
    supports_pipe: Literal[True] = ...,
    preprocess: Preprocessor | Sequence[Preprocessor] | None = None,
    valid_type: ValidInputType = ValidInputType.FLAC,
    caller: Any = None,
) -> AudioFile | subprocess.Popen: ...


@overload
def ensure_valid_in(
    fileIn: AudioFile,
    supports_pipe: Literal[False] = ...,
    preprocess: Preprocessor | Sequence[Preprocessor] | None = None,
    valid_type: ValidInputType = ValidInputType.FLAC,
    caller: Any = None,
) -> AudioFile: ...


def ensure_valid_in(
    fileIn: AudioFile,
    supports_pipe: bool = True,
    preprocess: Preprocessor | Sequence[Preprocessor] | None = None,
    valid_type: ValidInputType = ValidInputType.FLAC,
    caller: Any = None,
) -> AudioFile | subprocess.Popen:
    """
    Ensures valid input for any encoder that accepts flac (all of them).
    Passes existing file if no need to dither and is either wav or flac.
    """
    if fileIn.has_multiple_tracks(caller):
        msg = f"'{fileIn.file.name}' is a container with multiple tracks.\n"
        msg += f"The first audio track will be {'piped' if supports_pipe else 'extracted'} using default ffmpeg."
        warn(msg, caller, 5)
    trackinfo = fileIn.get_trackinfo()
    container = fileIn.get_containerinfo()
    preprocess = sanitize_pre(preprocess)

    form = trackinfo.get_audio_format()
    if form:
        if form.is_lossy:
            danger(f"It's strongly recommended to not reencode lossy audio! ({trackinfo.codec_name})", caller, 5)
        elif form.should_not_transcode():
            warn("Encoding tracks with special DTS Features or Atmos is very much discouraged.", caller, 5)

    wont_process = not any([p.can_run(trackinfo, preprocess) for p in preprocess])

    if (form == AudioFormat.PCM and container.format_name.lower() == "wav") and wont_process:
        return fileIn
    if valid_type.allows_flac():
        valid_type = valid_type.remove_flac()
        if (form == AudioFormat.FLAC and container.format_name.lower() == "flac") and wont_process:
            return fileIn

    if valid_type == ValidInputType.FLAC:
        from .encoders import FF_FLAC

        if supports_pipe:
            return FF_FLAC(preprocess=preprocess).get_pipe(fileIn)
        else:
            return FF_FLAC(compression_level=0, preprocess=preprocess, output=os.path.join(get_temp_workdir(), "tempflac")).encode_audio(
                fileIn, temp=True
            )
    else:
        return get_pcm(fileIn, trackinfo, supports_pipe, preprocess, valid_type, caller)


def get_preprocess_args(
    fileIn: AudioFile, preprocessors: Preprocessor | Sequence[Preprocessor] | None, track_info: TrackInfo, caller: Any = None
) -> list[str]:
    preprocessors = sanitize_pre(preprocessors)
    args = list[str]()
    if any([p.can_run(track_info, preprocessors) for p in preprocessors]):
        filters = list[str]()
        for pre in [p for p in preprocessors if p.can_run(track_info, preprocessors)]:
            pre.analyze(fileIn)
            args.extend(pre.get_args(caller=caller))
            filt = pre.get_filter(caller=caller)
            if filt:
                filters.append(filt)
        if filters:
            args.extend(["-filter:a", ",".join(filters)])
    return args


def get_pcm(
    fileIn: AudioFile,
    track_info: TrackInfo,
    supports_pipe: bool = True,
    preprocess: Sequence[Preprocessor] | None = None,
    valid_type: ValidInputType = ValidInputType.RF64,
    caller: Any = None,
) -> AudioFile | subprocess.Popen:
    ffmpeg = get_executable("ffmpeg")
    args = [ffmpeg, "-i", str(fileIn.file), "-map", "0:a:0"]
    codec = "pcm_s16le" if (track_info.bit_depth or 16) == 16 else "pcm_s24le"
    filters = list[str]()
    preprocess = sanitize_pre(preprocess)
    for pre in preprocess:
        can_run = pre.can_run(track_info, preprocess)
        if can_run:
            pre.analyze(fileIn)
            args.extend(pre.get_args(caller=caller))
            filt = pre.get_filter(caller=caller)
            if filt:
                filters.append(filt)
        if isinstance(pre, Resample):
            codec = "pcm_s16le" if can_run and (pre.depth or (track_info.bit_depth or 16)) == 16 else "pcm_s24le"
    if filters:
        args.extend(["-filter:a", ",".join(filters)])
    args.extend(["-c:a", codec])
    if valid_type == ValidInputType.RF64:
        args.extend(["-rf64", "auto"])
        output = make_output(fileIn.file, "wav", "ffmpeg", temp=True)
    else:
        output = make_output(fileIn.file, "w64", "ffmpeg", temp=True)

    if supports_pipe:
        debug("Piping audio to ensure valid input using ffmpeg...", caller)
        args.extend(["-f", "wav" if valid_type == ValidInputType.RF64 else "w64", "-"])
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=False)
        return p
    else:
        debug("Preparing audio to ensure valid input using ffmpeg...", caller)
        args.append(str(output))
        if not run_cmd_pb(args, pbc=ProgressBarConfig("Preparing...", duration_from_file(fileIn))):
            return AudioFile(output, fileIn.container_delay, fileIn.source)
        else:
            raise error("Failed to convert to desired intermediary!", ensure_valid_in)


def sanitize_trims(
    trims: Trim | list[Trim] | None, total_frames: int = 0, uses_frames: bool = True, allow_negative_start: bool = False, caller: Any = None
) -> list[Trim]:
    caller = caller if caller else sanitize_trims
    if trims is None:
        return []
    if not isinstance(trims, (list, tuple)):
        raise error("Trims must be a list of 2-tuples (or just one 2-tuple)", caller)
    if not isinstance(trims, list):
        trims = [trims]
    for index, trim in enumerate(trims):
        if not isinstance(trim, tuple):
            raise error(f"The trim {trim} is not a tuple", caller)
        if len(trim) != 2:
            raise error(f"The trim {trim} needs 2 elements", caller)
        for i in trim:
            if not isinstance(i, (int, type(None))):
                raise error(f"The trim {trim} must have 2 ints or None's", caller)
        if trim[-1] == 0:
            raise error("Slices cannot end with 0, if attempting to use an empty slice, use `None`", caller)

        if trim[0] and trim[0] < 0 and not allow_negative_start and index == 0:
            raise error("The first part of a trim cannot be negative.", caller)

        has_negative = (trim[1] is not None and trim[1] < 0) or (trim[0] is not None and trim[0] < 0)
        if not uses_frames and has_negative and index != 0:
            raise error("If you use milliseconds to trim you cannot use negative values.")

        if not total_frames and has_negative:
            raise error("If you want to use negative trims you gotta pass a total frame number.")

        if trim[1] is not None and trim[1] < 0:
            trim = (trim[0], total_frames + trim[1])
            trims[index] = trim

        if trim[0] is not None and trim[0] < 0:
            if allow_negative_start and index == 0:
                continue
            trims[index] = (total_frames + trim[0], trim[1])

    return trims


def duration_from_file(fileIn: PathLike | AudioFile, track: int = 0, caller: Any = None) -> timedelta:
    from ..utils.parsing import timedelta_from_formatted

    if isinstance(fileIn, AudioFile):
        if fileIn.duration:
            return fileIn.duration
        else:
            fileIn = fileIn.file

    args = [
        get_executable("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        str(track),
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        "-sexagesimal",
        str(ensure_path_exists(fileIn, duration_from_file)),
    ]

    try:
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode != 0:
            raise Exception("Failed to parse")
        return timedelta_from_formatted((p.stderr + p.stdout).strip())
    except:
        warn("Could not parse duration from track. Will assume 24 minutes.", caller)
        return timedelta(minutes=24)


def has_libFDK() -> bool:
    """
    Returns if whatever installation of ffmpeg being used has been compiled with libFDK
    """
    exe = get_executable("ffmpeg")
    _, readout = communicate_stdout([exe, "-encoders"])
    for line in readout.splitlines():
        if "libfdk_aac" in line.lower():
            return True
    return False


def qaac_compatcheck() -> str:
    """
    Checks if the qAAC installation has libflac and returns the qaac version.
    """
    exe = get_executable("qaac")
    _, readout = communicate_stdout([exe, "--check"])
    if "libflac" not in readout.lower():
        raise error(
            "Your installation of qaac does not have libFLAC.\nIt is needed for proper piping from ffmpeg etc."
            + "\nYou can download it from https://github.com/xiph/flac/releases or run muxtools deps"
            + "\nFor installation check https://github.com/nu774/qaac/wiki/Installation",
            "QAAC",
        )

    if match := re.search(r"qaac (\d+\.\d+(?:\.\d+)?)", readout, re.I):
        return match.group(1)

    return "Unknown version"
