from __future__ import annotations
from ass import Document, Comment, Dialogue, Style, parse as parseDoc  # type: ignore[import-untyped]
from collections.abc import Callable
from typing import Any, cast, Sequence
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from video_timestamps import TimeType
from typing_extensions import Self
import shutil
import json
import re
import os

from .styles import GJM_GANDHI_PRESET, resize_preset
from .subutils import create_document, dummy_video, has_arch_resampler
from ..utils.glob import GlobSearch
from ..utils.download import get_executable
from ..utils.types import PathLike, TrackType, TimeSourceT, TimeScaleT, TimeScale
from ..utils.log import debug, error, info, warn, log_escape
from ..utils.convert import resolve_timesource_and_scale
from ..utils.env import get_temp_workdir, get_workdir, run_commandline
from ..utils.files import ensure_path_exists, make_output, clean_temp_files, uniquify_path, ensure_path
from ..utils.probe import ParsedFile
from ..muxing.muxfiles import MuxingFile
from ..muxing.tracks import Attachment
from .basesub import BaseSubFile, _Line, ASSHeader, ShiftMode, OutOfBoundsMode

__all__ = ["FontFile", "SubFile", "DEFAULT_DIALOGUE_STYLES"]

DEFAULT_DIALOGUE_STYLES = ["default", "main", "alt", "overlap", "flashback", "top", "italics"]
SRT_REGEX = r"\d+[\r\n](?:(?P<start>\d+:\d+:\d+,\d+) --> (?P<end>\d+:\d+:\d+,\d+))[\r\n](?P<text>(?:.+\r?\n)+(?=(\r?\n)?))"
LINES = list[_Line]

CCC_REPLACEMENTS = dict(
    TopLeft=R"\an7", TopRight=R"\an9", CenterLeft=R"\an4", CenterCenter=R"\an5", CenterRight=R"\an6", BottomLeft=R"\an1", BottomRight=R"\an3"
)

CCC_REPLACEMENTS_REDUCED_MARGINS = dict(
    TopLeft=(R"\an7", 25, 25),
    TopRight=(R"\an9", 25, 25),
    CenterLeft=(R"\an4", 25, 25),
    CenterCenter=(R"\an5", 25, 25),
    CenterRight=(R"\an6", 25, 25),
    BottomLeft=(R"\an1", 25, 25),
    BottomRight=(R"\an3", 25, 25),
)


class FontFile(MuxingFile):
    def to_track(self, *args) -> Attachment:
        return Attachment(self.file)


