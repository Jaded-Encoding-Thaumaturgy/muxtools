from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import os
import re
from .tools import *
from utils.files import *
from utils.download import get_executable
from utils.types import Trim, PathLike, TrackType
from utils.log import error, debug, info, warn
from utils.format import get_absolute_track, format_from_track

__all__ = ["Eac3to", "Sox", "FFMpeg", "MkvExtract"]


def sanitize_trims(trims: Trim | list[Trim], total_frames: int = 0, uses_frames: bool = True, caller: any = None) -> list[Trim]:
    caller = caller if caller else sanitize_trims
    if not isinstance(trims, (list, tuple)):
        raise error("Trims must be a list of 2-tuples (or just one 2-tuple)", caller)
    if not isinstance(trims, list):
        trims = [trims]
    for trim in trims:
        if not isinstance(trim, tuple):
            raise error(f"The trim {trim} is not a tuple", caller)
        if len(trim) != 2:
            raise error(f"The trim {trim} needs 2 elements", caller)
        for i in trim:
            if not isinstance(i, (int, type(None))):
                raise error(f"The trim {trim} must have 2 ints or None's", caller)
        if trim[-1] == 0:
            raise error("Slices cannot end with 0, if attempting to use an empty slice, use `None`", caller)

        if trim[0] < 0:
            raise error("The first part of a trim cannot be negative.", caller)

        if trim[1] and uses_frames:
            if total_frames and trim[1] > total_frames:
                warn(f"The trim {trim} extends the frame number that was passed. Will be set to max frame.", caller, 5)
                trim[1] = total_frames - 1
            if trim[1] < 0:
                if not total_frames:
                    raise error("A trim cannot be negative if you're not passing the total frame number.", caller)
                trim[1] = total_frames + trim[1]
                if trim[1] < 0:
                    raise error(f"The negative number of the trim {trim} is out of bounds.", caller)

    return trims


class Eac3to(HasExtractor, HasTrimmer):
    @dataclass
    class Extractor(Extractor):
        """
        Extracts audio files using eac3to

        :param track:               Relative audio track number
        :param preserve_delay:      Will preserve existing container delay
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        :param append:              Specify a string of args you can pass to Eac3to
        """

        track: int = 0
        preserve_delay: bool = True
        output: PathLike | None = None
        append: str = ""

        def extract_audio(self, input: PathLike, quiet: bool = True) -> AudioFile:
            eac3to = get_executable("eac3to")
            input = ensure_path(input, self.extract_audio)
            track = get_absolute_track(input, self.track, TrackType.AUDIO)
            form = format_from_track(track)
            if not form:
                error(f"Unrecognized format: {track.format}", self.extract_audio)
                warn("Will extract as wav instead.", self.extract_audio)
                extension = "wav"
            else:
                extension = form.ext

            out = make_output(input, extension, f"extracted_{self.track}", self.output)
            p = run_commandline(f'"{eac3to}" "{input}" {track.track_id+1}: "{out}" {self.append}', quiet)
            if p == 0:
                if not out.exists():
                    pattern_str = rf"{re.escape(out.stem)} DELAY.*\.{extension}"
                    pattern = re.compile(pattern_str, re.IGNORECASE)
                    for f in os.listdir(out.parent):
                        if pattern.match(f):
                            f = Path(out.parent, f)
                            out = f.rename(f.with_stem(out.stem))
                            break

                return AudioFile(out, getattr(track, "delay_relative_to_video", 0) if self.preserve_delay else 0, input)
            else:
                raise error(f"eac3to failed to extract audio track {self.track} from '{input}'", self.extract_audio)

    @dataclass
    class Trimmer(Trimmer):
        """
        Trims audio files using eac3to.

        If the passed trim also has an end specified, it will use ffmpeg to cut that part off.

        :param trim:                Can only be a single trim
        :param trim_use_ms:         Will use milliseconds instead of frame numbers
        :param fps:                 Fps fraction that will be used for the conversion
        :param preserve_delay:      Will preserve existing container delay
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        """

        trim: Trim
        preserve_delay: bool = False
        trim_use_ms: bool = False
        fps: Fraction = Fraction(24000, 1001)
        output: PathLike | None = None

        def __post_init__(self):
            self.executable = get_executable("eac3to")

        def trim_audio(self, input: AudioFile, quiet: bool = True) -> AudioFile:
            pass


@dataclass
class MkvExtract(Extractor):
    def __post_init__(self):
        self.executable = get_executable("mkvextract")


class FFMpeg(HasExtractor, HasTrimmer):
    @dataclass
    class Extractor(Extractor):
        """
        Extracts audio files using FFMPEG

        :param track:               Relative audio track number
        :param preserve_delay:      Will preserve existing container delay
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        """

        track: int = 0
        preserve_delay: bool = True
        output: PathLike | None = None

        def __post_init__(self):
            self.executable = get_executable("ffmpeg")

        def extract_audio(self, input: PathLike, quiet: bool = True) -> AudioFile:
            pass

    @dataclass
    class Trimmer(Trimmer):
        """
        Trims audio files using FFMPEG.
        If you're working with lossless files it is strongly recommended to use SoX instead.
        If you only need a shift at the start and/or removal at the end, you should use eac3to instead.
        FFMPEG should only be a last resort kind of thing for this.

        :param trim:                Can be a single trim or a sequence of trims.
        :param trim_use_ms:         Will use milliseconds instead of frame numbers
        :param fps:                 Fps fraction that will be used for the conversion
        :param preserve_delay:      Will preserve existing container delay
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        """

        trim: Trim | list[Trim]
        preserve_delay: bool = False
        trim_use_ms: bool = False
        fps: Fraction = Fraction(24000, 1001)
        output: PathLike | None = None

        def __post_init__(self):
            self.executable = get_executable("ffmpeg")

        def trim_audio(self, input: AudioFile, quiet: bool = True) -> AudioFile:
            pass

    def has_libfdk() -> bool:
        exe = get_executable("ffmpeg")

        return False


@dataclass
class Sox(Trimmer):
    trim: Trim
    preserve_delay: bool = False
    trim_use_ms: bool = False
    fps: Fraction = Fraction(24000, 1001)
    output: PathLike | None = None
