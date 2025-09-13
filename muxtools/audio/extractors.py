from shlex import split as splitcommand
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from typing import Sequence
from pathlib import Path
from itertools import takewhile
import subprocess
import os
import re

from .audioutils import sanitize_trims, ensure_valid_in, duration_from_file
from .tools import Extractor, Trimmer, AudioFile, HasExtractor, HasTrimmer
from ..utils.files import ensure_path_exists, make_output, clean_temp_files
from ..utils.log import error, warn, debug, info, danger
from ..utils.download import get_executable
from ..utils.parsing import parse_audioinfo
from ..utils.types import Trim, PathLike, TrackType, TimeSourceT, TimeScaleT, TimeScale
from ..utils.env import get_temp_workdir, run_commandline, communicate_stdout, get_binary_version
from ..utils.subprogress import run_cmd_pb, ProgressBarConfig
from ..utils.convert import format_timedelta, resolve_timesource_and_scale, TimeType
from ..utils.probe import ParsedFile

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

    def extract_audio(self, input: PathLike, quiet: bool = True, is_temp: bool = False, force_flac: bool = False) -> AudioFile:
        eac3to = get_executable("eac3to")
        input = ensure_path_exists(input, self)
        parsed = ParsedFile.from_file(input, self)
        track = parsed.find_tracks(relative_id=self.track, type=TrackType.AUDIO, caller=self, error_if_empty=True)[0]
        form = track.get_audio_format()
        if not form:
            danger(f"Unrecognized format: {track.codec_name}\nWill extract as wav instead.", self, 2)
            extension = "wav"
        else:
            extension = form.extension

        info(f"Extracting audio track {self.track} from '{input.stem}'...", self)

        out = make_output(input, extension, f"extracted_{self.track}", self.output)
        code, stdout = communicate_stdout(f'"{eac3to}" "{input}" {track.index + 1}: "{out}" {self.append}')
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
        :param skip_analysis:       Skip the audio analysis with FLAC for wasted bits on lossless audio.
        """

        track: int = 0
        preserve_delay: bool = True
        output: PathLike | None = None
        skip_analysis: bool = False

        def __post_init__(self):
            self.executable = get_executable("ffmpeg")

        def extract_audio(self, input: PathLike, quiet: bool = True, is_temp: bool = False, force_flac: bool = False) -> AudioFile:
            input = ensure_path_exists(input, self)
            parsed = ParsedFile.from_file(input, self)
            track = parsed.find_tracks(relative_id=self.track, type=TrackType.AUDIO, caller=self, error_if_empty=True)[0]
            form = track.get_audio_format()
            if not self._no_print:
                info(f"Extracting audio track {self.track} from '{parsed.source.stem}'...", self)
            if not form:
                lossy = False
                extension = "wav"
                danger("Unrecognized format: {track.format}\nWill extract as wav instead.", self, 2)
                out = make_output(input, extension, f"extracted_{self.track}", self.output, temp=is_temp)
            else:
                lossy = form.is_lossy
                extension = form.extension
                out = make_output(input, form.extension, f"extracted_{self.track}", self.output, temp=is_temp)

            args = [self.executable, "-hide_banner", "-i", str(input.resolve()), "-map_chapters", "-1", "-map", f"0:a:{self.track}"]

            specified_depth = track.bit_depth or 16
            could_truncate = (
                not self.skip_analysis
                and not lossy
                and form
                and not form.should_not_transcode()
                and bool(actual_depth := self._analyse_bitdepth(input, specified_depth, quiet))
                and specified_depth > actual_depth
            )
            will_truncate = False

            if could_truncate:
                if specified_depth > actual_depth:
                    debug(f"Detected fake/padded {specified_depth} bit. Actual depth is {actual_depth} bit.", self)
                if actual_depth <= 16:
                    debug("Track will be converted to flac and truncated to 16 bit instead.", self)
                    out = make_output(input, "flac", f"extracted_{self.track}", self.output, temp=is_temp)
                    args.extend(["-c:a", "flac", "-sample_fmt", "s16", "-compression_level", "0"])
                    will_truncate = True

            if not will_truncate:
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
                return AudioFile(out, getattr(track, "delay_relative_to_video", 0) if self.preserve_delay else 0, input, None, duration)
            else:
                raise error("Failed to extract audio track using ffmpeg", self)

        def _analyse_bitdepth(self, file_in: PathLike, specified_depth: int, quiet: bool) -> int:
            flac = get_executable("flac", can_error=False)
            if not flac:
                warn("No FLAC executable found. Please disable analysis explicitly or make sure you have FLAC in your path.", self)
                return 0
            debug("Analysing audio track with libFLAC...", self)
            version = get_binary_version(flac, r"flac .+? version (\d\.\d+\.\d+)")
            temp_out = make_output(file_in, "flac", "analysis", temp=True)
            args_ffmpeg = [
                self.executable,
                "-hide_banner",
                "-i",
                str(file_in),
                "-map",
                f"0:a:{self.track}",
                "-f",
                "w64",
                "-c:a",
                "pcm_s16le" if specified_depth <= 16 else "pcm_s24le",
                "-",
            ]
            ffmpeg_process = subprocess.Popen(
                args_ffmpeg, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL if quiet else None, text=False
            )
            args_flac = [flac, "-0", "-o", str(temp_out), "-"]
            if not version or re.search(r"1\.[2|3|4]\.\d+?", version):
                warn("Using outdated FLAC encoder that does not support threading!", self)
            else:
                args_flac.append(f"--threads={min(os.cpu_count() or 1, 8)}")

            flac_returncode = run_commandline(args_flac, quiet, stdin=ffmpeg_process.stdout)
            if flac_returncode:
                danger("Failed to encode temp file via flac for analysis!", self)
                clean_temp_files()
                return 0
            returncode, stdout = communicate_stdout([flac, "-sac", str(temp_out)])
            if returncode:
                danger("Failed to analyse the temporary flac file!", self)
                clean_temp_files()
                return 0

            total = 0
            n = 0
            for line in stdout.splitlines():
                if "wasted_bits" not in line:
                    continue
                idx = line.index("wasted_bits") + len("wasted_bits") + 1
                try:
                    wasted_bits = int("".join(takewhile(str.isdigit, line[idx : idx + 3])))
                    total += specified_depth - wasted_bits
                    n += 1
                except:
                    debug(line, self)

            average_bits = 0
            if n > 0:
                average_bits = ((total * 10 // n) + 5) // 10
            else:
                danger("Audio analysis resulted in no valid bit depth entries!", self)

            clean_temp_files()
            return average_bits

    @dataclass
    class Trimmer(Trimmer):
        """
        Trims audio files using FFMPEG.
        If you're working with lossless files it is strongly recommended to use SoX instead.

        :param trim:                Can be a single trim or a sequence of trims.
        :param preserve_delay:      Will preserve existing container delay
        :param trim_use_ms:         Will use milliseconds instead of frame numbers
        :param timesource:          The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                    For details check the docstring on the type.
        :param num_frames:          Total number of frames used for calculations
        :param output:              Custom output. Can be a dir or a file.
                                    Do not specify an extension unless you know what you're doing.
        """

        trim: Trim | list[Trim] | None = None
        preserve_delay: bool = False
        trim_use_ms: bool = False
        timesource: TimeSourceT = Fraction(24000, 1001)
        timescale: TimeScaleT = TimeScale.MKV
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
                    millis = self.resolved_ts.frame_to_time(trim[0], TimeType.EXACT, 3)
                    arg += f" -ss {format_timedelta(timedelta(milliseconds=millis))}"
            if trim[1] is not None and trim[1] != 0:
                end_frame = self.num_frames + trim[1] if trim[1] < 0 else trim[1]
                if self.trim_use_ms:
                    arg += f" -to {format_timedelta(timedelta(milliseconds=trim[1]))}"
                else:
                    millis = self.resolved_ts.frame_to_time(end_frame, TimeType.EXACT, 3)
                    arg += f" -to {format_timedelta(timedelta(milliseconds=millis))}"
            return arg

        def trim_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True) -> AudioFile:
            if not isinstance(fileIn, AudioFile):
                fileIn = AudioFile.from_file(fileIn, self)
            self.resolved_ts = resolve_timesource_and_scale(self.timesource, self.timescale, caller=self)
            self.trim = sanitize_trims(self.trim, self.num_frames, not self.trim_use_ms, caller=self)

            parsed = ParsedFile.from_file(fileIn.file, self)
            track = parsed.find_tracks(relative_id=0, type=TrackType.AUDIO, caller=self, error_if_empty=True)[0]
            form = track.get_audio_format()
            if not form:
                raise error(f"Unrecognized format: {track.codec_name}", self)

            lossy = form.is_lossy
            args = [get_executable("ffmpeg"), "-hide_banner", "-i", str(fileIn.file.resolve()), "-map", "0:a:0"]
            if form.should_not_transcode():
                args.extend(["-c:a", "copy"])
                extension = form.extension
            else:
                args.extend(["-c:a", "flac", "-compression_level", "0"])
                extension = "flac"

            out = make_output(fileIn.file, extension, "trimmed", self.output)
            ainfo = parse_audioinfo(fileIn.file, is_thd=True, caller=self)

            if len(self.trim) == 1:
                info(f"Trimming '{fileIn.file.stem}' with ffmpeg...", self)
                tr = self.trim[0]
                if lossy:
                    args[2:1] = splitcommand(self._targs(tr))
                else:
                    args.extend(splitcommand(self._targs(tr)))
                args.append(str(out.resolve()))
                if not run_commandline(args, quiet):
                    if tr[0] and lossy:
                        ms = tr[0] if self.trim_use_ms else self.resolved_ts.frame_to_time(tr[0], TimeType.EXACT, 3)
                        cont_delay = self._calc_delay(ms, ainfo.num_samples(), track.raw_ffprobe.sample_rate or 48000)
                        debug(f"Additional delay of {cont_delay} ms will be applied to fix remaining sync", self)
                        if self.preserve_delay:
                            cont_delay += fileIn.container_delay
                    else:
                        cont_delay = fileIn.container_delay if self.preserve_delay else 0

                    debug("Done", self)
                    return AudioFile(out, cont_delay, fileIn.source)
                else:
                    raise error("Failed to trim audio using FFMPEG!", self)
            else:
                info(f"Generating trimmed tracks for '{fileIn.file.stem}'...", self)
                concat: list = []
                first = True
                for i, tr in enumerate(self.trim):
                    nArgs = args.copy()
                    if lossy:
                        nArgs[2:1] = splitcommand(self._targs(tr))
                        if first:
                            if tr[0]:
                                ms = tr[0] if self.trim_use_ms else self.resolved_ts.frame_to_time(tr[0], TimeType.EXACT, 3)
                                cont_delay = self._calc_delay(ms, ainfo.num_samples(), track.raw_ffprobe.sample_rate or 48000)
                                debug(f"Additional delay of {cont_delay} ms will be applied to fix remaining sync", self)
                            first = False
                    else:
                        nArgs.extend(splitcommand(self._targs(tr)))
                        if first:
                            cont_delay = fileIn.container_delay if self.preserve_delay else 0
                            first = False
                    nout = os.path.join(get_temp_workdir(), f"{fileIn.file.stem}_part{i}.{extension}")
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
                    return AudioFile(out, cont_delay, fileIn.source)
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
            with open(concat_file, "w", encoding="utf-8") as fout:
                fout.writelines([f"file {_escape_name(str(af.file.resolve()))}\n" for af in audio_files])

            first_format = audio_files[0].get_trackinfo().get_audio_format()
            if not first_format:
                raise error(f"Concat cannot work with unknown formats! ({audio_files[0].get_trackinfo().codec_name})", self)

            format_mismatch = not all([af.get_trackinfo().get_audio_format() == first_format for af in audio_files[1:]])
            if format_mismatch or first_format.extension == "wav":
                out_codec = "flac"
                out_ext = "flac"
            else:
                out_codec = "copy"
                out_ext = first_format.extension

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
    :param timesource:          The source of timestamps/timecodes. For details check the docstring on the type.
    :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
    :param num_frames:          Total number of frames used for calculations
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    trim: Trim | list[Trim] | None = None
    preserve_delay: bool = False
    trim_use_ms: bool = False
    timesource: TimeSourceT = Fraction(24000, 1001)
    timescale: TimeScaleT = TimeScale.MKV
    num_frames: int = 0
    output: PathLike | None = None

    def _conv(self, val: int | None):
        if val is None:
            return None

        if self.trim_use_ms:
            return abs(val) / 1000
        else:
            return self.resolved_ts.frame_to_time(abs(val), TimeType.EXACT).__float__()

    def trim_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True) -> AudioFile:
        import sox  # type: ignore[import-untyped]

        if not isinstance(fileIn, AudioFile):
            fileIn = AudioFile.from_file(fileIn, self)
        out = make_output(fileIn.file, "flac", "trimmed", self.output)
        self.resolved_ts = resolve_timesource_and_scale(self.timesource, self.timescale, caller=self)
        trim = sanitize_trims(self.trim, self.num_frames, not self.trim_use_ms, allow_negative_start=True, caller=self)
        source = ensure_valid_in(fileIn, caller=self, supports_pipe=False)

        if len(trim) > 1:
            files_to_concat = []
            first = True
            info(f"Generating trimmed tracks for '{fileIn.file.stem}'...", self)
            for i, t in enumerate(trim):
                soxr = sox.Transformer()
                soxr.set_globals(multithread=True, verbosity=0 if quiet else 1)
                trim_start = t[0] or 0
                if trim_start < 0 and first:
                    soxr.trim(0, self._conv(t[1]))
                    soxr.pad(self._conv(trim_start))
                else:
                    soxr.trim(self._conv(trim_start), self._conv(t[1]))
                first = False
                tout = os.path.join(get_temp_workdir(), f"{fileIn.file.stem}_trimmed_part{i}.wav")
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
            info(f"Applying trim to '{fileIn.file.stem}'", self)
            t = trim[0]
            trim_start = t[0] or 0
            if trim_start < 0:
                soxr.trim(0, self._conv(t[1]))
                soxr.pad(self._conv(trim_start))
            else:
                soxr.trim(self._conv(trim_start), self._conv(t[1]))
            soxr.build(str(source.file), str(out.resolve()))
            debug("Done", self)

        clean_temp_files()
        return AudioFile(out.resolve(), fileIn.container_delay if self.preserve_delay else 0, fileIn.source)
