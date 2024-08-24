from shlex import split as splitcommand
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from typing import Sequence
from pathlib import Path
import os
import re

from .audioutils import format_from_track, is_fancy_codec, sanitize_trims, ensure_valid_in, duration_from_file
from .tools import Extractor, Trimmer, AudioFile, HasExtractor, HasTrimmer
from ..utils.files import ensure_path_exists, make_output, clean_temp_files
from ..utils.log import error, warn, debug, info
from ..utils.download import get_executable
from ..utils.parsing import parse_audioinfo
from ..utils.files import get_absolute_track
from ..utils.types import Trim, PathLike, TrackType
from ..utils.env import get_temp_workdir, run_commandline, communicate_stdout
from ..utils.subprogress import run_cmd_pb, ProgressBarConfig
from ..utils.convert import frame_to_timedelta, format_timedelta, frame_to_ms

__all__ = ["Eac3to", "Sox", "FFMpeg", "MkvExtract"]


EAC3TO_DELAY_REGEX = r"remaining delay of (?P<delay>(?:-|\+)?\d+)ms could not"


def _escape_name(s: str) -> str:
    """Makes filepaths suitable for ffmpeg concat files"""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace(" ", "\\ ")


@dataclass
class Eac3to(Extractor):
    """
    Extracts audio files using eac3to

    :param track:               Relative audio track number
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    :param append:              Specify a string of args you can pass to Eac3to
    """

    track: int = 0
    output: PathLike | None = None
    append: str = ""

    def extract_audio(self, input: PathLike, quiet: bool = True) -> AudioFile:
        eac3to = get_executable("eac3to")
        input = ensure_path_exists(input, self)
        track = get_absolute_track(input, self.track, TrackType.AUDIO, self)
        form = format_from_track(track)
        if not form:
            lossy = getattr(track, "compression_mode", "lossless").lower() == "lossy"
            if lossy:
                raise error(f"Unrecognized lossy format: {track.format}", self)
            else:
                warn(f"Unrecognized format: {track.format}\nWill extract as wav instead.", self, 2)
            extension = "wav"
        else:
            extension = form.ext

        info(f"Extracting audio track {self.track} from '{input.stem}'...", self)

        out = make_output(input, extension, f"extracted_{self.track}", self.output)
        code, stdout = communicate_stdout(f'"{eac3to}" "{input}" {track.track_id+1}: "{out}" {self.append}')
        if code == 0:
            if not out.exists():
                pattern_str = rf"{re.escape(out.stem)} DELAY.*\.{extension}"
                pattern = re.compile(pattern_str, re.IGNORECASE)
                for f in os.listdir(out.parent):
                    if pattern.match(f):
                        f = Path(out.parent, f)
                        out = f.rename(f.with_stem(out.stem))
                        break
            delay = 0

            pattern = re.compile(EAC3TO_DELAY_REGEX)
            for line in stdout.splitlines():
                match = re.search(pattern, line)
                if match:
                    delay = int(match.group("delay"))
                    debug(f"Additional delay of {delay} ms will be applied to fix remaining sync.", self)
            return AudioFile(out, delay, input, duration=duration_from_file(input, self.track))
        else:
            print("", stdout, "")
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
        :param full_analysis:       Analyze entire track for bitdepth and other statistics.
                                    This *will* take quite a bit of time.
        """

        track: int = 0
        preserve_delay: bool = True
        output: PathLike | None = None
        full_analysis: bool = False

        def extract_audio(self, input: PathLike, quiet: bool = True, is_temp: bool = False, force_flac: bool = False) -> AudioFile:
            ffmpeg = get_executable("ffmpeg")
            input = ensure_path_exists(input, self)
            track = get_absolute_track(input, self.track, TrackType.AUDIO, self, quiet_fail=self._no_print)
            form = format_from_track(track)
            if not self._no_print:
                info(f"Extracting audio track {self.track} from '{input.stem}'...", self)
            if not form:
                ainfo = parse_audioinfo(input, self.track, self, full_analysis=self.full_analysis, quiet=self._no_print)
                lossy = getattr(track, "compression_mode", "lossless").lower() == "lossy"
                if lossy:
                    raise error(f"Unrecognized lossy format found: {track.format}", self)
                else:
                    extension = "wav"
                    warn("Unrecognized format: {track.format}\nWill extract as wav instead.", self, 2)
                    out = make_output(input, extension, f"extracted_{self.track}", self.output, temp=is_temp)
            else:
                ainfo = parse_audioinfo(input, self.track, self, form.ext == "thd", full_analysis=self.full_analysis, quiet=self._no_print)
                lossy = form.lossy
                extension = form.ext
                out = make_output(input, extension, f"extracted_{self.track}", self.output, temp=is_temp)

            args = [ffmpeg, "-hide_banner", "-i", str(input.resolve()), "-map_chapters", "-1", "-map", f"0:a:{self.track}"]

            specified_depth = getattr(track, "bit_depth", 16)
            if str(specified_depth) not in ainfo.stats.bit_depth and not lossy and not is_fancy_codec(track) and specified_depth is not None:
                actual_depth = int(ainfo.stats.bit_depth) if "/" not in ainfo.stats.bit_depth else int(ainfo.stats.bit_depth.split("/")[0])
                debug(f"Detected fake/padded {specified_depth} bit. Actual depth is {actual_depth} bit.", self)
                if specified_depth - actual_depth > 4:
                    debug("Track will be outputted as flac and truncated to 16 bit instead.", self)
                    out = make_output(input, "flac", f"extracted_{self.track}", self.output, temp=is_temp)
                    args.extend(["-c:a", "flac", "-sample_fmt", "s16"])
            else:
                if force_flac and extension in ["dts", "wav"] and not lossy:
                    out = make_output(input, "flac", f"extracted_{self.track}", self.output, temp=is_temp)
                    args.extend(["-c:a", "flac", "-compression_level", "0"])
                else:
                    if extension == "wav":
                        args.extend(["-c:a", "pcm_s16le" if specified_depth <= 16 else "pcm_s24le", "-rf64", "auto"])
                    else:
                        args.extend(["-c:a", "copy"])
                        if extension == "dtshd" or extension == "dts":
                            # FFMPEG screams about dtshd not being a known output format but ffmpeg -formats lists it....
                            args.extend(["-f", "dts"])

            args.append(str(out))
            duration = duration_from_file(input, self.track)
            if not run_cmd_pb(args, quiet, ProgressBarConfig("Extracting...", duration)):
                return AudioFile(out, getattr(track, "delay_relative_to_video", 0) if self.preserve_delay else 0, input, None, ainfo, duration)
            else:
                raise error("Failed to extract audio track using ffmpeg", self)

    @dataclass
    class Trimmer(Trimmer):
        """
        Trims audio files using FFMPEG.
        If you're working with lossless files it is strongly recommended to use SoX instead.

        :param trim:                Can be a single trim or a sequence of trims.
        :param trim_use_ms:         Will use milliseconds instead of frame numbers
        :param fps:                 Fps fraction that will be used for the conversion. Also accepts a timecode (v2) file.
        :param preserve_delay:      Will preserve existing container delay
        :param num_frames:          Total number of frames used for calculations
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        """

        trim: Trim | list[Trim] | None = None
        preserve_delay: bool = False
        trim_use_ms: bool = False
        fps: Fraction | PathLike = Fraction(24000, 1001)
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
            if lossy or is_fancy_codec(minfo):
                args.extend(["-c:a", "copy"])
                extension = form.ext
            else:
                args.extend(["-c:a", "flac", "-compression_level", "0"])
                extension = "flac"

            out = make_output(input.file, extension, "trimmed", self.output)
            ainfo = parse_audioinfo(input.file, caller=self) if not input.info else input.info

            if len(self.trim) == 1:
                info(f"Trimming '{input.file.stem}' with ffmpeg...", self)
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
                info(f"Generating trimmed tracks for '{input.file.stem}'...", self)
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
                info("Concatenating the tracks...", self)
                concat_f = os.path.join(get_temp_workdir(), "concat.txt")
                with open(concat_f, "w") as f:
                    f.writelines([f"file {_escape_name(c)}\n" for c in concat])

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
    class Concat:
        """
        Concat two or more audio files using FFMPEG.
        (Also transcodes to FLAC if the formats don't match)

        :param files:       List of PathLike or AudioFile to concat.

        """

        files: Sequence[PathLike] | Sequence[AudioFile]
        output: PathLike | None = None

        def concat_audio(self, quiet: bool = True) -> AudioFile:
            audio_files = list[AudioFile]()
            for f in self.files:
                if isinstance(f, AudioFile):
                    audio_files.append(f)
                    continue
                audio_files.append(FFMpeg.Extractor().extract_audio(f))

            if any([af.has_multiple_tracks(self) for af in audio_files]):
                raise error("One or more files passed have more than one audio track!", self)

            info(f"Concatenating {len(audio_files)} audio tracks...", self)

            concat_file = get_temp_workdir() / "concat.txt"
            with open(concat_file, "w", encoding="utf-8") as f:
                f.writelines([f"file {_escape_name(str(af.file.resolve()))}\n" for af in audio_files])

            first_format = format_from_track(audio_files[0].get_mediainfo())

            format_mismatch = not all([format_from_track(af.get_mediainfo()).format == first_format.format for af in audio_files[1:]])
            if format_mismatch or first_format.ext == "wav":
                out_codec = "flac"
                out_ext = "flac"
            else:
                out_codec = "copy"
                out_ext = first_format.ext

            output = make_output(audio_files[0].file, out_ext, "concat", self.output)
            args = [get_executable("ffmpeg"), "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", out_codec, str(output)]

            if not run_commandline(args, quiet):
                debug("Done", self)
                clean_temp_files()

                durations = [af.duration for af in audio_files if af.duration]
                final_dura = timedelta(milliseconds=0)
                for dura in durations:
                    final_dura += dura

                return AudioFile(output, audio_files[0].container_delay, audio_files[0].source, duration=final_dura)
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
    :param fps:                 The fps fraction used for the calculations. Also accepts a timecode (v2) file.
    :param num_frames:          Total number of frames used for calculations
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    trim: Trim | list[Trim] | None = None
    preserve_delay: bool = False
    trim_use_ms: bool = False
    fps: Fraction | PathLike = Fraction(24000, 1001)
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
        out = make_output(input.file, "flac", "trimmed", self.output)
        self.trim = sanitize_trims(self.trim, self.num_frames, not self.trim_use_ms, allow_negative_start=True, caller=self)
        source = ensure_valid_in(input, caller=self, supports_pipe=False)

        if len(self.trim) > 1:
            files_to_concat = []
            first = True
            info(f"Generating trimmed tracks for '{input.file.stem}'...", self)
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

            info("Concatenating the tracks...", self)
            soxr = sox.Combiner()
            soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
            formats = ["wav" for file in files_to_concat]
            soxr.set_input_format(file_type=formats)
            soxr.build(files_to_concat, str(out.resolve()), "concatenate")
            debug("Done", self)
        else:
            soxr = sox.Transformer()
            soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
            info(f"Applying trim to '{input.file.stem}'", self)
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
