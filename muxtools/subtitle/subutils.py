import os
from pathlib import Path
from ass import Document

from ..utils.log import error
from ..utils.env import run_commandline
from ..utils.download import get_executable

__all__ = ["dummy_video"]


def create_document() -> Document:
    """
    Convenience function to create a new ASS Document.
    With relevant fields already filled in.
    """
    doc = Document()
    doc.play_res_x = 1920
    doc.play_res_y = 1080
    doc.wrap_style = 0
    doc.scaled_border_and_shadow = "yes"
    doc.script_type = "v4.00+"
    return doc


def has_arch_resampler() -> bool:
    aegicli = Path(get_executable("aegisub-cli", False))
    sourcedir = Path(aegicli.parent, "automation")
    check = [sourcedir]

    if os.name == "nt":
        check.append(Path(os.getenv("APPDATA"), "Aegisub", "automation"))
    else:
        check.append(Path(Path.home(), ".aegisub", "automation"))

    for d in check:
        for f in d.rglob("*"):
            if f.name.lower() == "arch.resample.moon":
                return True

    return False


def dummy_video(width: int = 1920, height: int = 1080, format: str = "yuv420p", quiet: bool = True) -> Path:
    """
    Creates a black dummy video using ffmpeg.

    :param width:           Width of the video
    :param height:          Height of the video
    :param format:          Format of the video
                            Do `ffmpeg -pix_fmts` to see what's available
    :param quiet:           Enable or disable commandline output

    :return:                Path object of the resulting video
    """
    from ..utils.files import make_output

    ffmpeg = get_executable("ffmpeg")
    out = make_output("dummy_video.mp4", "mp4", temp=True)
    args = [ffmpeg, "-t", "1", "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}", "-c:v", "libx264", "-pix_fmt", format, str(out)]
    if run_commandline(args, quiet):
        raise error("Failed to create dummy video with ffmpeg!", dummy_video)
    return out
