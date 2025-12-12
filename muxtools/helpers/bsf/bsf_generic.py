from enum import IntEnum
from pathlib import Path
from typing import Any
from shutil import move

from ..helper_util import replace_crc
from ...utils import make_output, get_executable, run_commandline, clean_temp_files, error

__all__ = ["BSF_Matrix", "BSF_Transfer", "BSF_Primaries", "BSF_Format", "BSF_ChromaLocation"]


class BSF_ChromaLocation(IntEnum):
    """
    Collection of known chroma sample location values.

    For more documentation on these, check out the [H265 Specification](https://www.itu.int/rec/t-rec-h.265) (Figure E.1) or [JET Documentation](https://jaded-encoding-thaumaturgy.github.io/vs-jetpack/api/vstools/enums/generic/#vstools.enums.generic.ChromaLocation).
    """

    LEFT = 0
    CENTER = 1
    TOP_LEFT = 2
    TOP = 3
    BOTTOM_LEFT = 4
    BOTTOM = 5


class BSF_Matrix(IntEnum):
    """
    Collection of known bitstream matrix values.

    For more documentation on these, check out the [H265 Specification](https://www.itu.int/rec/t-rec-h.265) (Table E.5) or [JET Documentation](https://jaded-encoding-thaumaturgy.github.io/vs-jetpack/api/vstools/enums/color/#vstools.enums.color.Matrix).
    """

    RGB = 0
    GBR = RGB
    IDENTITY = RGB
    BT709 = 1
    UNKNOWN = 2
    FCC = 3
    BT470BG = 5
    BT601_625 = BT470BG
    SMPTE170M = 6
    BT601_525 = SMPTE170M
    SMPTE240M = 7
    YCGCO = 8
    BT2020NCL = 9
    BT2020CL = 10
    CHROMANCL = 12
    CHROMACL = 13
    ICTCP = 14


class BSF_Transfer(IntEnum):
    """
    Collection of known bitstream transfer values.

    For more documentation on these, check out the [H265 Specification](https://www.itu.int/rec/t-rec-h.265) (Table E.4) or [JET Documentation](https://jaded-encoding-thaumaturgy.github.io/vs-jetpack/api/vstools/enums/color/#vstools.enums.color.Transfer).
    """

    BT709 = 1
    BT1886 = BT709
    UNKNOWN = 2
    BT470M = 4
    BT470BG = 5
    SMPTE170M = 6
    BT601 = SMPTE170M
    SMPTE240M = 7
    LINEAR = 8
    LOG100 = 9
    LOG316 = 10
    XVYCC = 11
    SRGB = 13
    BT2020_10 = 14
    BT2020_12 = 15
    ST2084 = 16
    PQ = ST2084
    STD_B67 = 18
    HLG = STD_B67


class BSF_Primaries(IntEnum):
    """
    Collection of known bitstream color primaries values.

    For more documentation on these, check out the [H265 Specification](https://www.itu.int/rec/t-rec-h.265) (Table E.3) or [JET Documentation](https://jaded-encoding-thaumaturgy.github.io/vs-jetpack/api/vstools/enums/color/#vstools.enums.color.Primaries).
    """

    BT709 = 1
    UNKNOWN = 2
    BT470M = 4
    BT470BG = 5
    BT601_625 = BT470BG
    SMPTE170M = 6
    BT601_525 = SMPTE170M
    SMPTE240M = 7
    FILM = 8
    BT2020 = 9
    ST428 = 10
    XYZ = ST428
    CIE1931 = ST428
    ST431_2 = 11
    DCI_P3 = ST431_2
    ST432_1 = 12
    DISPLAY_P3 = ST432_1
    JEDEC_P22 = 22
    EBU3213 = JEDEC_P22


class BSF_Format(IntEnum):
    """
    Collection of known bitstream video_format values.

    For more documentation on these, check out the [H265 Specification](https://www.itu.int/rec/t-rec-h.265) (Table E.2)
    """

    COMPONENT = 0
    PAL = 1
    NTSC = 2
    SECAM = 3
    MAC = 4
    UNSPECIFIED = 5


def _apply_bsf(
    fileIn: Path,
    filter_name: str,
    filter_options: list[str],
    caller: Any,
    quiet: bool = True,
) -> Path:
    out = make_output(fileIn, fileIn.suffix[1:], "bsf", temp=True)
    ffmpeg = get_executable("ffmpeg")

    options = ":".join(filter_options)
    args = [ffmpeg, "-hide_banner", "-i", str(fileIn), "-map", "0", "-c", "copy", "-bsf:v", f"{filter_name}={options}", str(out)]

    result = run_commandline(args, quiet)
    if bool(result):
        clean_temp_files()
        raise error(f"Failed to apply {filter_name.split('_')[0]} bitstream filter!", caller)

    fileIn.unlink()
    move(out, fileIn)
    clean_temp_files()
    return replace_crc(fileIn, caller)
