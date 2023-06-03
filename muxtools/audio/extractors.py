from shlex import split as splitcommand
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
import shutil
import os
import re

from .audioutils import format_from_track, is_fancy_codec, sanitize_trims, ensure_valid_in
from .tools import *
from ..utils.files import *
from ..utils.log import error, warn, debug
from ..utils.download import get_executable
from ..utils.parsing import parse_audioinfo
from ..utils.files import get_absolute_track
from ..utils.types import Trim, PathLike, TrackType
from ..utils.env import get_temp_workdir, run_commandline
from ..utils.convert import frame_to_timedelta, format_timedelta, frame_to_ms

__all__ = ["Eac3to", "Sox", "FFMpeg", "MkvExtract"]


@dataclass
class Eac3to(Extractor):
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
        input = ensure_path_exists(input, self)
        track = get_absolute_track(input, self.track, TrackType.AUDIO, self)
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
        :param append:              Specify a string of args you can pass to Eac3to
        """

        track: int = 0
        preserve_delay: bool = True
        output: PathLike | None = None

        def extract_audio(self, input: PathLike, quiet: bool = True) -> AudioFile:
            ffmpeg = get_executable("ffmpeg")
            input = ensure_path_exists(input, self)
            track = get_absolute_track(input, self.track, TrackType.AUDIO, self)
            form = format_from_track(track)
            debug(f"Extracting audio track from '{input.stem}' using ffmpeg...", self)
            if not form:
                ainfo = parse_audioinfo(input, self.track, self)
                lossy = getattr(track, "compression_mode", "lossless").lower() == "lossy"
                if lossy:
                    raise error(f"Unrecognized lossy format found: {track.format}", self)
                else:
                    extension = "wav"
                    warn("Unrecognized format: {track.format}\nWill extract as wav instead.", self, 2)
                    out = make_output(input, extension, f"extracted_{self.track}", self.output)
            else:
                ainfo = parse_audioinfo(input, self.track, self, form.ext == "thd")
                lossy = form.lossy
                extension = form.ext
                out = make_output(input, extension, f"extracted_{self.track}", self.output)

            args = [ffmpeg, "-hide_banner", "-i", str(input.resolve()), "-map_chapters", "-1", "-map", f"0:a:{self.track}"]

            specified_depth = getattr(track, "bit_depth", 16)
            if str(specified_depth) not in ainfo.stats.bit_depth and not lossy and not is_fancy_codec(track) and specified_depth is not None:
                actual_depth = int(ainfo.stats.bit_depth) if "/" not in ainfo.stats.bit_depth else int(ainfo.stats.bit_depth.split("/")[0])
                debug(f"Detected fake/padded {specified_depth} bit. Actual depth is {actual_depth} bit.", self)
                if specified_depth - actual_depth > 4:
                    debug("Track will be outputted as flac and truncated to 16 bit instead.", self)
                    out = make_output(input, "flac", f"extracted_{self.track}", self.output)
                    args.extend(["-c:a", "flac", "-sample_fmt", "s16"])
            else:
                if extension == "wav":
                    args.extend(["-c:a", "pcm_s16le" if specified_depth == 16 else "pcm_s24le"])
                else:
                    args.extend(["-c:a", "copy"])
                    if extension == "dtshd" or extension == "dts":
                        # FFMPEG screams about dtshd not being a known output format but ffmpeg -formats lists it....
                        args.extend(["-f", "dts"])
            args.append(str(out))

            if not run_commandline(args, quiet):
                debug("Done", self)
                return AudioFile(out, getattr(track, "delay_relative_to_video", 0) if self.preserve_delay else 0, input, ainfo)
            else:
                raise error("Failed to extract audio track using ffmpeg", self)

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

        trim: Trim | list[Trim] | None = None
        preserve_delay: bool = False
        trim_use_ms: bool = False
        fps: Fraction = Fraction(24000, 1001)
        num_frames: int = 0
        output: PathLike | None = None

        def _escape_name(self, s: str) -> str:
            """Makes filepaths suitable for ffmpeg concat files"""
            return s.replace("\\", "\\\\").replace("'", "\\'").replace(" ", "\\ ")

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
            if lossy or is_fancy_codec(minfo):
                args.extend(["-c:a", "copy"])
                extension = form.ext
            else:
                args.extend(["-c:a", "flac", "-compression_level", "0"])
                extension = "flac"

            out = make_output(input.file, extension, f"trimmed", self.output)
            ainfo = parse_audioinfo(input.file, caller=self) if not input.info else input.info

            if len(self.trim) == 1:
                debug(f"Trimming '{input.file.stem}' with ffmpeg...", self)
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
                debug(f"Generating trimmed tracks for '{input.file.stem}'...", self)
                concat: list = []
                first = True
                for i, tr in enumerate(self.trim):
                    nArgs = args.copy()
                    if lossy:
                        nArgs[2:1] = splitcommand(self._targs(tr))
                        if first:
                            cont_delay = self._calc_delay(ms, ainfo.num_samples(), getattr(minfo, "sampling_rate", 48000))
                            debug(f"Additional delay of {cont_delay} ms will be applied to fix remaining sync", self)
                            first = False
                    else:
                        nArgs.extend(splitcommand(self._targs(tr)))
                        if first:
                            cont_delay = input.container_delay if self.preserve_delay else 0
                            first = False
                    nout = os.path.join(get_temp_workdir(), f"{input.file.stem}_part{i}.{extension}")
                    nArgs.append(nout)
                    if not run_commandline(nArgs, quiet):
                        concat.append(nout)
                    else:
                        raise error("Failed to trim audio using FFMPEG!", self)
                debug("Concatenating the tracks...", self)
                concat_f = os.path.join(get_temp_workdir(), "concat.txt")
                with open(concat_f, "w") as f:
                    f.writelines([f"file {self._escape_name(c)}\n" for c in concat])

                args[3] = concat_f
                args[2:1] = ["-f", "concat", "-safe", "0"]
                args.append(str(out.resolve()))

                if not run_commandline(args, quiet):
                    debug("Done", self)
                    clean_temp_files()
                    return AudioFile(out, cont_delay, input.source)
                else:
                    clean_temp_files()
                    raise error("Failed to trim audio using FFMPEG!", self)


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

    trim: Trim | list[Trim] | None = None
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
        out = make_output(input.file, "flac", f"trimmed", self.output)
        self.trim = sanitize_trims(self.trim, self.num_frames, not self.trim_use_ms, allow_negative_start=True, caller=self)
        source = ensure_valid_in(input, dither=False, caller=self, supports_pipe=False)

        if len(self.trim) > 1:
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
                tout = os.path.join(get_temp_workdir(), f"{input.file.stem}_trimmed_part{i}.wav")
                soxr.build(str(source.file.resolve()), tout)
                files_to_concat.append(tout)

            debug("Concatenating the tracks...", self)
            soxr = sox.Combiner()
            soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
            formats = ["wav" for file in files_to_concat]
            soxr.set_input_format(file_type=formats)
            soxr.build(files_to_concat, str(out.resolve()), "concatenate")
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
