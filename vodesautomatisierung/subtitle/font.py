import logging
import os
import shutil

from ..utils.env import get_workdir

logging.getLogger("matplotlib").setLevel(logging.CRITICAL)
logging.getLogger("matplotlib.font_manager").setLevel(logging.CRITICAL)

import matplotlib

matplotlib.use("agg", force=True)

from pathlib import Path


from ..utils.log import debug, warn
from .sub import SubFile, FontFile


def collect_fonts(sub: SubFile, use_system_fonts: bool = True, additional_fonts: list[Path] = []) -> list[FontFile]:
    from font_collector import set_loglevel

    set_loglevel(logging.CRITICAL)

    from font_collector import AssDocument, FontLoader, Helpers

    loaded_fonts = FontLoader(additional_fonts, use_system_font=use_system_fonts).fonts

    doc = AssDocument(sub._read_doc())
    styles = doc.get_used_style()

    found_fonts: list[FontFile] = []

    for style, _ in styles.items():
        query = Helpers.get_used_font_by_style(loaded_fonts, style)

        if not query:
            warn(f"Font '{style.fontname}' was not found!", collect_fonts, 3)
        else:
            fontname = query.font.exact_names.pop()
            debug(f"Found font '{fontname}'.", collect_fonts)
            fontpath = Path(query.font.filename)
            outpath = os.path.join(get_workdir(), f"{fontname}{fontpath.suffix}")
            if not Path(outpath).exists():
                shutil.copy(fontpath, outpath)

    for f in get_workdir().glob("*.ttf"):
        found_fonts.append(FontFile(f))
    for f in get_workdir().glob("*.otf"):
        found_fonts.append(FontFile(f))
    return found_fonts
