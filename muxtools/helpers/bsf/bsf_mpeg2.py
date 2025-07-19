from enum import Enum
from shutil import move

from ...utils import ensure_path_exists, PathLike, error, get_executable, run_commandline, make_output, clean_temp_files
from .generic_enums import BSF_Matrix, BSF_Primaries, BSF_Transfer, BSF_Format

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
):
    """
    A helper for the FFMpeg [mpeg2_metadata](https://ffmpeg.org/ffmpeg-bitstream-filters.html#mpeg2_005fmetadata) bitstream filter.

    `None` values will do nothing to the respective metadata flags.

    :param fileIn:                      The file to modify
    :param dar:                         Set the display aspect ratio in the stream
    :param fps:                         Set the frame rate in the stream
    :param format:                      Set the video format in the stream
    :param primaries:                   Set the color primaries in the stream
    :param transfer_characteristics:    Set the transfer characteristics in the stream
    :param matrix_coefficients:         Set the matrix coefficients in the stream
    :param quiet:                       Suppresses the output of ffmpeg
    """
    f = ensure_path_exists(fileIn, apply_mpeg2_bsf)
    out = make_output(f, f.suffix[1:], "bsf", temp=True)
    ffmpeg = get_executable("ffmpeg")
    filter_options = list[str]()

    if dar is not None:
        filter_options.append(f"display_aspect_ratio={str(dar.value) if isinstance(dar, MPEG2_DAR) else str(dar)}")

    if fps is not None:
        filter_options.append(f"frame_rate={str(fps.value) if isinstance(fps, MPEG2_FPS) else str(fps)}")

    if format is not None and (format := BSF_Format(format)):
        filter_options.append(f"video_format={str(format.value)}")

    if primaries is not None and (primaries := BSF_Primaries(primaries)):
        if primaries.value not in range(1, 8):
            raise error(f"'{primaries}' is not a valid primaries value for MPEG2 streams!")
        filter_options.append(f"colour_primaries={str(primaries.value)}")

    if transfer is not None and (transfer := BSF_Transfer(transfer)):
        if transfer.value not in range(1, 9):
            raise error(f"'{transfer}' is not a valid transfer value for MPEG2 streams!")
        filter_options.append(f"transfer_characteristics={str(transfer.value)}")

    if matrix is not None and (matrix := BSF_Matrix(matrix)):
        if matrix.value not in range(1, 8):
            raise error(f"'{matrix}' is not a valid matrix value for MPEG2 streams!")
        filter_options.append(f"matrix_coefficients={str(matrix.value)}")

    if not filter_options:
        raise error("No changes to be made!", apply_mpeg2_bsf)

    filter_options = ":".join(filter_options)
    args = [ffmpeg, "-hide_banner", "-i", str(f), "-map", "0", "-c", "copy", "-bsf:v", f"mpeg2_metadata={filter_options}", str(out)]

    result = run_commandline(args, quiet)
    if bool(result):
        clean_temp_files()
        raise error("Failed to apply mpeg2 bitstream filter!", apply_mpeg2_bsf)

    f.unlink()
    move(out, f)
    clean_temp_files()
