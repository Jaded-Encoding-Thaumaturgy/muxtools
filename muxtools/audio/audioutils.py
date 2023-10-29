import os
import re
import subprocess
from typing import Sequence

from pymediainfo import Track, MediaInfo

from .preprocess import Preprocessor, Resample
from ..utils.files import make_output
from ..muxing.muxfiles import AudioFile
from ..utils.log import debug, warn, error
from ..utils.download import get_executable
from ..utils.env import get_temp_workdir, run_commandline
from ..utils.types import DitherType, Trim, AudioFormat, ValidInputType

__all__ = ["ensure_valid_in", "sanitize_trims", "format_from_track", "is_fancy_codec", "has_libFLAC", "has_libFDK"]


def sanitize_pre(preprocess: Preprocessor | Sequence[Preprocessor] | None = None) -> list[Preprocessor]:
    if not preprocess:
        return []
    return list(preprocess) if isinstance(preprocess, Sequence) else [preprocess]


def ensure_valid_in(
    fileIn: AudioFile,
    supports_pipe: bool = True,
    preprocess: Preprocessor | Sequence[Preprocessor] | None = None,
    valid_type: ValidInputType = ValidInputType.FLAC,
    caller: any = None,
) -> AudioFile | subprocess.Popen:
    """
    Ensures valid input for any encoder that accepts flac (all of them).
    Passes existing file if no need to dither and is either wav or flac.
    """
    if fileIn.has_multiple_tracks(caller):
        msg = f"'{fileIn.file.name}' is a container with multiple tracks.\n"
        msg += f"The first audio track will be {'piped' if supports_pipe else 'extracted'} using default ffmpeg."
        warn(msg, caller, 5)
    minfo = MediaInfo.parse(fileIn.file)
    trackinfo = fileIn.get_mediainfo(minfo)
    container = fileIn.get_containerinfo(minfo)
    has_containerfmt = container is not None and hasattr(container, "format") and container.format is not None
    preprocess = sanitize_pre(preprocess)

    if is_fancy_codec(trackinfo):
        warn("Encoding tracks with special DTS Features or Atmos is very much discouraged.", caller, 10)
    form = trackinfo.format.lower()
    if fileIn.is_lossy():
        warn(f"It's strongly recommended to not reencode lossy audio! ({trackinfo.format})", caller, 5)

    wont_process = not any([p.can_run(trackinfo, preprocess) for p in preprocess])

    if (form == "wave" or (has_containerfmt and container.format.lower() == "wave")) and wont_process:
        return fileIn
    if valid_type.allows_flac():
        valid_type = valid_type.remove_flac()
        if (form == "flac" or (has_containerfmt and container.format.lower() == "flac")) and wont_process:
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


def get_pcm(
    fileIn: AudioFile,
    minfo: Track,
    supports_pipe: bool = True,
    preprocess: Sequence[Preprocessor] | None = None,
    valid_type: ValidInputType = ValidInputType.RF64,
    caller: any = None,
) -> AudioFile | subprocess.Popen:
    ffmpeg = get_executable("ffmpeg")
    args = [ffmpeg, "-i", str(fileIn.file), "-map", "0:a:0"]
    cope = "pcm_s24be" if valid_type == ValidInputType.AIFF else "pcm_s24le"
    codec = "pcm_s16le" if getattr(minfo, "bit_depth", 16) == 16 else cope
    filters = list[str]()
    preprocess = sanitize_pre(preprocess)
    for pre in preprocess:
        can_run = pre.can_run(minfo, preprocess)
        if can_run:
            pre.analyze(fileIn)
            args.extend(pre.get_args(caller=caller))
            filt = pre.get_filter(caller=caller)
            if filt:
                filters.append(filt)
        if isinstance(pre, Resample):
            codec = "pcm_s16le" if can_run and (pre.depth or getattr(minfo, "bit_depth", 16)) == 16 else cope
    if filters:
        args.extend(["-filter:a", ",".join(filters)])
    args.extend(["-c:a", codec])
    if valid_type == ValidInputType.RF64:
        args.extend(["-rf64", "auto"])
        output = make_output(fileIn.file, "wav", "ffmpeg", temp=True)
    else:
        output = make_output(fileIn.file, "aiff" if valid_type == ValidInputType.AIFF else "w64", "ffmpeg", temp=True)

    if supports_pipe and valid_type != ValidInputType.RF64:
        debug(f"Piping audio to ensure valid input using ffmpeg...", caller)
        args.extend(["-f", "aiff" if valid_type == ValidInputType.AIFF else "w64", "-"])
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=False)
        return p
    else:
        debug(f"Preparing audio to ensure valid input using ffmpeg...", caller)
        args.append(str(output))
        if not run_commandline(args):
            return AudioFile(output, fileIn.container_delay, fileIn.source)
        else:
            raise error("Failed to convert to desired intermediary!", ensure_valid_in)


