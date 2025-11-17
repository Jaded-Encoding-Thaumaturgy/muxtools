import os
import re
import shutil
import logging
from pathlib import Path
from font_collector import ABCFontFace, VariableFontFace
from fontTools.subset import Subsetter
from fontTools import ttLib
import time
import hashlib
import base64

from .sub import SubFile, FontFile as MTFontFile
from ..utils.convert import sizeof_fmt
from ..utils.env import get_workdir
from ..utils.log import warn, error, info, danger


__all__ = [
    "subset_fonts",
]

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


def _hash_font_name(font_name: str, run_time: str) -> str:
    font_name = font_name.replace(" ", "").strip()

    # Font names should be at most 31 characters long to work with GDI

    hash = base64.urlsafe_b64encode(
        hashlib.sha256(f"{font_name}_Subset_{run_time}".encode('utf-8')).digest()
    ).decode('utf-8').replace("=", "")

    # Maximise the hash we can use, whilst keeping the total length <= 31 and a decent size hash (6 chars at least)
    if len(font_name) > 24:
        return f"{font_name[:24]}_{hash[:6]}"
    else:
        return f"{font_name}_{hash[:(31 - len(font_name) - 1)]}"


def subset_fonts(
    subs: list[SubFile],
    aggressive: bool = False,
    ignore_fonts_with_no_usage: bool = True,
    additional_glyphs: list[str] = [],
    print_final_stats: bool = True,
) -> list[MTFontFile]:
    """
    Subset fonts previously collected with `collect_fonts`. This can greatly reduce the size of the final mux.
    The output of this function should be used instead of the output of `collect_fonts`.

    The default behavior is to include the used glyphs and a common set of unicode characters to ensure re-usability of the font for others editing your subtitles.

    :param subs:                        List of subtitle files to analyze for used glyphs.
    :param aggressive:                  If enabled, this will only include the characters used in the subtitles and all `additional_glyphs` specified.
                                        Note: This may harm the re-usability of the font for others editing your subtitles.
    :param ignore_fonts_with_no_usage:  If no glyphs are used, having this option `True` will skip subsetting for that font.
                                        Otherwise, it will subset using a common glyph set.
    :param additional_glyphs:           If you have any additional glyphs that need to be included in the subsetted fonts.
                                        You can use the format "U+XXXX" for unicode characters or "U+XXXX-YYYY" for unicode ranges.
                                        https://unicode-explorer.com/blocks can help you find the characters/ranges you need.
    :param print_final_stats:           If enabled, will print out statistics about space saved.

    :return:                            A list of FontFile objects
    """

    run_time = str(int(time.time())) # Use this to create unique hashes

    info("Subsetting fonts...", subset_fonts)

    from font_collector import set_loglevel

    set_loglevel(logging.CRITICAL)

    from font_collector import AssDocument, FontLoader, FontCollection, FontSelectionStrategyLibass, ABCFontFace

    from ass_tag_analyzer import parse_line, AssValidTagFontName

    font_collection = FontCollection(
        use_system_font=False,
        reload_system_font=False,
        use_generated_fonts=False,
        additional_fonts=FontLoader.load_additional_fonts([get_workdir()], scan_subdirs=False),
    )
    load_strategy = FontSelectionStrategyLibass()

    subset_additional_glyphs_parsed = _parse_unicode_chars(additional_glyphs)

    fonts: dict[ABCFontFace, dict] = {}
    # Font:
    # - usage: set()
    # - names: dict[str, str]  # old name -> new name

    for sub in subs:
        doc = AssDocument(sub._read_doc())
        styles = doc.get_used_style(collect_draw_fonts=True)

        for style, usage_data in styles.items():
            query = font_collection.get_used_font_by_style(style, load_strategy)

            if not query:
                danger(f"Font '{style.fontname}' was not found! Did you run collect_fonts?", subset_fonts)
            
            else:
                if fonts.get(query.font_face) is None:
                    fonts[query.font_face] = {
                        "usage": set(),
                        "names": {},
                    }
                
                fonts[query.font_face]["usage"].update(usage_data.characters_used)
                
                for name in query.font_face.exact_names + query.font_face.family_names + [style.fontname]:
                    value = name if isinstance(name, str) else name.value  

                    if fonts[query.font_face]["names"].get(value) is None:
                        fonts[query.font_face]["names"][value] = _hash_font_name(value, run_time)


    font_replacements: dict[str, str] = {}

    total_old_size = 0
    total_new_size = 0

    for font_face, data in fonts.items():
        assert font_face.font_file is not None, "Font file is missing!"

        # Old size is calculated before skipping subsetting if necessary
        old_size = os.path.getsize(font_face.font_file.filename)
        total_old_size += old_size

        font_name = _get_fontname(font_face)

        ttLib_font = ttLib.TTFont(font_face.font_file.filename)

        name_table = ttLib_font["name"]

        for record in name_table.names:
            if record.nameID == 1:  # Font Family name
                old_name = record.toUnicode().strip()
                if old_name in data["names"]:
                    record.string = data["names"][old_name]
                else:
                    raise Exception(f"Font family name '{old_name}' not found in names mapping for font '{font_name}'!")
            
            elif record.nameID == 4:  # Full name
                old_name = record.toUnicode().strip()
                if old_name in data["names"]:
                    record.string = data["names"][old_name]
                else:
                    raise Exception(f"Font full name '{old_name}' not found in names mapping for font '{font_name}'!")
            
            elif record.nameID == 6:  # PostScript name
                old_name = record.toUnicode().strip()
                if old_name in data["names"]:
                    record.string = data["names"][old_name]
                else:
                    raise Exception(f"Font PostScript name '{old_name}' not found in names mapping for font '{font_name}'!")
        
        characters = data["usage"].copy()
        characters.update(subset_additional_glyphs_parsed)

        if not aggressive:
            # We also want to add a general subset of common characters to avoid issues when reusing fonts, if we aren't doing aggressive subsetting
            characters.update(COMMON_UNICODE_CHARS)

        if not characters:
            if ignore_fonts_with_no_usage:
                warn(f"No characters used in font '{font_name}'. Skipping subsetting.", subset_fonts)
                continue
            else:
                warn(f"No characters used in font '{font_name}'. Defaulting to common subset.", subset_fonts)
                characters.update(COMMON_UNICODE_CHARS)
        
        subsetter = Subsetter()
        subsetter.populate(text="".join(characters))
        subsetter.subset(ttLib_font)

        new_font_path = font_face.font_file.filename.with_stem(f"{font_face.font_file.filename.stem}_subset")
        ttLib_font.save(new_font_path)
        ttLib_font.close()

        new_size = os.path.getsize(new_font_path)
        total_new_size += new_size

        try:
            os.remove(font_face.font_file.filename)
        except FileNotFoundError:
            pass # If the file is already missing, we can ignore this, bit weird though
        except PermissionError:
            error(f"Could not remove original font file '{font_face.font_file.filename}' due to permission error. Is it open in another program?", subset_fonts)
        
        for old_name, new_name in data["names"].items():
            font_replacements[old_name] = new_name

        info(f"Subsetted font '{font_name}' ({len(characters)} glyphs, {sizeof_fmt(old_size)} -> {sizeof_fmt(new_size)})", collect_fonts)
    

    if font_replacements:

        for sub in subs:
            doc = sub._read_doc()

            modified = False

            for event in doc.events:
                line_data = parse_line(event.text)
                for data in line_data:
                    if isinstance(data, AssValidTagFontName):
                        safe_font_name = re.escape(data.name)

                        if data.name in font_replacements:
                            event.text = re.sub(
                                R'(\\fn.*)(' + safe_font_name + R')(.*)',
                                lambda m: m.group(1) + font_replacements[data.name] + m.group(3),
                                event.text
                            )
                            modified = True
            
            for style in doc.styles:
                if style.fontname in font_replacements:  
                    style.fontname = font_replacements[style.fontname]
                    modified = True
            
            if modified:
                sub._update_doc(doc)

            info(f"Updated font names in subfile '{sub.file.name}'", subset_fonts)
    
    if print_final_stats and total_old_size > 0:
        info(f'Subsetting has saved {(total_old_size - total_new_size) / total_old_size * 100:.2f}% ({sizeof_fmt(total_old_size)} -> {sizeof_fmt(total_new_size)})')
    
    found_fonts = list[MTFontFile]()
    for r in ["*.[tT][tT][fF]", "*.[oO][tT][fF]", "*.[tT][tT][cC]", "*.[oO][tT][cC]"]:
        for f in get_workdir().glob(r):
            found_fonts.append(MTFontFile(f))

    return found_fonts


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

    for r in ["*.[tT][tT][fF]", "*.[oO][tT][fF]", "*.[tT][tT][cC]", "*.[oO][tT][cC]"]:
        for f in get_workdir().glob(r):
            found_fonts.append(MTFontFile(f))
    return found_fonts
