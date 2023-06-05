from shlex import split as splitcommand
from dataclasses import dataclass
import subprocess
import os

from .tools import Encoder, LosslessEncoder
from ..muxing.muxfiles import AudioFile
from ..utils.env import run_commandline
from ..utils.download import get_executable
from ..utils.log import warn, crit, debug, error
from ..utils.files import make_output, clean_temp_files
from ..utils.types import DitherType, ValidInputType, qAAC_MODE, PathLike
from .audioutils import ensure_valid_in, has_libFDK, qaac_compatcheck

__all__ = ["FLAC", "FLACCL", "FF_FLAC", "Opus", "qAAC", "FDK_AAC"]


@dataclass
class FLAC(LosslessEncoder):
    """
    Uses the reference libFLAC encoder to encode audio to flac.

    :param compression_level:   Any int value from 0 to 8 (Higher = better but slower)
    :param dither:              Dithers any input down to 16 bit 48 khz if True
    :param dither_type:         FFMPEG dither_method used for dithering
    :param append:              Any other args one might pass to the encoder
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    compression_level: int = 8
    dither: bool = True
    dither_type: DitherType = DitherType.TRIANGULAR
    append: str = ""
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        flaccl = get_executable("flac")
        output = make_output(input.file, "flac", "libflac", self.output)
        source = ensure_valid_in(
            input, dither=self.dither, dither_type=self.dither_type, caller=self, valid_type=ValidInputType.AIFF_OR_FLAC, supports_pipe=False
        )
        debug(f"Encoding '{input.file.stem}' to FLAC using libFLAC...", self)

        args = [flaccl, f"-{self.compression_level}", str(source.file.resolve()) if isinstance(source, AudioFile) else "-"]
        args.extend(["-o", str(output)])
        if self.append:
            args.extend(splitcommand(self.append))

        stdin = subprocess.DEVNULL if isinstance(source, AudioFile) else source.stdout

        if not run_commandline(args, quiet, False, stdin):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to FLAC using libFLAC failed!", self)


@dataclass
class FLACCL(LosslessEncoder):
    """
    Uses the CUETools FLACCL encoder to encode audio to flac.
    This one uses OpenCL or Cuda depending on your GPU and claims to have better compression than libFLAC.

    :param compression_level:   Any int value from 0 to 8 (Higher = better but slower)
    :param dither:              Dithers any input down to 16 bit 48 khz if True
    :param dither_type:         FFMPEG dither_method used for dithering
    :param append:              Any other args one might pass to the encoder
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    compression_level: int = 8
    dither: bool = True
    dither_type: DitherType = DitherType.TRIANGULAR
    append: str = ""
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        flaccl = get_executable("CUETools.FLACCL.cmd")
        output = make_output(input.file, "flac", "flaccl", self.output)
        source = ensure_valid_in(
            input, dither=self.dither, dither_type=self.dither_type, caller=self, valid_type=ValidInputType.FLAC, supports_pipe=False
        )
        debug(f"Encoding '{input.file.stem}' to FLAC using FLACCL...", self)

        args = [flaccl, f"-{self.compression_level}", str(source.file.resolve()) if isinstance(source, AudioFile) else "-"]
        args.extend(["-o", str(output)])
        if self.append:
            args.extend(splitcommand(self.append))

        stdin = subprocess.DEVNULL if isinstance(source, AudioFile) else source.stdout

        if not run_commandline(args, quiet, False, stdin):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to FLAC using FLACCL failed!", self)


@dataclass
class FF_FLAC(LosslessEncoder):
    """
    Uses the ffmpeg/libav FLAC encoder to encode audio to flac.

    :param compression_level:   Any int value from 0 to 12 (Higher = better but slower)
    :param dither:              Dithers any input down to 16 bit 48 khz if True
    :param dither_type:         FFMPEG dither_method used for dithering
    :param append:              Any other args one might pass to the encoder
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    compression_level: int = 10
    dither: bool = True
    dither_type: DitherType = DitherType.TRIANGULAR
    append: str = ""
    output: PathLike | None = None

    def _base_command(self, input: AudioFile, compression: int = 0) -> list[str]:
        # fmt: off
        args = [get_executable("ffmpeg"), "-hide_banner", "-i", str(input.file.resolve()), "-map", "0:a:0", "-c:a", "flac", "-compression_level", str(compression)]
        if self.dither:
            args.extend(['-sample_fmt', 's16', '-ar', '48000', '-resampler', 'soxr', '-precision', '24', '-dither_method', self.dither_type.name.lower()])
        if self.append:
            args.extend(splitcommand(self.append))
        return args
        # fmt: on

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        output = make_output(input.file, "flac", "ffmpeg", self.output)
        if "temp" in kwargs.keys():
            debug(f"Preparing audio for input to other encoder using ffmpeg...", self)
        else:
            debug(f"Encoding '{input.file.stem}' to FLAC using ffmpeg...", self)
        args = self._base_command(input, self.compression_level)
        args.append(str(output.resolve()))

        if not run_commandline(args, quiet):
            debug("Done", self)
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to flac using ffmpeg failed!", self)

    def get_pipe(self, input: AudioFile) -> subprocess.Popen:
        debug(f"Piping audio for input to other encoder using ffmpeg...", self)
        args = self._base_command(input, 0)
        args.extend(["-f", "flac", "-"])
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=False)
        return p


@dataclass
class Opus(Encoder):
    """
    Uses opusenc to encode audio to opus.

    :param bitrate:             Any int value representing kbps from 1 to 512
                                Automatically chooses 192 and 320 for stereo and surround respectively if None

    :param vbr:                 Uses VBR encoding if True
    :param dither:              Dithers any input down to 16 bit 48 khz if True, lets the encoder handle it if False
    :param dither_type:         FFMPEG dither_method used for dithering
    :param append:              Any other args one might pass to the encoder
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    bitrate: int | None = None
    vbr: bool = True
    dither: bool = False
    dither_type: DitherType = DitherType.TRIANGULAR
    append: str = ""
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile | PathLike, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)

        exe = get_executable("opusenc")
        if not self.bitrate:
            info = input.get_mediainfo()
            match (info.channel_s):
                case _ if info.channel_s == 2:
                    self.bitrate = 192
                case _ if info.channel_s > 6:
                    self.bitrate = 420
                case _:
                    self.bitrate = 320
            debug(f"Encoding '{input.file.stem}' to Opus ({self.bitrate} kbps) using opusenc...", self)
        else:
            debug(f"Encoding '{input.file.stem}' to Opus using opusenc...", self)

        output = make_output(input.file, "opus", "opusenc", self.output)
        source = ensure_valid_in(
            input, dither=self.dither, dither_type=self.dither_type, caller=self, valid_type=ValidInputType.FLAC, supports_pipe=True
        )

        args = [exe, "--vbr" if self.vbr else "--cvbr", "--bitrate", str(self.bitrate)]
        if self.append:
            args.extend(splitcommand(self.append))
        args.append(str(source.file.resolve()) if isinstance(source, AudioFile) else "-")
        args.append(str(output))

        stdin = subprocess.DEVNULL if isinstance(source, AudioFile) else source.stdout

        if not run_commandline(args, quiet, False, stdin):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to opus using opusenc failed!", self)