def sanitize_trims(
    trims: Trim | list[Trim], total_frames: int = 0, uses_frames: bool = True, allow_negative_start: bool = False, caller: any = None
) -> list[Trim]:
    caller = caller if caller else sanitize_trims
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
        if not uses_frames and has_negative:
            raise error(f"If you use milliseconds to trim you cannot use negative values.")

        if not total_frames and has_negative:
            raise error(f"If you want to use negative trims you gotta pass a total frame number.")

        if trim[1] is not None and trim[1] < 0:
            trim = (trim[0], total_frames + trim[1])
            trims[index] = trim

        if trim[0] is not None and trim[0] < 0:
            if allow_negative_start and index == 0:
                continue
            trims[index] = (total_frames + trim[0], trim[1])

    return trims


# Of course these are not all of the formats possible but those are the most common from what I know.
# fmt: off
formats = [
    # Lossy
    AudioFormat("AC-3",         "ac3",      "A_AC3"),
    AudioFormat("E-AC-3",       "eac3",     "A_EAC3"),
    AudioFormat("AAC*",         "m4a",      "A_AAC*"), # Lots of different AAC formats idk what they mean, don't care either
    AudioFormat("Opus",         "opus",     "A_OPUS"),
    AudioFormat("Vorbis",       "ogg",      "A_VORBIS"),
    AudioFormat("/",            "mp3",      "mp4a-6B"), # MP3 has the format name split up into 3 variables so we're gonna ignore this
    
    # Lossless
    AudioFormat("FLAC",         "flac",     "A_FLAC", False),
    AudioFormat("MLP FBA*",     "thd",      "A_TRUEHD", False), # Atmos stuff has some more shit in the format name
    AudioFormat("PCM*",         "wav",      "A_PCM*", False),

    # Disgusting DTS Stuff
    AudioFormat("DTS XLL*",     "dtshd",    "A_DTS", False), # Can be HD-MA or Headphone X or X, who the fuck knows
    AudioFormat("DTS",          "dts",      "A_DTS"), # Can be lossy
]
# fmt: on


def format_from_track(track: Track) -> AudioFormat | None:
    for format in formats:
        f = str(track.format)
        if hasattr(track, "format_additionalfeatures") and track.format_additionalfeatures:
            f = f"{f} {track.format_additionalfeatures}"
        if "*" in format.format:
            # matches = filter([f.lower()], format.format.lower())
            if re.match(format.format.replace("*", ".*"), f, re.IGNORECASE):
                return format
        else:
            if format.format.casefold() == f.casefold():
                return format

        if "*" in format.codecid:
            # matches = filter([str(track.codec_id).lower()], format.codecid)
            if re.match(format.codecid.replace("*", ".*"), str(track.codec_id), re.IGNORECASE):
                return format
        else:
            if format.codecid.casefold() == str(track.codec_id).casefold():
                return format
    return None


def is_fancy_codec(track: Track) -> bool:
    """
    Tries to check if a track is some fancy DTS (X, Headphone X) or TrueHD with Atmos

    :param track:   Input track to check
    """
    codec_id = str(track.codec_id).casefold()
    if codec_id == "A_TRUEHD".casefold() or "truehd" in track.commercial_name.lower():
        if "atmos" in track.commercial_name.lower():
            return True
        if not hasattr(track, "format_additionalfeatures") or not track.format_additionalfeatures:
            return False
        # If it contains something other than the fallback AC-3 track it's probably atmos
        return "ch" in track.format_additionalfeatures
    elif codec_id == "A_DTS".casefold() or "dts" in track.format.lower():
        # Not even lossless if this doesn't exist
        if not hasattr(track, "format_additionalfeatures") or not track.format_additionalfeatures:
            return False
        # If those additional features contain something after removing "XLL" its some fancy stuff
        return bool(re.sub("XLL", "", str(track.format_additionalfeatures).strip(), re.IGNORECASE))

    return False


def has_libFDK() -> bool:
    """
    Returns if whatever installation of ffmpeg being used has been compiled with libFDK
    """
    exe = get_executable("ffmpeg")
    p = subprocess.run([exe, "-encoders"], capture_output=True, text=True)
    output = p.stderr + p.stdout
    for line in output.splitlines():
        if "libfdk_aac" in line.lower():
            return True
    return False


def has_libFLAC() -> bool:
    """
    Returns if whatever installation of qaac being used has libFLAC
    and as such can accept flac input
    """
    exe = get_executable("qaac")
    p = subprocess.run([exe, "--check"], capture_output=True, text=True)
    output = p.stderr + p.stdout
    for line in output.splitlines():
        if "libflac" in line.lower():
            return True
    return False


def qaac_compatcheck():
    if not has_libFLAC():
        raise error(
            "Your installation of qaac does not have libFLAC.\nIt is needed for proper piping from ffmpeg etc."
            + "\nYou can download it from https://github.com/xiph/flac/releases"
            + "\nFor installation check https://github.com/nu774/qaac/wiki/Installation",
            "QAAC",
        )