class SubFile(BaseSubFile):
    """
    Utility class representing an ASS/SSA subtitle file with various functions to run on.

    :param file:            Can be a string, Path object or GlobSearch.
                            If the GlobSearch returns multiple results or if a list was passed it will merge them.

    :param container_delay: Set a container delay used in the muxing process later.
    :param source:          The file this sub originates from, will be set by the constructor.
    :param encoding:        Encoding used for reading and writing the subtitle files.
    """

    def __init__(
        self,
        file: PathLike | Sequence[PathLike] | GlobSearch,
        container_delay: int = 0,
        source: PathLike | None = None,
        tags: dict[str, str] | None = None,
        encoding: str = "utf_8_sig",
    ):
        if isinstance(file, GlobSearch):
            file = file.paths

        if isinstance(file, list) and len(file) > 1:
            debug("Merging sub files...", self)
            docs: list[Document] = []
            for i, f in enumerate(file):
                f = ensure_path_exists(f, self)
                with open(f, "r", encoding=self.encoding) as read:
                    doc = parseDoc(read)
                    docs.append(doc)
                    if i != 0:
                        self._warn_mismatched_properties(docs[0], doc, ensure_path(file[0], self).name, f.name)

            main = docs[0]
            existing_styles = [style.name for style in (main.styles)]
            docs.remove(main)

            for doc in docs:
                main.events.extend(doc.events)
                for style in doc.styles:
                    if style.name.casefold() in [s.casefold() for s in existing_styles]:
                        warn(f"Ignoring style '{style.name}' due to preexisting style of the same name.", self)
                        continue
                    main.styles.append(style)

            source = file[0]
            out = make_output(file[0], "ass", "merged")
            with open(out, "w", encoding=self.encoding) as writer:
                main.dump_file(writer)

            file = out
            debug("Done")
        else:
            file = ensure_path_exists(file, self)
            source = file
            if not os.path.samefile(file.parent, get_workdir()):
                out = make_output(file, "ass", "vof")
                with open(out, "w", encoding=self.encoding) as writer:
                    self._read_doc(file).dump_file(writer)
                file = out

        super().__init__(file, container_delay, source, tags, encoding)

    def manipulate_lines(self, func: Callable[[LINES], LINES | None]) -> Self:
        """
        Function to manipulate any lines.

        :param func:        Your own function you want to run on the list of lines.
                            This can return a new list or just edit the one passed into it.
        """
        super()._manipulate_lines(func)
        return self

    def set_header(self, header: str | ASSHeader, value: str | int | bool | None) -> Self:
        """
        A function to add headers to the "Script Info" section of the subtitle file.
        This will validate the input for known functional headers but also allows arbitrary ones.
        If you're planning on setting multiple at the same time, use the `set_headers` function instead to avoid a lot of I/O.

        :param header:      The name of the header or a header chosen from the enum.
        :param value:       The value of the header. None will remove the header unless it's the Matrix header because None has a meaning there.
        """
        super()._set_header(header, value)
        return self

    def set_headers(self, *headers: tuple[str | ASSHeader, str | int | bool | None]) -> Self:
        """
        A function to add headers to the "Script Info" section of the subtitle file.
        This will validate the input for known functional headers but also allows arbitrary ones.

        :param headers:     Any amount of tuples with the same typing as the single header function.
        """
        doc = self._read_doc()
        for header, value in headers:
            super()._set_header(header, value, doc)
        self._update_doc(doc)
        return self

    def clean_styles(self) -> Self:
        """
        Deletes unused styles from the document.
        """
        doc = self._read_doc()
        used_styles = {line.style for line in doc.events if line.TYPE == "Dialogue"}
        regex = re.compile(r"\{[^}]*\\r([^\\}]+)[^}]*\}")
        for line in [line for line in doc.events if line.TYPE == "Dialogue"]:
            for match in regex.finditer(line.text):
                used_styles.add(match.group(1))
        doc.styles = [style for style in doc.styles if style.name in used_styles]
        self._update_doc(doc)
        return self

    def clean_garbage(self) -> Self:
        """
        Removes the "Aegisub Project Garbage" section from the file.
        """
        doc = self._read_doc()
        doc.sections.pop("Aegisub Project Garbage", None)
        self._update_doc(doc)
        return self

    def clean_extradata(self) -> Self:
        """
        Removes the "Aegisub Extradata" section from the file.
        """
        doc = self._read_doc()
        doc.sections.pop("Aegisub Extradata", None)
        self._update_doc(doc)
        return self

    def clean_comments(self) -> Self:
        """
        Removes all comment lines from the file.
        """
        return self.manipulate_lines(lambda lines: list(filter(lambda line: str(line.TYPE).lower() != "comment", lines)))

    def autoswapper(
        self,
        allowed_styles: list[str] | None = DEFAULT_DIALOGUE_STYLES,
        print_swaps: bool = False,
        inline_marker: str = "*",
        line_marker: str = "***",
        inline_tag_markers: str | None = None,
    ) -> Self:
        r"""
        autoswapper allows replacing text in the script with a different text.
        Useful for creating honorific tracks.

        Assuming the markers are as default:

        - `{*}abc{*def}` becomes `{*}def{*abc}` (AB Swap)
        - `abc{**def}` becomes `abc{*}def{*}` (Show Word)
        - `abc{*}def{*}` becomes `abc{**def}` (Hide Word)

        Note: AB Swap and Hide Word will remove `{}` from the swapped text, to ensure the comment isn't broken.

        You can also comment in or out entire lines by using the line marker in either the `effect` or `name` field.
        - A dialogue line with effect or name set to `***` will be commented.
        - A comment line with effect or name set to `***` will be set to a dialogue.


        `inline_tag_markers` can be used to swap ASS tags as well. Keep in mind that "\" and "/" will be swapped, so override tags aren't applied.

        Assuming the markers are as default, except inline_tag_markers = `[]`:
        - `{*}{\i1}abc{*[/b1]def}` becomes `{*}{\b1}def{*[/i1]abc}` (AB Swap)
        - `abc{**[/b1]def}` becomes `abc{*}{\b1}def{*}` (Show Word)
        - `abc{*}{\b1}def{*}` becomes `abc{**[/b1]def}` (Hide Word)


        :param allowed_styles:          List of allowed styles to do the swapping on (case insensitive)
                                        Will run on every line if passed `None`
        :param print_swaps:             Prints the swaps
        :param inline_marker:           Marker to use for inline swaps.
                                        Should be one character. Default `*`
        :param line_marker:             Marker to use for full-line swaps. Default `***`
        :param inline_tag_markers:      Two characters that will be replaced with `{}` respectively in the inline swaps.
                                        Defaults to `None`, which will just remove the `{}` from the swapped text.

        :return:                        This SubTrack
        """
        if not isinstance(inline_marker, str) or not inline_marker.strip():
            warn("Given invalid inline marker. Using default '*'.", self)
            inline_marker = "*"

        if not isinstance(line_marker, str) or not line_marker.strip():
            warn("Given invalid line marker. Using default '***'.", self)
            line_marker = "***"

        if inline_tag_markers:
            if len(inline_tag_markers) != 2 or inline_tag_markers[0] == inline_tag_markers[1] or any([m in "{}" for m in inline_tag_markers]):
                warn("Given invalid inline comment markers. Using default 'None'.", self)
                inline_tag_markers = None

        marker = re.escape(inline_marker)

        ab_swap_regex = re.compile(rf"{{{marker}}}(.*?){{{marker}([^}}]+)}}")
        show_word_regex = re.compile(rf"{{{marker}{marker}([^}}]+)}}")
        hide_word_regex = re.compile(rf"{{{marker}}}(.*?){{{marker} *}}")

        backslash = "\\"  # This is to ensure support for previous python versions that don't allow backslashes in f-strings.

        def _do_autoswap(lines: LINES):
            for i, line in enumerate(lines):
                if not allowed_styles or str(line.style).casefold() in {style.casefold() for style in allowed_styles}:
                    to_swap: dict = {}
                    # {*}This will be replaced{*With this}
                    for match in re.finditer(ab_swap_regex, line.text):
                        if inline_tag_markers:
                            to_swap.update(
                                {
                                    f"{match.group(0)}": f"{{{inline_marker}}}{match.group(2).replace(inline_tag_markers[0], '{').replace(inline_tag_markers[1], '}').replace('/', backslash)}{{{inline_marker}{match.group(1).replace('{', inline_tag_markers[0]).replace('}', inline_tag_markers[1]).replace(backslash, '/')}}}"
                                }
                            )
                        else:
                            to_swap.update(
                                {
                                    f"{match.group(0)}": f"{{{inline_marker}}}{match.group(2)}{{{inline_marker}{match.group(1).replace('{', '').replace('}', '')}}}"
                                }
                            )

                    # This sentence is no longer{** incomplete}
                    for match in re.finditer(show_word_regex, line.text):
                        if inline_tag_markers:
                            to_swap.update(
                                {
                                    f"{match.group(0)}": f"{{{inline_marker}}}{match.group(1).replace(inline_tag_markers[0], '{').replace(inline_tag_markers[1], '}').replace('/', backslash)}{{{inline_marker}}}"
                                }
                            )
                        else:
                            to_swap.update({f"{match.group(0)}": f"{{{inline_marker}}}{match.group(1)}{{{inline_marker}}}"})

                    # This sentence is no longer{*} complete{*}
                    for match in re.finditer(hide_word_regex, line.text):
                        if inline_tag_markers:
                            to_swap.update(
                                {
                                    f"{match.group(0)}": f"{{{inline_marker * 2}{match.group(1).replace('{', inline_tag_markers[0]).replace('}', inline_tag_markers[1]).replace(backslash, '/')}}}"
                                }
                            )
                        else:
                            to_swap.update({f"{match.group(0)}": f"{{{inline_marker * 2}{match.group(1).replace('{', '').replace('}', '')}}}"})

                    for key, val in to_swap.items():
                        if print_swaps:
                            info(f'autoswapper: Swapped "{log_escape(key)}" for "{log_escape(val)}" on line {i}', self)
                        line.text = line.text.replace(key, val)

                    if line.effect.strip() == line_marker or line.name.strip() == line_marker:
                        if isinstance(line, Comment):
                            line.TYPE = "Dialogue"
                            if print_swaps:
                                info(f'autoswapper: Uncommented Line {i} - "{log_escape(line.text)}"', self)
                        elif isinstance(line, Dialogue):
                            line.TYPE = "Comment"
                            if print_swaps:
                                info(f'autoswapper: Commented Line {i} - "{log_escape(line.text)}"', self)

        self.manipulate_lines(_do_autoswap)
        return self

    def unfuck_cr(
        self,
        default_style: str = "Default",
        keep_flashback: bool = True,
        dialogue_styles: list[str] | None = ["main", "default", "narrator", "narration", "bottomcenter"],
        top_styles: list[str] | None = ["top"],
        italics_styles: list[str] | None = ["italics", "internal"],
        alt_style: str = "Alt",
        alt_styles: list[str] | None = None,
        exact_names: bool = False,
        custom_replacements: dict[str, str] | dict[str, tuple[str, int, int]] = CCC_REPLACEMENTS_REDUCED_MARGINS,
    ) -> Self:
        """
        Removes any top/positional and italics styles and replaces them with tags.

        Style names are case-insensitive and use substring matching.
        i.e. if `top_styles=["top"]`, `"MainTop"` or `"main_top"` would both be considered top styles.

        :param default_style:       The default style that everything will be set to
        :param keep_flashback:      If not it will set the flashback styles to default_style
        :param dialogue_styles:     Styles that will be set to default_style
        :param top_styles:          Styles that will be set to default_style and an8 added to tags
        :param italics_styles:      Styles that will be set to default_style and i1 added to tags
        :param alt_style:           The default alt/overlap style that lines will be set to
        :param alt_styles:          Possible identifiers for styles that should be set to the alt_style
        :param exact_names:         Match style names in full instead of substring matching as mentioned above. (still case-insensitive)

        :param custom_replacements: Other styles to replace with Default and where custom tags might want to be prepended.\n
                                    If any of these get matched then the other operations will be skipped.\n
                                    Defaults to the positional Styles (with custom margins) that the annoying CCC subs from Crunchyroll have.\n
                                    Keep in mind that the margins of the restyle presets might not look great for these positional styles.\n
                                    The tuple value option stands for (TagsToPrepend, MarginL, MarginR).
        """

        def name_matches(name: str, other: str) -> bool:
            if exact_names:
                return name.casefold() == other.casefold()
            else:
                return name.casefold() in other.casefold()

        def get_default(line: _Line, allow_default: bool = True) -> str:
            placeholder = default_style
            is_default = True
            if alt_styles:
                for s in alt_styles:
                    if name_matches(s, line.style):
                        placeholder = alt_style
                        is_default = False
            if "flashback" in line.style.lower():
                return placeholder if not keep_flashback else "Flashback"

            if is_default:
                return placeholder if allow_default else line.style

            return placeholder

        def _func(lines: LINES):
            for line in lines:
                custom_match = False
                if custom_replacements and bool(match := next(filter(lambda x: name_matches(x, line.style), custom_replacements.keys()), None)):
                    custom_match = True
                    line.style = get_default(line)
                    value = custom_replacements[match]  # type: ignore # fuck off mypy
                    line.text = f"{{{value if isinstance(value, str) else value[0]}}}{line.text}"
                    if not isinstance(value, str):
                        line.margin_l = value[1]
                        line.margin_r = value[2]

                if custom_match:
                    continue

                add_italics_tag = italics_styles and bool([s for s in italics_styles if name_matches(s, line.style)])
                add_top_tag = top_styles and bool([s for s in top_styles if name_matches(s, line.style)])

                if any([add_italics_tag, add_top_tag]):
                    line.style = get_default(line)
                    tags = "" if not add_italics_tag else R"\i1"
                    tags = tags if not add_top_tag else tags + R"\an8"
                    line.text = f"{{{tags}}}{line.text}"

                line.style = get_default(line, False)

                if dialogue_styles:
                    for s in dialogue_styles:
                        if s.casefold() in line.style.casefold():
                            line.style = default_style

        return self.manipulate_lines(_func).clean_styles()

    def shift_0(
        self,
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = None,
        allowed_styles: list[str] | None = DEFAULT_DIALOGUE_STYLES,
    ) -> Self:
        """
        Does the famous shift by 0 frames to fix frame timing issues.
        (It's basically just converting time to frame and back)

        This does not currently exactly reproduce the aegisub behaviour but it should have the same effect.

        :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
        :param allowed_styles:  A list of style names this is run on (case-insensitive).
                                Runs on every line if None.
        """
        resolved_ts = resolve_timesource_and_scale(timesource, timescale, fetch_from_setup=True, caller=self)

        def _func(lines: LINES):
            for line in lines:
                if not allowed_styles or line.style.casefold() in {style.casefold() for style in allowed_styles}:
                    result = self._shift_line_by_frames(line, 0, resolved_ts, OutOfBoundsMode.ERROR)
                    line = result.line

        return self.manipulate_lines(_func)

    def merge(
        self,
        file: PathLike | GlobSearch,
        sync: None | int | str = None,
        sync2: None | str = None,
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = None,
        use_actor_field: bool = False,
        no_error: bool = False,
        sort_lines: bool = False,
        shift_mode: ShiftMode = ShiftMode.FRAME,
        oob_mode: OutOfBoundsMode = OutOfBoundsMode.ERROR,
    ) -> Self:
        """
        Merge another subtitle file with syncing if needed.

        :param file:            The file to be merged.
        :param sync:            Can be None to not adjust timing at all, an int for a frame number or a string for a syncpoint name.
        :param sync2:           The syncpoint you want to use for the second file.
                                This is needed if you specified a frame for sync and still want to use a specific syncpoint.
        :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
        :param use_actor_field: Checks the actor field instead of effect for the names if True.
        :param no_error:        Don't error and warn instead if syncpoint not found.
        :param sort_lines:      Sort the lines by the starting timestamp.
                                This was done by default before but may cause issues with subtitles relying on implicit layering.
        :param shift_mode:      Choose what to shift by. Defaults to shifting by frames.
        :param oob_mode:        What to do with lines that are out of bounds after shifting.
        """
        if sync is not None or sync2 is not None and shift_mode == ShiftMode.FRAME:
            resolved_ts = resolve_timesource_and_scale(timesource, timescale, fetch_from_setup=True, caller=self)

        file = ensure_path_exists(file, self)
        mergedoc = self._read_doc(file)
        doc = self._read_doc()
        doc_name = ensure_path_exists(self.file, self).name if str(self.source).lower().endswith(".mkv") else ensure_path(self.source, self).name
        self._warn_mismatched_properties(doc, mergedoc, doc_name, file.name)

        events = []
        tomerge = []
        existing_styles = [style.name for style in doc.styles]
        target = None if not isinstance(sync, int) else sync

        # Find syncpoint in current document if sync is a string
        for line in doc.events:
            events.append(line)
            line = cast(_Line, line)
            if target is None and isinstance(sync, str):
                field = line.name if use_actor_field else line.effect
                if field.lower().strip() == sync.lower().strip() or line.text.lower().strip() == sync.lower().strip():
                    if shift_mode == ShiftMode.FRAME:
                        target = resolved_ts.time_to_frame(int(line.start.total_seconds() * 1000), TimeType.START, 3)
                    else:
                        target = line.start

        if target is None and isinstance(sync, str):
            msg = f"Syncpoint '{sync}' was not found."
            if no_error:
                warn(msg, self)
                return self
            raise error(msg, self)

        mergedoc.events = cast(list[_Line], mergedoc.events)

        # Find second syncpoint if any
        second_sync: int | timedelta | None = None
        for line in mergedoc.events:
            if not isinstance(sync, str) and not sync2:
                break
            elif not isinstance(sync, int):
                sync2 = sync2 or sync
            if not sync2:
                break
            field = line.name if use_actor_field else line.effect
            if field.lower().strip() == sync2.lower().strip() or line.text.lower().strip() == sync2.lower().strip():
                if shift_mode == ShiftMode.FRAME:
                    second_sync = resolved_ts.time_to_frame(int(line.start.total_seconds() * 1000), TimeType.START, 3)
                else:
                    second_sync = line.start
                mergedoc.events.remove(line)
                break

        sorted_lines = sorted(mergedoc.events, key=lambda event: event.start)

        # Assume the first line to be the second syncpoint if none was found
        if second_sync is None and target is not None:
            for line in filter(lambda event: event.TYPE != "Comment", sorted_lines):
                if shift_mode == ShiftMode.FRAME:
                    second_sync = resolved_ts.time_to_frame(int(line.start.total_seconds() * 1000), TimeType.START, 3)
                else:
                    second_sync = line.start
                break

        # Merge lines from file
        for line in sorted_lines if sort_lines else mergedoc.events:
            # Don't apply any offset if sync=None for plain merging or if target == source
            if target is None or target == second_sync:
                tomerge.append(line)
                continue

            if shift_mode == ShiftMode.FRAME:
                assert isinstance(target, int)
                assert isinstance(second_sync, int)
                offset = target - second_sync
                line_result = self._shift_line_by_frames(line, offset, resolved_ts, oob_mode)
            else:
                assert isinstance(target, timedelta)
                assert isinstance(second_sync, timedelta)
                offset = target - second_sync
                line_result = self._shift_line_by_time(line, offset, oob_mode)

            if line_result.was_out_of_bounds:
                warn(f"Line is out of bounds: {line.start} - {line.end}:\n\t{line.text}", self)
                if oob_mode == OutOfBoundsMode.DROP_LINE:
                    continue

            tomerge.append(line_result.line)

        if tomerge:
            events.extend(tomerge)
            doc.events = events
            for style in mergedoc.styles:
                if style.name in existing_styles:
                    continue
                doc.styles.append(style)

        self._update_doc(doc)
        return self

    def collect_fonts(
        self,
        use_system_fonts: bool = True,
        search_current_dir: bool = True,
        additional_fonts: list[PathLike] = [],
        collect_draw_fonts: bool = True,
        error_missing: bool = False,
        use_ntfs_compliant_names: bool | None = None,
    ) -> list[FontFile]:
        """
        Collects fonts for current subtitle.
        Note that this places all fonts into the workdir for the episode/Setup and all fonts in it.

        :param use_system_fonts:            Parses and checks against all installed fonts
        :param search_current_dir:          Recursively checks the current work directory for fonts
        :param additional_fonts:            Can be a directory or a path to a file directly (or a list of either)
        :param collect_draw_fonts:          Whether or not to include fonts used for drawing (usually Arial)
                                            See https://github.com/libass/libass/issues/617 for details.
        :param error_missing:               Raise an error instead of just warnings when a font is missing.\n
                                            This is **deprecated** and will be removed at some point in the future.
                                            Please use `error_on_danger` in the Setup.
        :param use_ntfs_compliant_names:    Ensure that filenames will work on a NTFS (Windows) filesystem.
                                            The `None` default means it'll use them but only if you're running the script on windows.

        :return:                        A list of FontFile objects
        """

        if not isinstance(additional_fonts, list):
            additional_fonts = [additional_fonts]

        if search_current_dir:
            additional_fonts.append(os.getcwd())

        resolved_paths: list[Path] = []

        for f in additional_fonts:
            f = ensure_path_exists(f, self, True)
            if f.is_dir():
                resolved_paths.extend([file for file in f.rglob("*.[tT][tT][fF]")])
                resolved_paths.extend([file for file in f.rglob("*.[oO][tT][fF]")])
                resolved_paths.extend([file for file in f.rglob("*.[tT][tT][cC]")])
                resolved_paths.extend([file for file in f.rglob("*.[oO][tT][cC]")])
            else:
                if f.suffix.lower() not in [".ttf", ".otf", ".ttc", ".otc"]:
                    raise error(f"'{f.name}' is not a font!", self)
                resolved_paths.append(f)
        from .font import collect_fonts as collect

        info(f"Collecting fonts for '{self.file.stem}'...", self)

        if error_missing:
            warn("The 'error_missing' parameter is deprecated.\nPlease use the 'error_on_danger' variable on the Setup.", self, 1)

        if use_ntfs_compliant_names is None:
            use_ntfs_compliant_names = os.name == "nt"

        return collect(self, use_system_fonts, resolved_paths, collect_draw_fonts, error_missing, use_ntfs_compliant_names)

    def restyle(self, styles: Style | list[Style], clean_after: bool = True, delete_existing: bool = False, adjust_styles: bool = True) -> Self:
        """
        Add (and replace existing) styles to the subtitle file.

        :param styles:          Either a single or a list of ass Styles
        :param clean_after:     Clean unused styles after
        :param delete_existing: Delete all existing styles before adding new ones
        :param adjust_styles:   Resize the styles to match the script resolution.
                                This assumes 1080p for the actual style res as all the presets are that.
        """
        if not isinstance(styles, list):
            styles = [styles]

        styles = styles.copy()

        doc = self._read_doc()
        script_res = int(doc.info.get("PlayResY", 360))
        if script_res != 1080 and adjust_styles:
            styles = resize_preset(styles, script_res)

        if delete_existing:
            doc.styles = []

        names = [style.name.casefold() for style in styles]
        existing = [style for style in doc.styles if style.name.casefold() not in names]
        styles.extend(existing)
        doc.styles = styles

        self._update_doc(doc)
        if clean_after:
            return self.clean_styles()
        else:
            return self

    def resample(
        self,
        video: PathLike | None = None,
        src_width: int | None = None,
        src_height: int | None = None,
        use_arch: bool | None = None,
        quiet: bool = True,
    ) -> Self:
        """
        Resample subtitles to match the resolution of the specified video.

        :param video:           Path to a video. Will resort to a 1080p dummy video if None.
        :param src_width:       The width of the resolution the subs are currently at
        :param src_height:      The height of the resolution the subs are currently at
                                Both of the above params will be taken from the sub file if not given.
                                (Assuming 640 x 360 if nothing is given in the document)

        :param use_arch:        Uses arch1t3cht's perspective resampler script to fix any perspective stuff after resampling.
                                This requires arch.Resample.moon in either of your autoload folders.
                                None means it will use it if it can find the script. True will try to force it.
        """
        aegicli = get_executable("aegisub-cli", False)
        video = dummy_video(1920, 1080) if not video else ensure_path_exists(video, self)
        doc = self._read_doc()

        if not src_width:
            src_width = doc.info.get("PlayResX", 640)

        if not src_height:
            src_height = doc.info.get("PlayResY", 360)

        if use_arch is None:
            use_arch = has_arch_resampler()

        output = Path(get_temp_workdir(), f"{self.file.stem}_resampled.ass")
        args = [aegicli, "--video", str(video.resolve()), str(self.file.resolve()), str(output), "tool/resampleres"]
        if run_commandline(args, quiet):
            raise error("Failed to resample subtitles!", self)

        if use_arch:
            prevout = output
            output = Path(get_temp_workdir(), f"{self.file.stem}_resampled_arch.ass")

            # fmt: off
            dialog_json = json.dumps({"button": 0, "values": {"srcresx": src_width, "srcresy": src_height, "centerorg": "false"}})
            args = [aegicli, "--video", str(video.resolve()), "--dialog", dialog_json, "--automation", "arch.Resample.moon", str(prevout), str(output), "Resample Perspective"]
            # fmt: on
            if run_commandline(args, quiet):
                raise error("Failed to resample perspective of subtitles!", self)

        self.file.unlink(True)
        self.file = ensure_path(shutil.copy(output, self.file), self)
        clean_temp_files()
        return self

    def separate_signs(
        self, styles: list[str] = DEFAULT_DIALOGUE_STYLES, inverse: bool = False, heuristics: bool = False, print_heuristics: bool = True
    ) -> Self:
        """
        Basically deletes lines that have any of the passed styles.

        :param styles:      List of style names to get rid of (case-insensitive)
        :param inverse:     Treat the list as the opposite. Will remove lines that *don't* have any of those styles.
        :param heuristics:  Also use heuristics for detecting signs.
        """

        def _is_sign(line: _Line) -> bool:
            confidence = 0
            style_check = False
            if styles and (line.style.casefold() not in [str(style).casefold() for style in styles]):
                style_check = True
                confidence += 2

            if heuristics and confidence < 2:
                if line.name:
                    if "onscreen" in line.name.lower().replace(" ", "") or line.name.lower() == "type" or line.name.lower() == "sign":
                        confidence += 1

                if R"\pos" in line.text:
                    confidence += 1
                if R"\mov" in line.text:
                    confidence += 1
                if R"\fn" in line.text:
                    confidence += 1
                if R"\blur" in line.text or R"\be" in line.text:
                    confidence += 1

                an_types = [Rf"\an{num}" for num in range(1, 10) if num not in (2, 8)]
                for an in an_types:
                    if an in line.text:
                        confidence += 1
                        break
                if print_heuristics and confidence >= 2 and not style_check:  # and styles:
                    info(f"Line with dialogue style passed heuristics:\n{line.text}", self)

            return confidence >= 2

        def filter_lines(lines: LINES):
            events = []
            for line in lines:
                skip = not inverse
                if _is_sign(line):
                    skip = inverse

                if skip:
                    continue
                events.append(line)
            return events

        return self.manipulate_lines(filter_lines).clean_styles()

    def change_layers(self, styles: list[str] = DEFAULT_DIALOGUE_STYLES, layer: int | None = None, additive: bool = True) -> Self:
        """
        Set layer to the specified number or adds the number to the existing one on every line with a style you selected.

        :param styles:      List of styles to look for (case-insensitive)
        :param layer:       The layer you want. Defaults to 50 for additive and 99 otherwise.
        :param additive:    Add specified layer number instead of replacing the existing one.
        """
        if not layer:
            layer = 50 if additive else 99

        def _func(lines: LINES) -> None:
            for line in lines:
                for style in styles:
                    if str(line.style).strip().casefold() == style.strip().casefold():
                        line.layer = layer if not additive else line.layer + layer

        return self.manipulate_lines(_func)

    def purge_macrons(self, styles: list[str] | None = DEFAULT_DIALOGUE_STYLES) -> Self:
        """
        Removes romaji macrons from every dialogue line.
        German subs use this a lot and a lot of fonts don't support it, so I like to purge them.

        :param styles:      List of styles to look for (case-insensitive).
                            Runs on all styles if None.
        """
        macrons: list[tuple[str, str]] = [("ā", "a"), ("ē", "e"), ("ī", "i"), ("ō", "o"), ("ū", "u")]

        def _func(lines: LINES):
            for line in lines:
                process = not styles
                for style in styles or []:
                    if str(line.style).strip().casefold() == style.strip().casefold():
                        process = True
                if process:
                    for macron in macrons + [(m[0].upper(), m[1].upper()) for m in macrons]:
                        line.text = line.text.replace(macron[0], macron[1])

        return self.manipulate_lines(_func)

    def shift(
        self,
        frames: int,
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = None,
        oob_mode: OutOfBoundsMode = OutOfBoundsMode.ERROR,
    ) -> Self:
        """
        Shifts all lines by any frame number.

        :param frames:              Number of frames to shift by
        :param timesource:          The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                    For details check the docstring on the type.
        :param oob_mode:            What to do with lines that are out of bounds after shifting.
        """
        resolved_ts = resolve_timesource_and_scale(timesource, timescale, fetch_from_setup=True, caller=self)

        def shift_lines(lines: LINES):
            new_list = list[_Line]()
            for line in lines:
                line_result = self._shift_line_by_frames(line, frames, resolved_ts, oob_mode)

                if line_result.was_out_of_bounds:
                    warn(f"Line is out of bounds: {line.start} - {line.end}:\n\t{line.text}", self)
                    if oob_mode == OutOfBoundsMode.DROP_LINE:
                        continue

                new_list.append(line_result.line)
            return new_list

        return self.manipulate_lines(shift_lines)

    def copy(self, filename: PathLike = None) -> Self:
        """
        Creates a new copy of the current SubFile object, including its file.
        So you can run anything on the new one without impacting the other one.

        :param filename:    Use a specific filename for this copy. Don't include an extension.
                            If this is a dir it will have the same name and be placed in the dir.

        :return:            A new SubFile instance
        """
        doc = self._read_doc()

        new_path = ensure_path(uniquify_path(self.file), self)
        if filename:
            new_path = make_output(self.file, "ass", user_passed=filename)

        with open(new_path, "w", encoding=self.encoding) as writer:
            doc.dump_file(writer)

        new = self.__class__(new_path, self.container_delay, self.source)
        new.encoding = self.encoding
        return new

    @classmethod
    def from_srt(
        cls: type[Self],
        file: PathLike,
        an8_all_caps: bool = True,
        style_all_caps: bool = True,
        timesource: TimeSourceT = Fraction(24000, 1001),
        timescale: TimeScaleT = TimeScale.MKV,
        encoding: str = "UTF8",
    ) -> Self:
        """
        Convert srt subtitles to an ass SubFile.
        Automatically applies Gandhi styling. Feel free to restyle.
        Also worth noting that this creates a file that assumes 1920x1080. Use the resample function if you need something else.

        :param file:            Input srt file
        :param an8_all_caps:    Automatically an8 every full caps line with over 7 characters because they're usually signs.
        :param style_all_caps:  Also set the style of these lines to "Sign" wether it exists or not.
        :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
        :param encoding:        Encoding used to read the file. Defaults to UTF8.
        """
        caller = "SubFile.from_srt"
        file = ensure_path_exists(file, caller)
        resolved_ts = resolve_timesource_and_scale(timesource, timescale, caller=cls)

        compiled = re.compile(SRT_REGEX, re.MULTILINE)

        def srt_timedelta(timestamp: str, time_type: TimeType) -> timedelta:
            args = timestamp.split(",")[0].split(":")
            parsed = timedelta(hours=int(args[0]), minutes=int(args[1]), seconds=int(args[2]), milliseconds=int(timestamp.split(",")[1]))
            cope = resolved_ts.time_to_frame(int(parsed.total_seconds() * 1000), time_type, 3)
            cope = resolved_ts.frame_to_time(cope, time_type, 3, True)
            return timedelta(milliseconds=cope)

        def convert_tags(text: str) -> tuple[str, bool]:
            text = text.strip().replace("\n", "\\N")
            is_sign = False
            if an8_all_caps and text.upper() == text and len(text) > 7:
                text = R"{\an8}" + text
                is_sign = True
            text = re.sub(r"[\<|{]i[\>|}]", R"{\\i1}", text)
            text = re.sub(r"[\<|{]\/i[\>|}]", R"{\\i}", text)
            text = re.sub(r"[\<|{]b[\>|}]", R"{\\b1}", text)
            text = re.sub(r"[\<|{]\/b[\>|}]", R"{\\b}", text)
            text = re.sub(r"[\<|{]u[\>|}]", R"{\\u1}", text)
            text = re.sub(r"[\<|{]\/u[\>|}]", R"{\\u}", text)
            return text, is_sign

        doc = create_document()

        with open(file, "r", encoding=encoding) as reader:
            content = reader.read() + "\n"
            for match in compiled.finditer(content):
                start = srt_timedelta(match["start"], TimeType.START)
                end = srt_timedelta(match["end"], TimeType.END)
                text, sign = convert_tags(match["text"])
                doc.events.append(Dialogue(layer=99, start=start, end=end, text=text, style="Sign" if sign and style_all_caps else "Default"))

        out = file.with_suffix(".ass")
        with open(out, "w", encoding="utf_8_sig") as writer:
            doc.dump_file(writer)
        out = cls(file=out, container_delay=0, source=file)
        return out.restyle(GJM_GANDHI_PRESET)

    @classmethod
    def from_mkv(cls: type[Self], file: PathLike, track: int = 0, preserve_delay: bool = False, quiet: bool = True, **kwargs: Any) -> Self:
        """
        Extract subtitle from mkv.\n
        The track must be either an ASS or SRT subtitle. SRT will be converted automatically.

        :param file:            Input mkv file
        :param track:           Relative track number
        :param preserve_delay:  Preserve existing container delay
        :param kwargs:          Other args to pass to `from_srt` if trying to extract srt subtitles
        """
        caller = "SubFile.from_mkv"
        file = ensure_path_exists(file, caller)
        parsed = ParsedFile.from_file(file, caller)
        parsed_track = parsed.find_tracks(relative_id=track, type=TrackType.SUB, error_if_empty=True, caller=caller)[0]

        if parsed_track.codec_name not in ["ass", "subrip"]:
            raise error("The selected track is not an ASS or SRT subtitle.", caller)

        mkvextract = get_executable("mkvextract")
        out = Path(get_workdir(), f"{file.stem}_{parsed_track.index}.{'ass' if parsed_track.codec_name == 'ass' else 'srt'}")
        args = [mkvextract, str(file), "tracks", f"{parsed_track.index}:{str(out)}"]
        if run_commandline(args, quiet):
            raise error("Failed to extract subtitle!", caller)

        delay = 0 if not preserve_delay else parsed_track.container_delay

        if parsed_track.codec_name == "subrip":
            subfile = cls.from_srt(out, **kwargs)
            subfile.container_delay = delay
            subfile.source = file
            out.unlink(True)
            return subfile

        return cls(file=out, container_delay=delay, source=file)