@dataclass
class qAAC(Encoder):
    """
    Uses qAAC to encode audio to AAC.

    :param q:                   Quality value ranging from 0 to 127 if using TVBR, otherwise bitrate in kbps
    :param mode:                Encoding mode, Defaults to TVBR
    :param dither:              Dithers any input down to 16 bit 48 khz if True, lets the encoder handle it if False
    :param dither_type:         FFMPEG dither_method used for dithering
    :param append:              Any other args one might pass to the encoder
                                Adds " --no-delay --no-optimize" by default to prevent desync with video
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    q: int = 127
    mode: qAAC_MODE | int = qAAC_MODE.TVBR
    dither: bool = False
    dither_type: DitherType = DitherType.TRIANGULAR
    append: str = ""
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        output = make_output(input.file, "aac", "qaac", self.output)
        source = ensure_valid_in(
            input, dither=self.dither, dither_type=self.dither_type, caller=self, valid_type=ValidInputType.AIFF_OR_FLAC, supports_pipe=False
        )
        qaac = get_executable("qaac")
        qaac_compatcheck()

        debug(f"Encoding '{input.file.stem}' to AAC using qAAC...", self)
        args = [qaac, "--no-delay", "--no-optimize", "--threading", f"--{self.mode.name.lower()}", str(self.q)]
        if self.append:
            args.extend(splitcommand(self.append))
        args.extend(["-o", str(output), str(source.file.resolve()) if isinstance(source, AudioFile) else "-"])

        stdin = subprocess.DEVNULL if isinstance(source, AudioFile) else source.stdout

        if not run_commandline(args, quiet, False, stdin):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to AAC using qAAC failed!", self)


@dataclass
class FDK_AAC(Encoder):
    """
    Uses the libFDK implementation in ffmpeg to encode audio to AAC.
    It's strongly recommended to use qAAC if you're on windows because its straight up the best AAC encoder.

    :param bitrate_mode:        Any int value from 0 - 5
                                0 will be CBR and using the bitrate below, 1 - 5 are true VBR modes
                                See https://wiki.hydrogenaud.io/index.php?title=Fraunhofer_FDK_AAC#Bitrate_Modes

    :param bitrate:             Any int value representing kbps
    :param dither:              Dithers any input down to 16 bit 48 khz if True, lets the encoder handle it if False
    :param dither_type:         FFMPEG dither_method used for dithering
    :param append:              Any other args one might pass to the encoder
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    bitrate_mode: int = 5
    bitrate: int = 256
    dither: bool = False
    dither_type: DitherType = DitherType.TRIANGULAR
    append: str = ""
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        output = make_output(input.file, "m4a", "fdkaac", self.output)
        if not has_libFDK():
            raise error(
                "Your installation of ffmpeg wasn't compiled with libFDK."
                + "\nYou can download builds with the non-free flag from https://github.com/AnimMouse/ffmpeg-autobuild/releases",
                self,
            )
        if os.name == "nt":
            warn("It is strongly recommended to use qAAC on windows. See docs.", self, 5)
        debug(f"Encoding '{input.file.stem}' to AAC using libFDK...", self)
        # fmt: off
        args = [get_executable("ffmpeg"), "-hide_banner", "-i", str(input.file.resolve()), "-map", "0:a:0", "-c:a", "libfdk_aac"]
        if self.bitrate_mode > 0:
            args.extend(['-vbr', str(self.bitrate_mode)])
        else:
            args.extend(['-b:a', f'{self.bitrate}k'])
        if self.dither:
            args.extend(['-sample_fmt', 's16', '-ar', '48000', '-resampler', 'soxr', '-precision', '24', '-dither_method', self.dither_type.name.lower()])
        if self.append:
            args.extend(splitcommand(self.append))
        args.append(str(output))
        # fmt: on
        if not run_commandline(args, quiet, False):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to AAC using libFDK failed!", self)


# TODO: Implement the dolby shit
