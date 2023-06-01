"""
This contains a few either amusing or mostly useless codecs/encoders.

Thought they might be cool to have atleast.
"""

from dataclasses import dataclass
from .encoders import FLAC
from .tools import Encoder, LosslessEncoder
from ..utils.log import crit, debug, error
from ..muxing.muxfiles import AudioFile
from ..utils.env import run_commandline
from ..utils.download import get_executable
from ..utils.types import DitherType, LossyWavQuality, PathLike
from ..utils.files import clean_temp_files, make_output
from .audioutils import ensure_valid_in, qaac_compatcheck

__all__ = ["qALAC", "TTA", "TrueAudio", "TheTrueAudio", "LossyWav"]


@dataclass
class qALAC(Encoder):
    """
    Uses qAAC encoder to encode audio to ALAC.
    This is basically just worse FLAC and the only real use is good Apple hardware support.

    :param dither:              Dithers any input down to 16 bit 48 khz if True
    :param dither_type:         FFMPEG dither_method used for dithering
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    dither: bool = True
    dither_type: DitherType = DitherType.TRIANGULAR
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        output = make_output(input.file, "alac", "qaac", self.output)
        source = ensure_valid_in(input, dither=self.dither, dither_type=self.dither_type, caller=self, supports_pipe=False)
        qaac = get_executable("qaac")
        qaac_compatcheck()

        debug(f"Encoding '{input.file.stem}' to ALAC using qAAC...", self)
        args = [qaac, "-A", "--no-delay", "--no-optimize", "--threading", "-o", str(output), str(source.file)]
        if not run_commandline(args, quiet):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to ALAC using qAAC failed!", self)


@dataclass
class TTA(LosslessEncoder):
    """
    Uses ffmpeg to encode audio to TTA/The True Audio.
    (I could not get the reference encoder to work with any ffmpeg wav or any flac)
    This doesn't really seem to have any benefit over FLAC except for maybe encode speed?
    Definitely has a cool name tho.


    :param dither:              Dithers any input down to 16 bit 48 khz if True
    :param dither_type:         FFMPEG dither_method used for dithering
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    dither: bool = True
    dither_type: DitherType = DitherType.TRIANGULAR
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        output = make_output(input.file, "tta", "encoded", self.output)

        args = [get_executable("ffmpeg"), "-hide_banner", "-i", str(input.file.resolve()), "-map", "0:a:0", "-c:a", "tta"]
        if self.dither:
            args.extend(
                ["-sample_fmt", "s16", "-ar", "48000", "-resampler", "soxr", "-precision", "24", "-dither_method", self.dither_type.name.lower()]
            )

        debug(f"Encoding '{input.file.stem}' to TTA using ffmpeg...", self)
        if not run_commandline(args, quiet):
            debug("Done", self)
            clean_temp_files()
            return AudioFile(output, input.container_delay, input.source)
        else:
            raise crit("Encoding to TTA using ffmpeg failed!", self)


TrueAudio = TTA
TheTrueAudio = TTA


@dataclass
class LossyWav(Encoder):
    """
    :param quality:             Lossywav Quality Preset
    :param target_encoder:      Whatever encoder the lossy wav file will be fed to. (lossless encoders only)
                                Only properly supports libFLAC and wavpack (will be added later) out of what we have.

    :param override_options:    Automatically sets the appropriate options for each encoder to work as intended.
    :param dither:              Dithers any input down to 16 bit 48 khz if True
    :param dither_type:         FFMPEG dither_method used for dithering
    :param output:              Custom output. Can be a dir or a file.
                                Do not specify an extension unless you know what you're doing.
    """

    quality: LossyWavQuality = LossyWavQuality.INSANE
    target_encoder: LosslessEncoder | None = None
    override_options: bool = True
    dither: bool = True
    dither_type: DitherType = DitherType.TRIANGULAR
    output: PathLike | None = None

    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        if not self.target_encoder:
            self.target_encoder = FLAC()
        if not self.target_encoder.lossless:
            raise error("Target Encoder can only be a lossless one.", self)
        if not isinstance(input, AudioFile):
            input = AudioFile.from_file(input, self)
        output = make_output(input.file, "wav", "encoded", self.output, True)
        specified_depth = getattr(input.get_mediainfo(), "bit_depth", 16)
        codec = "pcm_s16le" if specified_depth == 16 or self.dither else "pcm_s24le"
        args = [get_executable("ffmpeg"), "-hide_banner", "-i", str(input.file.resolve()), "-map", "0:a:0", "-c:a", codec]
        if self.dither:
            args.extend(
                ["-sample_fmt", "s16", "-ar", "48000", "-resampler", "soxr", "-precision", "24", "-dither_method", self.dither_type.name.lower()]
            )
        args.append(str(output))

        debug(f"Encoding '{input.file.stem}' to PCM WAV using ffmpeg...", self)
        if run_commandline(args, quiet):
            raise crit("Encoding to WAV using ffmpeg failed!", self)

        args = [get_executable("lossyWAV", False), str(output), "--quality", self.quality.name.lower(), "-o", str(output.parent.resolve())]
        debug(f"Doing lossywav magic...", self)
        if run_commandline(args, quiet):
            raise crit("LossyWAV conversion failed!", self)

        lossy = output.with_stem(output.stem + ".lossy")
        setattr(self.target_encoder, "dither", False)
        if self.override_options:
            if isinstance(self.target_encoder, FLAC):
                setattr(self.target_encoder, "compression_level", 5)
                setattr(self.target_encoder, "append", "-b 512")

        encoded = self.target_encoder.encode_audio(AudioFile(lossy, input.container_delay, input.source), quiet)
        clean_temp_files()
        return encoded
