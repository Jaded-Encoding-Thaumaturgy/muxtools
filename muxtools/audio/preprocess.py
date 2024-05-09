import os
import re
import subprocess
from typing import Any
from collections.abc import Sequence
from dataclasses import dataclass
from abc import ABC, abstractmethod
from pymediainfo import Track

from ..utils.log import error, debug
from ..utils.types import DitherType
from ..muxing.muxfiles import AudioFile
from ..utils.download import get_executable
from ..utils.files import ensure_path_exists

__all__ = ["Resample", "Loudnorm", "Downmix", "Pan", "CustomPreprocessor"]


class Preprocessor(ABC):
    refresh_metadata = False

    def get_filter(self, caller: Any = None) -> str | None:
        return None

    def get_args(self, caller: Any = None) -> Sequence[str]:
        return []

    def analyze(self, file: AudioFile):
        return None

    @abstractmethod
    def can_run(self, track: Track, preprocessors: Sequence[Any]) -> bool: ...


@dataclass
class Resample(Preprocessor):
    """
    A FFMPEG Resampling preprocessor.
    This is used to dither down to 16 bit and resample to 48kHz by default.
    Uses the sox resampler internally for best results.

    :param dither:          The dither algorithm to use. Uses SoX's default by default.
    :param depth:           The bitdepth to dither to. `None` will not change the depth.
                            You can technically only choose 16 or 32 as 24 is apparently just 32 with padding and needs specific codec support.
    :param sample_rate:     The sample rate to resample to. Defaults to 48kHz because most encoders support it.
    """

    dither: DitherType = DitherType.TRIANGULAR
    depth: int | None = 16
    sample_rate: int = 48000
    refresh_metadata = True

    def can_run(self, track: Track, preprocessors: Sequence[Any]) -> bool:
        # Run if depth or sample rate differ. Also run if loudnorm is being used.
        return (
            (self.depth and getattr(track, "bit_depth", 24) != self.depth)
            or getattr(track, "sampling_rate", 0) != self.sample_rate
            or [p for p in preprocessors if isinstance(p, Loudnorm)]
        )

    def get_args(self, caller: Any = None) -> Sequence[str]:
        if caller:
            debug(
                (
                    f"Resampling to {self.depth} bit and {self.sample_rate / 1000} kHz..."
                    if self.depth
                    else f"Resampling to {self.sample_rate / 1000} kHz..."
                ),
                caller,
            )
        return (
            []
            if not self.depth
            else ["-sample_fmt", f"s{self.depth}"]
            + [
                "-ar",
                str(self.sample_rate),
                "-resampler",
                "soxr",
                "-precision",
                "24",
                "-dither_method",
                self.dither.name.lower(),
            ]
        )


class classproperty(object):
    def __init__(self, f):
        self.f = classmethod(f)

    def __get__(self, *a):
        return self.f.__get__(*a)()


@dataclass
class Downmix(Preprocessor):
    """
    A FFMPEG downmixing/pan preprocessor.
    This essentially just uses the [pan](http://ffmpeg.org/ffmpeg-all.html#pan-1) filter and offers a few presets.

    If you're looking for explanations or other infos feel free to read these threads:
    https://superuser.com/questions/852400/properly-downmix-5-1-to-stereo-using-ffmpeg
    https://github.com/mpv-player/mpv/issues/6343

    :param mixing:      The Pan filter string. Defaults to the Dave_750 preset.
                        Honestly no recommendations here. Try them all and use what you prefer.
    :param force:       Force processing even if there are only 2 channels.
    """

    mixing: str | None = None
    force: bool = False
    refresh_metadata = True

    def can_run(self, track: Track, preprocessors: Sequence[Any]) -> bool:
        return getattr(track, "channel_s", 2) > 2 or self.force

    def get_filter(self, caller: Any = None) -> str:
        if not self.mixing:
            self.mixing = Downmix.Dave_750
        if caller:
            debug("Applying downmix/pan filter...", caller)
        return f"pan={self.mixing}"

    @classproperty
    def ATSC(self) -> str:
        return "stereo|FL<1.0*FL+0.707*FC+0.707*BL+0.707*SL|FR<1.0*FR+0.707*FC+0.707*BR+0.707*SR"

    @classproperty
    def Collier(self) -> str:
        return "stereo|FL=FC+0.30*FL+0.30*BL+0.30*SL|FR=FC+0.30*FR+0.30*BR+0.30*SR"

    @classproperty
    def Dave_750(self) -> str:
        return "stereo|FL=0.5*FC+0.707*FL+0.707*BL+0.707*SL+0.5*LFE|FR=0.5*FC+0.707*FR+0.707*BR+0.707*SR+0.35*LFE"

    @classproperty
    def RFC_7845(self) -> str:
        return "stereo|FL=0.374107*FC+0.529067*FL+0.458186*BL+0.458186*SL+0.264534*BR+0.264534*SR+0.374107*LFE|FR=0.374107*FC+0.529067*FR+0.458186*BR+0.458186*SR+0.264534*BL+0.264534*SL+0.374107*LFE"


