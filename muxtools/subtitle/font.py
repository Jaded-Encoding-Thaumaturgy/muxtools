import re
import shutil
import logging
from pathlib import Path
from font_collector import ABCFontFace, VariableFontFace

from .sub import SubFile, FontFile as MTFontFile
from ..utils.env import get_workdir
from ..utils.log import warn, error, info, danger


def _weight_to_name(weight: int) -> str | int:
    # https://learn.microsoft.com/en-us/typography/opentype/spec/os2#usweightclass
    match weight:
        case 100:
            return "Thin"
        case 200:
            return "ExtraLight"
        case 300:
            return "Light"
        case 400:
            return ""
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
    return weight


def _get_fontname(font: ABCFontFace) -> str:
    filename_fallback = False
    try:
        found = font.get_family_name_from_lang("en")
        if not found:
            found = font.get_best_family_name()
        name = found.value
    except:
        name = Path(font.font_file.filename).with_suffix("").name.strip()
        filename_fallback = True

    name = name.replace("/", " ").replace("\\", " ")

    if not filename_fallback:
        if " " in name:
            name = "".join([(part.capitalize() if part.islower() else part) for part in name.split(" ")])
        else:
            name = name.capitalize()
        if isinstance(font, VariableFontFace):
            name += "-VariableCollection"
            if font.is_italic:
                name += "Italic"
        else:
            weight = _weight_to_name(font.weight)
            if weight:
                name += f"-{weight}"
            if font.is_italic:
                name += ("" if weight else "-") + "Italic"

    return name


def collect_fonts(
    sub: SubFile,
    use_system_fonts: bool = True,
    additional_fonts: list[Path] = [],
    collect_draw_fonts: bool = True,
    error_missing: bool = False,
    use_ntfs_compliant_names: bool = False,
) -> list[MTFontFile]:
    def clean_name(fontname: str) -> str:
        removed_slash = fontname.replace("/", "_")
        if not use_ntfs_compliant_names:
            return removed_slash
        return re.sub(r"[\<\>\*\\\:\|\?\"]", "_", removed_slash)

    from font_collector import set_loglevel

    set_loglevel(logging.CRITICAL)

    from font_collector import AssDocument, FontLoader, FontCollection, FontSelectionStrategyLibass, ABCFontFace

    font_collection = FontCollection(
        use_system_fonts, additional_fonts=FontLoader.load_additional_fonts(additional_fonts, scan_subdirs=True) if additional_fonts else []
    )
    load_strategy = FontSelectionStrategyLibass()

    doc = AssDocument(sub._read_doc())
    styles = doc.get_used_style(collect_draw_fonts)

    found_fonts = list[MTFontFile]()
    collected_faces = set[ABCFontFace]()

    for style, usage_data in styles.items():
        query = font_collection.get_used_font_by_style(style, load_strategy)

        if not query:
            msg = f"Font '{style.fontname}' was not found!"
            if error_missing:
                raise error(msg, collect_fonts)
            else:
                danger(msg, collect_fonts, 3)
        else:
            fontname = _get_fontname(query.font_face)
            fontpath = Path(query.font_face.font_file.filename)
            outpath = get_workdir() / f"{clean_name(fontname)}{fontpath.suffix}"
            family_name = query.font_face.get_best_family_name().value

            if isinstance(query.font_face, VariableFontFace):
                outpath = outpath.with_suffix(".ttc")

                if not outpath.exists():
                    info(f"Converting '{family_name}' variable font to a collection.")
                    query.font_face.variable_font_to_collection(outpath)
            else:
                if query.font_face in collected_faces:
                    continue

            if query.font_face not in collected_faces:
                info(f"Found font '{fontname}'.", collect_fonts)
                collected_faces.add(query.font_face)

            if query.need_faux_bold:
                warn(f"Faux bold used for '{fontname}' (requested weight {style.weight}, got {query.font_face.weight})!", collect_fonts, 2)
            elif query.mismatch_bold:
                warn(f"Mismatched weight for '{fontname}' (requested weight {style.weight}, got {query.font_face.weight})!", collect_fonts, 2)

            if query.mismatch_italic:
                warn(f"Could not find a requested {'non-' if query.font_face.is_italic else ''}italic variant for '{fontname}'!", collect_fonts, 2)

            missing_glyphs = query.font_face.get_missing_glyphs(usage_data.characters_used)
            if len(missing_glyphs) != 0:
                danger(f"'{fontname}' is missing the following glyphs: {missing_glyphs}", collect_fonts, 3)

            if not outpath.exists():
                shutil.copy(fontpath, outpath)

    for r in ["*.[tT][tT][fF]", "*.[oO][tT][fF]", "*.[tT][tT][cC]", "*.[oO][tT][cC]"]:
        for f in get_workdir().glob(r):
            found_fonts.append(MTFontFile(f))
    return found_fonts
