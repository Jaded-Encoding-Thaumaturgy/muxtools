from shlex import split as splitcommand
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
import shutil
import os
import re

from .audioutils import format_from_track, sanitize_trims, ensure_valid_in, clean_temp_files
from .tools import *
from ..utils.files import *
from ..utils.log import error, warn, debug
from ..utils.env import get_temp_workdir
from ..utils.download import get_executable
from ..utils.parsing import parse_audioinfo
from ..utils.files import get_absolute_track
from ..utils.types import Trim, PathLike, TrackType
from ..utils.convert import frame_to_timedelta, format_timedelta, frame_to_ms

__all__ = ["Eac3to", "Sox", "FFMpeg", "MkvExtract"]


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

        :param trim:                Can be a single trim or a sequence of trims.
        :param trim_use_ms:         Will use milliseconds instead of frame numbers
        :param fps:                 Fps fraction that will be used for the conversion
        :param preserve_delay:      Will preserve existing container delay
        :param num_frames:          Total number of frames used for calculations
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        """

        trim: Trim | list[Trim]
        preserve_delay: bool = False
        trim_use_ms: bool = False
        fps: Fraction = Fraction(24000, 1001)
        num_frames: int = 0
        output: PathLike | None = None

        def _calc_delay(self, delay: int = 0, num_samples: int = 0, sample_rate: int = 48000) -> int:
            """
            Calculates the delay needed to fix the remaining sync for lossy audio.
            """
            from math import ceil, floor

            frame = num_samples * 1000 / sample_rate
            leftover = (round(delay / frame) * frame) - delay
            return ceil(leftover) if leftover > 0 else floor(leftover)

        def _targs(self, trim: Trim) -> str:
            """
            Converts trim to ffmpeg seek args.
            """
            arg = ""
            if trim[1] and trim[1] < 0 and not self.trim_use_ms:
                raise error("Negative input is not allowed for ms based trims.", FFMpeg())

            if trim[0] is not None and trim[0] > 0:
                if self.trim_use_ms:
                    arg += f" -ss {format_timedelta(timedelta(milliseconds=trim[0]))}"
                else:
                    arg += f" -ss {format_timedelta(frame_to_timedelta(trim[0], self.fps))}"
            if trim[1] is not None and trim[1] != 0:
                end_frame = self.num_frames + trim[1] if trim[1] < 0 else trim[1]
                if self.trim_use_ms:
                    arg += f" -to {format_timedelta(timedelta(milliseconds=trim[1]))}"
                else:
                    arg += f" -to {format_timedelta(frame_to_timedelta(end_frame, self.fps))}"
            return arg

        def trim_audio(self, input: AudioFile, quiet: bool = True) -> AudioFile:
            if not isinstance(input, AudioFile):
                input = AudioFile.from_file(input, self)
            self.trim = sanitize_trims(self.trim, self.num_frames, not self.trim_use_ms, caller=self)
            minfo = input.get_mediainfo()
            form = format_from_track(minfo)
            lossy = input.is_lossy()
            if not form and lossy:
                raise error(f"Unrecognized lossy format: {minfo.format}", self)

            args = [get_executable("ffmpeg"), "-hide_banner", "-i", str(input.file.resolve()), "-map", "0:a:0"]
            if lossy:
                args.extend(["-c:a", "copy"])
                out = make_output(input, form.ext, f"trimmed", self.output)
            else:
                args.extend(["-c:a", "flac", "-compression_level", "0"])
                out = make_output(input, "flac", f"trimmed", self.output)

            ainfo = parse_audioinfo(input.file, caller=self) if not input.info else input.info

            debug(f"Trimming '{input.file.stem}' with ffmpeg...", self)

            if len(self.trim) == 1:
                tr = self.trim[0]
                if lossy:
                    args[2:1] = splitcommand(self._targs(tr))
                else:
                    args.extend(splitcommand(self._targs(tr)))
                args.append(str(out.resolve()))
                if not run_commandline(args, quiet):
                    if tr[0] and lossy:
                        ms = tr[0] if self.trim_use_ms else frame_to_ms(tr[0], self.fps)
                        cont_delay = self._calc_delay(ms, ainfo.num_samples(), getattr(minfo, "sampling_rate", 48000))
                        debug(f"Additional delay of {cont_delay} ms will be applied to fix remaining sync", self)
                        if self.preserve_delay:
                            cont_delay += input.container_delay
                    else:
                        cont_delay = input.container_delay if self.preserve_delay else 0

                    debug("Done", self)
                    return AudioFile(out, cont_delay, input.source)
                else:
                    raise error("Failed to trim audio using FFMPEG!", self)
            else:
                # Not yet implemented
                pass


@dataclass
class Sox(Trimmer):
    """
    Trim lossless audio using SoX.

    :param trim:                List of Trims or a single Trim, which is a Tuple of two frame numbers or milliseconds
    :param preserve_delay:      Keeps existing container delay if True
    :param trim_use_ms:         Will use milliseconds instead of frame numbers
    :param fps:                 The fps fraction used for the calculations
    :param num_frames:          Total number of frames used for calculations
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    trim: Trim | list[Trim]
    preserve_delay: bool = False
    trim_use_ms: bool = False
    fps: Fraction = Fraction(24000, 1001)
    num_frames: int = 0
    output: PathLike | None = None

    def _conv(self, val: int | None):
        if val is None:
            return None

        if self.trim_use_ms:
            return abs(val) / 1000
        else:
            return frame_to_timedelta(abs(val), self.fps).total_seconds()

    def trim_audio(self, input: AudioFile, quiet: bool = True) -> AudioFile:
        import sox

        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        out = make_output(input, "flac", f"trimmed", self.output)
        self.trim = sanitize_trims(self.trim, self.num_frames, not self.trim_use_ms, allow_negative_start=True, caller=self)
        source = ensure_valid_in(input, dither=False, caller=self, supports_pipe=False)

        if len(self.trim) > 1:
            tempdir = get_temp_workdir()
            tempdir.mkdir(exist_ok=True)
            files_to_concat = []
            first = True
            debug(f"Generating trimmed tracks for '{input.file.stem}'...", self)
            for i, t in enumerate(self.trim):
                soxr = sox.Transformer()
                soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
                if t[0] < 0 and first:
                    soxr.trim(0, self._conv(t[1]))
                    soxr.pad(self._conv(t[0]))
                else:
                    soxr.trim(self._conv(t[0]), self._conv(t[1]))
                first = False
                tout = os.path.join(tempdir, f"{input.file.stem}_trimmed_part{i}.wav")
                soxr.build(str(source.file.resolve()), tout)
                files_to_concat.append(tout)

            debug("Concatenating the tracks...", self)
            soxr = sox.Combiner()
            soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
            formats = ["wav" for file in files_to_concat]
            soxr.set_input_format(file_type=formats)
            soxr.build(files_to_concat, str(out.resolve()), "concatenate")
            shutil.rmtree(tempdir)
            debug("Done", self)
        else:
            soxr = sox.Transformer()
            soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
            debug(f"Applying trim to '{input.file.stem}'", self)
            t = self.trim[0]
            if t[0] < 0:
                soxr.trim(0, self._conv(t[1]))
                soxr.pad(self._conv(t[0]))
            else:
                soxr.trim(self._conv(t[0]), self._conv(t[1]))
            soxr.build(str(source.file), str(out.resolve()))
            debug("Done", self)

        clean_temp_files()
        return AudioFile(out.resolve(), input.container_delay if self.preserve_delay else 0, input.source)
