from enum import Enum
from pathlib import Path

from ...utils import ensure_path_exists, PathLike, error
from .bsf_generic import BSF_Matrix, BSF_Primaries, BSF_Transfer, BSF_Format, _apply_bsf

__all__ = [
    "MPEG2_DAR",
    "MPEG2_FPS",
    "apply_mpeg2_bsf",
]


class MPEG2_DAR(Enum):
    DAR_4_3 = "4/3"
    DAR_16_9 = "16/9"
    DAR_221_100 = "221/100"


class MPEG2_FPS(Enum):
    FPS_23_976 = "24000/1001"
    FPS_24 = "24"
    FPS_25 = "25"
    FPS_29_97 = "30000/1001"
    FPS_30 = "30"
    FPS_50 = "50"
    FPS_59_94 = "60000/1001"
    FPS_60 = "60"


def apply_mpeg2_bsf(
    fileIn: PathLike,
    dar: MPEG2_DAR | str | None = None,
    fps: MPEG2_FPS | str | None = None,
    format: BSF_Format | int | None = None,
    primaries: BSF_Primaries | int | None = None,
    transfer: BSF_Transfer | int | None = None,
    matrix: BSF_Matrix | int | None = None,
    quiet: bool = True,
) -> Path:
    """
    A helper for the FFMpeg [mpeg2_metadata](https://ffmpeg.org/ffmpeg-bitstream-filters.html#mpeg2_005fmetadata) bitstream filter.

    `None` values will do nothing to the respective metadata flags.

    :param fileIn:                      The file to modify
    :param dar:                         Set the display aspect ratio in the stream
    :param fps:                         Set the frame rate in the stream
    :param format:                      Set the video format in the stream
    :param primaries:                   Set the color primaries in the stream
    :param transfer:                    Set the transfer characteristics in the stream
    :param matrix:                      Set the matrix coefficients in the stream
    :param quiet:                       Suppresses the output of ffmpeg
    :return:                            The output path which may be different if a CRC was detected and swapped.
    """
    f = ensure_path_exists(fileIn, apply_mpeg2_bsf)
    filter_options = list[str]()

    if dar is not None:
        filter_options.append(f"display_aspect_ratio={str(dar.value) if isinstance(dar, MPEG2_DAR) else str(dar)}")

    if fps is not None:
        filter_options.append(f"frame_rate={str(fps.value) if isinstance(fps, MPEG2_FPS) else str(fps)}")

    if format is not None:
        filter_options.append(f"video_format={str(BSF_Format(format).value)}")

    if primaries is not None:
        primaries = BSF_Primaries(primaries)
        if primaries.value not in range(1, 8):
            raise error(f"'{primaries}' is not a valid primaries value for MPEG2 streams!")
        filter_options.append(f"colour_primaries={str(primaries.value)}")

    if transfer is not None:
        transfer = BSF_Transfer(transfer)
        if transfer.value not in range(1, 9):
            raise error(f"'{transfer}' is not a valid transfer value for MPEG2 streams!")
        filter_options.append(f"transfer_characteristics={str(transfer.value)}")

    if matrix is not None:
        matrix = BSF_Matrix(matrix)
        if matrix.value not in range(1, 8):
            raise error(f"'{matrix}' is not a valid matrix value for MPEG2 streams!")
        filter_options.append(f"matrix_coefficients={str(matrix.value)}")

    if not filter_options:
        raise error("No changes to be made!", apply_mpeg2_bsf)

    return _apply_bsf(f, "mpeg2_metadata", filter_options, apply_mpeg2_bsf, quiet)
