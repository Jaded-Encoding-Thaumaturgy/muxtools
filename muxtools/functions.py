from fractions import Fraction

from .utils.log import warn
from .muxing.muxfiles import AudioFile
from .audio.audioutils import is_fancy_codec
from .audio.encoders import Opus
from .utils.types import PathLike, Trim
from .audio.extractors import FFMpeg, Sox
from .utils.files import ensure_path, ensure_path_exists
from .audio.tools import AutoEncoder, AutoTrimmer, Encoder, Trimmer, Extractor


def do_audio(
    fileIn: PathLike,
    track: int = 0,
    trims: Trim | list[Trim] | None = None,
    fps: Fraction = Fraction(24000, 1001),
    num_frames: int = 0,
    extractor: Extractor = FFMpeg.Extractor(),
    trimmer: Trimmer | None = AutoTrimmer(),
    encoder: Encoder | None = AutoEncoder(),
    quiet: bool = True,
    output: PathLike | None = None,
) -> AudioFile:
    """
    One-liner to handle the whole audio processing

    :param fileIn:          Input file
    :param track:           Audio track number
    :param trims:           Frame ranges to trim and/or combine, e. g. (24, -24) or [(24, 500), (700, 900)]
    :param fps:             FPS Fraction used for the conversion to time
    :param num_frames:      Total number of frames, used for negative numbers in trims
    :param extractor:       Tool used to extract the audio
    :param trimmer:         Tool used to trim the audio
                            AutoTrimmer means it will choose ffmpeg for lossy and Sox for lossless

    :param encoder:         Tool used to encode the audio
                            AutoEncoder means it won't reencode lossy and choose opus otherwise

    :param quiet:           Whether or not the tool output should be visible
    :param output:          Custom output file or directory, extensions will be automatically added
    :return:                AudioFile Object containing file path, delays and source
    """
    audio = ensure_path_exists(fileIn, do_audio)
    if extractor:
        setattr(extractor, "track", track)
        if not trimmer and not encoder:
            setattr(extractor, "output", output)
        audio = extractor.extract_audio(audio, quiet)

    if not isinstance(audio, AudioFile):
        audio = AudioFile.from_file(audio, do_audio)

    lossy = audio.is_lossy()

    if isinstance(trimmer, AutoTrimmer) and trims:
        if lossy:
            trimmer = FFMpeg.Trimmer()
        else:
            trimmer = Sox()

    if isinstance(encoder, AutoEncoder):
        if lossy:
            encoder = None
        elif is_fancy_codec(audio.get_mediainfo()):
            encoder = None
            warn("Audio will not be reencoded due to having Atmos or special DTS features.", do_audio, 2)
        else:
            encoder = Opus()

    if trimmer and trims:
        setattr(trimmer, "trim", trims)
        setattr(trimmer, "fps", fps)
        setattr(trimmer, "num_frames", num_frames)
        if not extractor and not encoder:
            setattr(trimmer, "output", output)
        trimmed = trimmer.trim_audio(audio, quiet)
        ensure_path(audio.file, do_audio).unlink(missing_ok=True)
        audio = trimmed

    if encoder:
        setattr(encoder, "output", output)
        encoded = encoder.encode_audio(audio, quiet)
        ensure_path(audio.file, do_audio).unlink(missing_ok=True)
        audio = encoded

    return audio
