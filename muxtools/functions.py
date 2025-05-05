from fractions import Fraction
from datetime import timedelta

from .utils.log import warn, error, info, danger
from .utils.types import TimeScaleT, TimeScale, TimeSourceT
from .muxing.muxfiles import AudioFile
from .audio.audioutils import is_fancy_codec
from .audio.encoders import Opus, qAAC, FDK_AAC
from .utils.types import PathLike, Trim
from .audio.extractors import FFMpeg, Sox
from .utils.files import ensure_path, ensure_path_exists
from .audio.tools import AutoEncoder, AutoTrimmer, Encoder, Trimmer, Extractor
from .utils.convert import format_timedelta
from .utils.download import get_executable

__all__ = ["do_audio"]


def do_audio(
    fileIn: PathLike | list[PathLike],
    track: int = 0,
    trims: Trim | list[Trim] | None = None,
    timesource: TimeSourceT = Fraction(24000, 1001),
    timescale: TimeScaleT = TimeScale.MKV,
    num_frames: int = 0,
    extractor: Extractor | None = FFMpeg.Extractor(),
    trimmer: Trimmer | None = AutoTrimmer(),
    encoder: Encoder | None = AutoEncoder(),
    quiet: bool = True,
    output: PathLike | None = None,
) -> AudioFile:
    """
    One-liner to handle the whole audio processing

    :param fileIn:          Input file
    :param track:           Audio track number
    :param trims:           Frame ranges to trim and/or combine, e.g. (24, -24) or [(24, 500), (700, 900)]
    :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
    :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                            For details check the docstring on the type.
    :param num_frames:      Total number of frames, used for negative numbers in trims
    :param extractor:       Tool used to extract the audio
    :param trimmer:         Tool used to trim the audio
                            AutoTrimmer means it will choose ffmpeg for lossy and Sox for lossless

    :param encoder:         Tool used to encode the audio
                            AutoEncoder means it won't reencode lossy and choose opus (for 2.0) or qAAC/FDKAAC (for >2.0) otherwise

    :param quiet:           Whether the tool output should be visible
    :param output:          Custom output file or directory, extensions will be automatically added
    :return:                AudioFile Object containing file path, delays and source
    """
    if isinstance(fileIn, list) and (not extractor or not isinstance(extractor, FFMpeg.Extractor)):
        raise error("When passing a list of files you have to use the FFMpeg extractor!", do_audio)

    if extractor:
        setattr(extractor, "track", track)
        if not trimmer and not encoder:
            setattr(extractor, "output", output)
        if isinstance(fileIn, list):
            info(f"Extracting audio from {len(fileIn)} files to concatenate...", do_audio)
            extractor._no_print = True
            fileIn = [ensure_path_exists(f, do_audio) for f in fileIn]
            extracted = []
            for f in fileIn:
                try:
                    af = extractor.extract_audio(f, quiet, True, True)
                except:
                    setattr(extractor, "track", 0)
                    af = extractor.extract_audio(f, quiet, True, True)
                    setattr(extractor, "track", track)
                    duration = af.duration or timedelta(milliseconds=0)
                    if duration > timedelta(seconds=2):
                        danger(f"Could not find valid track {track} in '{f.name}' and falling back resulted in suspiciously long file.", do_audio, 1)
                        continue

                    duration = format_timedelta(duration)
                    warn(f"Fell back to track 0 for '{f.name}' with a duration of {duration}", do_audio, 1)

                extracted.append(af)
            audio = FFMpeg.Concat(extracted).concat_audio()
        else:
            audio = extractor.extract_audio(fileIn, quiet)
    else:
        audio = ensure_path_exists(fileIn, do_audio)

    if not isinstance(audio, AudioFile):
        audio = AudioFile.from_file(audio, do_audio)

    lossy = audio.is_lossy()

    if isinstance(trimmer, AutoTrimmer) and trims:
        if lossy:
            trimmer = FFMpeg.Trimmer()
        else:
            trimmer = Sox()

    mediainfo = audio.get_mediainfo()

    if isinstance(encoder, AutoEncoder):
        if lossy:
            encoder = None
        elif is_fancy_codec(mediainfo):
            encoder = None
            warn("Audio will not be reencoded due to having Atmos or special DTS features.", do_audio, 2)
        else:
            channels = getattr(mediainfo, "channel_s", None) or 2
            if channels <= 2:
                encoder = Opus()
            else:
                has_qaac = bool(get_executable("qaac", False, False))
                if has_qaac:
                    encoder = qAAC(100, lowpass=20000)
                else:
                    warn("Attempting to fall back to FDK_AAC because of a lack of qAAC in current PATH.", do_audio, 1)
                    encoder = FDK_AAC()

    if trimmer and trims:
        setattr(trimmer, "trim", trims)
        setattr(trimmer, "timesource", timesource)
        setattr(trimmer, "timescale", timescale)
        setattr(trimmer, "num_frames", num_frames)
        if not encoder:
            setattr(trimmer, "output", output)
        trimmed = trimmer.trim_audio(audio, quiet)
        ensure_path(audio.file, do_audio).unlink(missing_ok=True)
        audio = trimmed

    if encoder:
        setattr(encoder, "output", output)
        encoded = encoder.encode_audio(audio, quiet)
        ensure_path(audio.file, do_audio).unlink(missing_ok=True)
        audio = encoded

    print("")
    return audio