Pan = Downmix


@dataclass
class Loudnorm(Preprocessor):
    """
    A FFMPEG normalization preprocessor according to EBU-R128 standards.
    It's strongly recommended to also put a `Resample` preprocessor into the chain as this filter needs to upsample to 192kHz and we don't want to encode that after.

    This will do a dynamic pass first to measure various values and then do the proper pass so it might take a while.

    :param i:           The integrated loudness target. Range is `-70.0` - `-5.0`. Default value is `-24.0`.
    :param lra:         The loudness range target. Range is `1.0` - `50.0`. Default value is `7.0`.
    :param tp:          The maximum true peak. Range is `-9.0` - `+0.0`. Default value is `-2.0`.
    :param offset:      Offset gain. Gain is applied before the true-peak limiter.
                        Will be taken from the analysis in the first pass if None.
    """

    i: float = -24.0
    lra: float = 7.0
    tp: float = -2.0
    offset: float | None = None

    @dataclass
    class Measurements:
        i: float
        lra: float
        tp: float
        thresh: float
        target_offset: float

    def can_run(self, track: Track, preprocessors: Sequence[Any]) -> bool:
        return True

    def analyze(self, file: AudioFile):
        debug("Analyzing file loudness...", self)
        ffmpeg = get_executable("ffmpeg")
        out_var = "NUL" if os.name == "nt" else "/dev/null"
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-i",
            str(ensure_path_exists(file.file, self).resolve()),
            "-map",
            "0:a:0",
            "-filter:a",
            "loudnorm=print_format=json",
            "-f",
            "null",
            out_var,
        ]
        out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        output = (out.stderr or "") + (out.stdout or "")
        output = output.replace("\n", "").replace("\r", "")
        i_match = re.findall(r"input_i.+?(-?\d+(?:\.\d+)?)", output, re.I)
        tp_match = re.findall(r"input_tp.+?(-?\d+(?:\.\d+)?)", output, re.I)
        lra_match = re.findall(r"input_lra.+?(-?\d+(?:\.\d+)?)", output, re.I)
        thresh_match = re.findall(r"input_thresh.+?(-?\d+(?:\.\d+)?)", output, re.I)
        offset_match = re.findall(r"target_offset.+?(-?\d+(?:\.\d+)?)", output, re.I)
        if not all([i_match, tp_match, lra_match, thresh_match, offset_match]):
            raise error("Could not properly measure the input file!", self)

        self.measurements = self.Measurements(
            float(i_match[0]),
            float(lra_match[0]),
            float(tp_match[0]),
            float(thresh_match[0]),
            float(offset_match[0]),
        )

    def get_filter(self, caller: Any = None) -> str | None:
        if caller:
            debug("Applying loudnorm...", caller)
        if not hasattr(self, "measurements"):
            # Ideally shouldn't run into this lmfao
            return ""
        return (
            f"loudnorm=linear=true:i={self.i}:lra={self.lra}:tp={self.tp}:offset={self.offset if self.offset else self.measurements.target_offset}"
            f":measured_I={self.measurements.i}:measured_tp={self.measurements.tp}:measured_LRA={self.measurements.lra}:measured_thresh={self.measurements.thresh}"
        )


@dataclass
class CustomPreprocessor(Preprocessor):
    """
    A custom preprocessor class to pass arbitrary filters or arguments to ffmpeg.

    :param filt:        Audio filter to append to the filterchain. Don't include any flags or whatever.
                        It should look like this `afade=t=in:ss=0:d=15`
    :param args:        Other args you may want to pass to ffmpeg.
    """

    filt: str | None = None
    args: str | Sequence[str] | None = None

    def can_run(self, track: Track, preprocessors: Sequence[Any]) -> bool:
        return True

    def get_filter(self, caller: Any = None) -> str | None:
        return self.filt

    def get_args(self, caller: Any = None) -> Sequence[str]:
        if isinstance(self.args, str) and not isinstance(self.args, Sequence):
            self.args = [self.args]
        return list(self.args) if self.args else []
