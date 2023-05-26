import os
import re
import subprocess
from shutil import rmtree
from pymediainfo import Track
from functools import cmp_to_key


from ..utils.log import warn, error
from ..muxing.muxfiles import AudioFile
from ..utils.env import get_temp_workdir
from ..utils.download import get_executable
from ..utils.types import DitherType, Trim, AudioFormat

__all__ = ["ensure_valid_in", "sanitize_trims", "format_from_track", "is_fancy_codec", "has_libFLAC", "has_libFDK"]


def ensure_valid_in(
    input: AudioFile,
    supports_pipe: bool = True,
    dither: bool = True,
    dither_type: DitherType = DitherType.TRIANGULAR,
    caller: any = None,
) -> AudioFile | subprocess.Popen:
    """
    Ensures valid input for any encoder that accepts flac (all of them).
    Passes existing file if no need to dither and is either wav or flac.
    """
    from .encoders import FF_FLAC

    def getflac(input: AudioFile):
        if supports_pipe:
            return FF_FLAC(dither=dither, dither_type=dither_type).get_pipe(input)
        else:
            return FF_FLAC(
                compression_level=0, dither=dither, dither_type=dither_type, output=os.path.join(get_temp_workdir(), "tempflac")
            ).encode_audio(input, temp=True)

    if input.has_multiple_tracks(caller):
        msg = f"'{input.name}' is a container with multiple tracks.\n"
        msg += f"The first audio track will be {'piped' if supports_pipe else 'extracted'} using default ffmpeg."
        warn(msg, caller, 5)

    minfo = input.get_mediainfo()
    if is_fancy_codec(minfo):
        warn("Encoding tracks with special DTS Features or Atmos is very much discouraged.", caller, 10)
    form = minfo.format.lower()
    if "wav" in form or "flac" in form or "pcm" in form:
        if minfo.bit_depth > 16 and dither:
            return getflac(input)
        return input
    else:
        if input.is_lossy():
            warn(f"It's strongly recommended to not reencode lossy audio! ({minfo.format})", caller, 5)
        return getflac(input)


def compare_trims(trim: Trim, trim2: Trim):
    if trim[0] is None and trim2[0] is not None:
        return -1
    elif trim[0] is not None and trim2[0] is None:
        return 1
    else:
        if trim[0] is None and trim2[0] is None:
            return trim[1] - trim2[1]
        else:
            return trim[0] - trim2[0]


def clean_trims(trims: list[Trim]):
    sorted_trims = sorted(trims, key=cmp_to_key(compare_trims))

    final_trims = []
    for start, end in sorted_trims:
        if final_trims:
            prev_start, prev_end = final_trims[-1]
            if start is None and prev_end is not None:
                continue
            elif prev_end is not None and prev_end >= start:
                final_trims[-1] = (prev_start, max(prev_end, end))
            elif prev_end is None and end is None:
                continue
            else:
                final_trims.append((start, end))
        elif start is not None or end is not None:
            final_trims.append((start, end))

    return final_trims


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

        if trim[0] and trim[0] < 0 and not allow_negative_start:
            raise error("The first part of a trim cannot be negative.", caller)

        if trim[1] and uses_frames:
            if total_frames and trim[1] > total_frames:
                warn(f"The trim {trim} extends the frame number that was passed. Will be set to max frame.", caller, 5)
                trims[index] = (trim[0], total_frames - 1)
            if trim[1] < 0:
                if not total_frames:
                    raise error("A trim cannot be negative if you're not passing the total frame number.", caller)
                new_val = total_frames + trim[1]
                trims[index] = (trim[0], new_val)
                if new_val < 0:
                    raise error(f"The negative number of the trim {trim} is out of bounds.", caller)

    return clean_trims(trims)


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
    AudioFormat("DTS XLL",      "dtshd",    "A_DTS", False), # Can be HD-MA or Headphone X or X, who the fuck knows
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
    if codec_id == "A_TRUEHD".casefold():
        # If it contains something other than "MLP FBA" it's probably atmos
        return bool(re.sub("MLP FBA", "", str(track.format).strip(), re.IGNORECASE))
    elif codec_id == "A_DTS".casefold():
        # Not even lossless if this doesn't exist
        if not hasattr(track, "format_additionalfeatures"):
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
    for line in p.stderr.splitlines():
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
    for line in p.stderr.splitlines():
        if "libflac" in line.lower():
            return True
    return False
