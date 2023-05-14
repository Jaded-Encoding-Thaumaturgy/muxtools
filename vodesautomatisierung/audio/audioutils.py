import subprocess
import os

from encoders import FF_FLAC
from utils.format import *
from utils.log import warn
from utils.files import AudioFile
from utils.types import DitherType
from utils.env import get_workdir


def ensure_valid_in(
    input: AudioFile,
    supports_pipe: bool = True,
    dither: bool = True,
    dither_type: DitherType = DitherType.TRIANGULAR,
    caller: any = None,
) -> AudioFile | subprocess.Popen:
    """
    Ensures valid input for any encoder that accepts flac (all of them).
    Passes existing file if no need to dither and is either wav or flac.
    """

    def getflac(input: AudioFile):
        if supports_pipe:
            return FF_FLAC(dither=dither, dither_type=dither_type).get_pipe(input)
        else:
            return FF_FLAC(compression_level=0, dither=dither, dither_type=dither_type, output=os.path.join(get_workdir(), "tempflac")).encode_audio(
                input, temp=True
            )

    if input.has_multiple_tracks(caller):
        msg = f"'{input.name}' is a container with multiple tracks.\n"
        msg += f"The first audio track will be {'piped' if supports_pipe else 'extracted'} using default ffmpeg."
        warn(msg, caller, 5)

    minfo = input.get_mediainfo()
    if is_fancy_codec(minfo):
        warn("Encoding tracks with special DTS Features or Atmos is very much discouraged.", caller, 10)
    form = minfo.format.lower()
    if "wav" in form or "flac" in form or "pcm" in form:
        if minfo.bit_depth > 16 and dither:
            return getflac(input)
        return input
    else:
        if input.is_lossy():
            warn(f"It's strongly recommended to not reencode lossy audio! ({minfo.format})", caller, 5)
        return getflac(input)
