import os
import shutil
import logging
from pathlib import Path

from .sub import SubFile, FontFile
from ..utils.env import get_workdir
from ..utils.log import debug, warn


def _weight_to_name(weight: int) -> str:
    # https://learn.microsoft.com/en-us/typography/opentype/spec/os2#usweightclass
    match weight:
        case 100:
            return "Thin"
        case 200:
            return "ExtraLight"
        case 300:
            return "Light"
        case 500:
            return "Medium"
        case 600:
            return "SemiBold"
        case 700:
            return "Bold"
        case 800:
            return "ExtraBold"
        case 900:
            return "Black"
    return ""


def collect_fonts(sub: SubFile, use_system_fonts: bool = True, additional_fonts: list[Path] = [], collect_draw_fonts: bool = True) -> list[FontFile]:
    from font_collector import set_loglevel

    set_loglevel(logging.CRITICAL)

    from font_collector import AssDocument, FontLoader, Helpers, Font

    def _get_fontname(font: Font) -> str:
        filename_fallback = False
        exact_fallback = False
        try:
            try:
                name = font.family_names.pop().strip()
            except:
                name = font.exact_names.pop().strip()
                exact_fallback = True
        except:
            name = Path(font.filename).with_suffix("").name.strip()
            filename_fallback = True

        if not filename_fallback:
            if " " in name:
                name = "".join([part.capitalize() for part in name.split(" ")])
            elif "-" in name and exact_fallback:
                name = "".join([part.strip().capitalize() for part in name.split("-")])
            else:
                name = name.capitalize()
            weight = _weight_to_name(font.weight)
            name = f"{name}{'-' + weight if weight and weight not in name else ''}{'Italic' if font.italic else ''}"

        return name

    loaded_fonts = FontLoader(additional_fonts, use_system_font=use_system_fonts).fonts

    doc = AssDocument(sub._read_doc())
    styles = doc.get_used_style(collect_draw_fonts)

    found_fonts: list[FontFile] = []

    for style, _ in styles.items():
        query = Helpers.get_used_font_by_style(loaded_fonts, style)

        if not query:
            warn(f"Font '{style.fontname}' was not found!", collect_fonts, 3)
        else:
            fontname = _get_fontname(query.font)

            debug(f"Found font '{fontname}'.", collect_fonts)
            fontpath = Path(query.font.filename)
            outpath = os.path.join(get_workdir(), f"{fontname}{fontpath.suffix}")
            if not Path(outpath).exists():
                shutil.copy(fontpath, outpath)

    for f in get_workdir().glob("*.[tT][tT][fF]"):
        found_fonts.append(FontFile(f))
    for f in get_workdir().glob("*.[oO][tT][fF]"):
        found_fonts.append(FontFile(f))
    return found_fonts
