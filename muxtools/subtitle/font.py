import os
import re
import shutil
import logging
from pathlib import Path
from font_collector import ABCFontFace, VariableFontFace
from fontTools.subset import Subsetter
from fontTools import ttLib

from .sub import SubFile, FontFile as MTFontFile
from ..utils.convert import sizeof_fmt
from ..utils.env import get_workdir
from ..utils.log import warn, error, info, danger, log_escape


# A selection of common unicode characters to always include when subsetting fonts
# Follows the format: 'U+XXXX'
# For ranges, use 'U+XXXX-YYYY'
UNFORMATTED_COMMON_UNICODE_CHARS = [
    'U+0000-00FF',  # Basic Latin + Latin-1 Supplement
    'U+0100-024F',  # Latin Extended-A + Latin Extended-B
    'U+1E00-1EFF',  # Latin Extended Additional
    'U+2000-206F',  # General Punctuation
    'U+20A0-20CF',  # Currency Symbols
]

def _parse_unicode_chars(char_list: list[str]) -> list[str]:
    """Parse unicode character definitions including ranges."""
    result = []
    for item in char_list:
        if item.startswith('U+'):
            if '-' in item:
                # Handle range
                parts = item.replace('U+', '').split('-')
                start = int(parts[0], 16)
                end = int(parts[1], 16)
                result.extend([chr(i) for i in range(start, end + 1)])
            else:
                # Single character
                result.append(chr(int(item.replace('U+', ''), 16)))
        else:
            if len(item) == 1:
                result.append(item)
            else:
                warn(f"Invalid unicode character format: {item}", _parse_unicode_chars)

    return result

COMMON_UNICODE_CHARS = _parse_unicode_chars(UNFORMATTED_COMMON_UNICODE_CHARS)

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
        # Not quite sure why this is nullable
        if not font.font_file:
            raise error(f"Could not find font file for '{font.get_best_exact_name()}'!")
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
    subset_fonts: bool = False,
    subset_aggressive: bool = False,
    subset_ignore_fonts_with_no_usage: bool = True,
    subset_additional_glyphs: list[str] = [],
    subset_additional_subfiles: list[SubFile] = [],
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

    subset_additional_glyphs_parsed = _parse_unicode_chars(subset_additional_glyphs)
    subset_all_subfiles = [sub] + subset_additional_subfiles

    found_fonts = list[MTFontFile]()
    collected_faces = set[ABCFontFace]()

    fonts_to_be_replaced: dict[str, str] = {}

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
            assert query.font_face.font_file
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
            
            if subset_fonts:
                # We always want to include the used characters, and any additional glyphs specified by the user
                characters_set = usage_data.characters_used
                characters_set.update(subset_additional_glyphs_parsed)

                if not subset_aggressive:
                    # We also want to add a general subset of common characters to avoid issues when reusing fonts, if we aren't doing aggressive subsetting
                    characters_set.update(COMMON_UNICODE_CHARS)

                if not subset_ignore_fonts_with_no_usage and not characters_set:
                    # If theres no characters used, and we aren't ignoring fonts with no usage, add common characters
                    warn(f"No characters used in font '{fontname}'. Defaulting to common subset.", collect_fonts)
                    characters_set.update(COMMON_UNICODE_CHARS)

                if not characters_set:
                    warn(f"No characters used in font '{fontname}'. Skipping subsetting...", collect_fonts)
                
                else:
                    new_path = outpath.with_name(f"{outpath.stem}_subset{outpath.suffix}")

                    old_font_family_name = ''
                    new_font_family_name = ''
                    old_font_name = ''
                    new_font_name = ''

                    try:
                        font = ttLib.TTFont(outpath)

                        subsetter = Subsetter()
                        subsetter.populate(text="".join(characters_set))
                        subsetter.subset(font)

                        name_table = font["name"]

                        for record in name_table.names:
                            # Font names can only be 31 characters long

                            if record.nameID == 1:  # Font Family name
                                old_font_family_name = record.toUnicode().strip()
                                new_font_family_name = record.toUnicode().replace(' ', '')[:25] + "Subset"
                                record.string = new_font_family_name
                            elif record.nameID == 4:  # Full name
                                old_font_name = record.toUnicode().strip()
                                new_font_name = record.toUnicode().replace(' ', '')[:25] + "Subset"
                                record.string = new_font_name
                            elif record.nameID == 6:  # PostScript name
                                record.string = record.toUnicode().replace(' ', '')[:25] + "Subset"
                        
                        if not old_font_name or not new_font_name:
                            raise Exception("Could not find necessary name records for subsetting.")
                        
                        font.save(new_path)
                        font.close()
                    
                    except Exception as e:
                        danger(f"Failed to subset font '{fontname}' (possibly corrupt/invalid font): {log_escape(str(e))}", collect_fonts)
                    
                    else:
                        # It's important that the family name and font name are both replaced.
                        # Usually, the family name is used in styles, but sometimes the full font name is used.
                        
                        # Insertion order is important as well, to avoid partial replacements.
                        # For example:
                        # - old_family_name = "Arial"
                        # - old_font_name = "Arial Bold"
                        # If we replaced "Arial" first, then "Arial Bold":
                        # - \fnArial Bold -> \fnArialSubset Bold
                        # which would not match the new name.
                        # We need to replace the one which is longer first.
                        
                        if len(old_font_name) > len(old_font_family_name):
                            fonts_to_be_replaced[old_font_name] = new_font_name
                            fonts_to_be_replaced[old_font_family_name] = new_font_family_name
                        else:
                            fonts_to_be_replaced[old_font_family_name] = new_font_family_name
                            fonts_to_be_replaced[old_font_name] = new_font_name

                        old_size = os.path.getsize(outpath)
                        new_size = os.path.getsize(new_path)
                        
                        info(f"Subsetted font '{fontname}' ({len(characters_set)} glyphs, {sizeof_fmt(old_size)} -> {sizeof_fmt(new_size)})", collect_fonts)

                        outpath = new_path

            
            found_fonts.append(MTFontFile(outpath))
    
    # Update additional subfiles with new font names
    # We do this at the end to avoid multiple reads/writes
    if fonts_to_be_replaced:
        for sub_obj in subset_all_subfiles:
            doc = sub_obj._read_doc()

            for event in doc.events:
                for old_font_name, new_font_name in fonts_to_be_replaced.items():
                    event.text = event.text.replace('\\fn' + old_font_name, '\\fn' + new_font_name)
            
            for style in doc.styles:
                for old_font_name, new_font_name in fonts_to_be_replaced.items():
                    if style.fontname == old_font_name:
                        style.fontname = new_font_name
                
            sub_obj._update_doc(doc)

            info(f"Updated font names in subfile '{sub_obj.file.name}'", collect_fonts)

    #for r in ["*.[tT][tT][fF]", "*.[oO][tT][fF]", "*.[tT][tT][cC]", "*.[oO][tT][cC]"]:
    #    for f in get_workdir().glob(r):
    #        found_fonts.append(MTFontFile(f))

    return found_fonts
