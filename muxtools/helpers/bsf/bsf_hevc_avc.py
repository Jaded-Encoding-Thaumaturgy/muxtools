from typing import Any, Sequence
from pathlib import Path

from ...utils import ensure_path_exists, PathLike, error
from .bsf_generic import BSF_Matrix, BSF_Primaries, BSF_Transfer, BSF_Format, BSF_ChromaLocation, _apply_bsf

__all__ = ["apply_avc_bsf", "apply_hevc_bsf"]


def _resolve_crop(crop: int | Sequence[int]) -> list[str]:
    if isinstance(crop, int):
        crop = [crop] * 4
    elif len(crop) == 2:
        crop = list(crop) * 2
    return [f"crop_left={str(crop[0])}", f"crop_top={str(crop[1])}", f"crop_right={str(crop[2])}", f"crop_bottom={str(crop[3])}"]


def _apply_avc_hevc_bsf(
    fileIn: PathLike,
    filter_name: str,
    sar: int | None = None,
    cloc_type: BSF_ChromaLocation | int | None = None,
    full_range: bool | int | None = None,
    format: BSF_Format | int | None = None,
    primaries: BSF_Primaries | int | None = None,
    transfer: BSF_Transfer | int | None = None,
    matrix: BSF_Matrix | int | None = None,
    crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None,
    quiet: bool = True,
    caller: Any = None,
    **kwargs: bool | str,
) -> Path:
    f = ensure_path_exists(fileIn, caller)
    filter_options = list[str]()

    if sar is not None:
        filter_options.append(f"sample_aspect_ratio={str(sar)}")
    if full_range is not None:
        filter_options.append(f"video_full_range_flag={str(int(full_range))}")

    if cloc_type is not None:
        filter_options.append(f"chroma_sample_loc_type={str(BSF_ChromaLocation(cloc_type).value)}")
    if format is not None:
        filter_options.append(f"video_format={str(BSF_Format(format).value)}")
    if primaries is not None:
        filter_options.append(f"colour_primaries={str(BSF_Primaries(primaries).value)}")
    if transfer is not None:
        filter_options.append(f"transfer_characteristics={str(BSF_Transfer(transfer).value)}")
    if matrix is not None:
        filter_options.append(f"matrix_coefficients={str(BSF_Matrix(matrix).value)}")
    if crop is not None:
        filter_options.extend(_resolve_crop(crop))

    if kwargs:
        for key, value in kwargs.items():
            if isinstance(value, bool):
                filter_options.append(f"{key}={str(int(value))}")
            else:
                filter_options.append(f"{key}={str(value)}")

    if not filter_options:
        raise error("No changes to be made!", caller)

    return _apply_bsf(f, filter_name, filter_options, caller, quiet)


def apply_avc_bsf(
    fileIn: PathLike,
    sar: int | None = None,
    cloc_type: BSF_ChromaLocation | int | None = None,
    full_range: bool | int | None = None,
    format: BSF_Format | int | None = None,
    primaries: BSF_Primaries | int | None = None,
    transfer: BSF_Transfer | int | None = None,
    matrix: BSF_Matrix | int | None = None,
    crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None,
    quiet: bool = True,
    **kwargs: bool | str,
) -> Path:
    """
    A helper for the FFMpeg [h264_metadata](https://ffmpeg.org/ffmpeg-bitstream-filters.html#h264_005fmetadata) bitstream filter.

    `None` values will do nothing to the respective metadata flags.

    :param fileIn:                      The file to modify
    :param sar:                         Set the sample aspect ratio in the stream
    :param cloc_type:                   Set the chroma sample location in the stream
    :param full_range:                  Set the full range flag in the stream
    :param format:                      Set the video format in the stream
    :param primaries:                   Set the color primaries in the stream
    :param transfer:                    Set the transfer characteristics in the stream
    :param matrix:                      Set the matrix coefficients in the stream
    :param crop:                        Set the crop values in the stream
    :param quiet:                       Suppresses the output of ffmpeg
    :param kwargs:                      Additional options for the filter.\n
                                        For other available options, check the hyperlink to the filter above.
    :return:                            The output path which may be different if a CRC was detected and swapped.
    """

    return _apply_avc_hevc_bsf(
        fileIn,
        "h264_metadata",
        sar=sar,
        cloc_type=cloc_type,
        full_range=full_range,
        format=format,
        primaries=primaries,
        transfer=transfer,
        matrix=matrix,
        crop=crop,
        quiet=quiet,
        caller=apply_avc_bsf,
        **kwargs,
    )


def apply_hevc_bsf(
    fileIn: PathLike,
    sar: int | None = None,
    cloc_type: BSF_ChromaLocation | int | None = None,
    full_range: bool | int | None = None,
    format: BSF_Format | int | None = None,
    primaries: BSF_Primaries | int | None = None,
    transfer: BSF_Transfer | int | None = None,
    matrix: BSF_Matrix | int | None = None,
    crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None,
    quiet: bool = True,
    **kwargs: bool | str,
) -> Path:
    """
    A helper for the FFMpeg [hevc_metadata](https://ffmpeg.org/ffmpeg-bitstream-filters.html#hevc_005fmetadata) bitstream filter.

    `None` values will do nothing to the respective metadata flags.

    :param fileIn:                      The file to modify
    :param sar:                         Set the sample aspect ratio in the stream
    :param cloc_type:                   Set the chroma sample location in the stream
    :param full_range:                  Set the full range flag in the stream
    :param format:                      Set the video format in the stream
    :param primaries:                   Set the color primaries in the stream
    :param transfer:                    Set the transfer characteristics in the stream
    :param matrix:                      Set the matrix coefficients in the stream
    :param crop:                        Set the crop values in the stream
    :param quiet:                       Suppresses the output of ffmpeg
    :param kwargs:                      Additional options for the filter.\n
                                        For available options, check the hyperlink to the filter above.
    :return:                            The output path which may be different if a CRC was detected and swapped.
    """

    return _apply_avc_hevc_bsf(
        fileIn,
        "hevc_metadata",
        sar=sar,
        cloc_type=cloc_type,
        full_range=full_range,
        format=format,
        primaries=primaries,
        transfer=transfer,
        matrix=matrix,
        crop=crop,
        quiet=quiet,
        caller=apply_hevc_bsf,
        **kwargs,
    )
