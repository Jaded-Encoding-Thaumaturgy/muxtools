from __future__ import annotations
from ass import Document, Comment, Dialogue, Style, parse as parseDoc
from dataclasses import dataclass
from typing import Any, TypeVar
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
import shutil
import json
import re
import os

from .styles import GJM_GANDHI_PRESET
from .subutils import create_document, dummy_video, has_arch_resampler
from ..utils.glob import GlobSearch
from ..utils.download import get_executable
from ..utils.types import PathLike, TrackType
from ..utils.log import debug, error, info, warn
from ..utils.convert import frame_to_timedelta, timedelta_to_frame
from ..utils.env import get_temp_workdir, get_workdir, run_commandline
from ..utils.files import ensure_path_exists, get_absolute_track, make_output, clean_temp_files, uniquify_path
from ..muxing.muxfiles import MuxingFile

__all__ = ["FontFile", "SubFile", "DEFAULT_DIALOGUE_STYLES"]


DEFAULT_DIALOGUE_STYLES = ["default", "main", "alt", "overlap", "flashback", "top", "italics"]
SRT_REGEX = r"\d+[\r\n](?:(?P<start>\d+:\d+:\d+,\d+) --> (?P<end>\d+:\d+:\d+,\d+))[\r\n](?P<text>(?:.+\r?\n)+(?=(\r?\n)?))"


@dataclass
class FontFile(MuxingFile):
    pass


@dataclass
class SubFile(MuxingFile):
    """
    Utility class representing a subtitle file with various functions to run on.

    :param file:            Can be a string, Path object or GlobSearch.
                            If the GlobSearch returns multiple results or if a list was passed it will merge them.

    :param container_delay: Set a container delay used in the muxing process later.
    :param source:          The file this sub originates from, will be set by the constructor.
    :param encoding:        Encoding used for reading and writing the subtitle files.
    """

    encoding = "utf_8_sig"

    def __post_init__(self):
        if isinstance(self.file, GlobSearch):
            self.file = self.file.paths

        if isinstance(self.file, list) and len(self.file) > 1:
            debug("Merging sub files...", self)
            docs: list[Document] = []
            for f in self.file:
                f = ensure_path_exists(f, self)
                with open(f, "r", encoding=self.encoding) as read:
                    docs.append(parseDoc(read))

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

            self.source = self.file[0]
            out = make_output(self.file[0], "ass", "merged")
            with open(out, "w", encoding=self.encoding) as writer:
                main.dump_file(writer)

            self.file = out
            debug("Done")
        else:
            self.file = ensure_path_exists(self.file, self)
            self.source = self.file
            if not os.path.samefile(self.file.parent, get_workdir()):
                out = make_output(self.file, "ass", "vof")
                with open(out, "w", encoding=self.encoding) as writer:
                    self._read_doc().dump_file(writer)
                self.file = out

    def _read_doc(self, file: PathLike | None = None) -> Document:
        with open(self.file if not file else file, "r", encoding=self.encoding) as reader:
            return parseDoc(reader)

    def __update_doc(self, doc: Document):
        with open(self.file, "w", encoding=self.encoding) as writer:
            doc.dump_file(writer)

    def clean_styles(self: SubFileSelf) -> SubFileSelf:
        """
        Deletes unused styles from the document
        """
        doc = self._read_doc()
        used_styles = {line.style for line in doc.events if line.TYPE == "Dialogue"}
        regex = re.compile(r"\{.*?\\r([^\\]+)\}")
        for line in [line for line in doc.events if line.TYPE == "Dialogue"]:
            for match in regex.finditer(line.text):
                used_styles.add(match.group(1))
        doc.styles = [style for style in doc.styles if style.name in used_styles]
        self.__update_doc(doc)
        return self

    def clean_garbage(self: SubFileSelf) -> SubFileSelf:
        """
        Removes the "Aegisub Project Garbage" section from the file
        """
        doc = self._read_doc()
        doc.sections.pop("Aegisub Project Garbage", None)
        self.__update_doc(doc)
        return self

    def autoswapper(self: SubFileSelf, allowed_styles: list[str] | None = DEFAULT_DIALOGUE_STYLES, print_swaps: bool = False) -> SubFileSelf:
        """
        autoswapper does the swapping.
        Too lazy to explain

        :param allowed_styles:      List of allowed styles to do the swapping on
                                    Will run on every line if passed `None`
        :param print_swaps:         Prints the swaps

        :return:                    This SubTrack
        """
        doc = self._read_doc()

        events = []

        for i, line in enumerate(doc.events):
            if not allowed_styles or line.style.lower() in (style.lower() for style in allowed_styles):
                to_swap: dict = {}
                # {*}This will be replaced{*With this}
                for match in re.finditer(re.compile(r"\{\*\}([^{]*)\{\*([^}*]+)\}"), line.text):
                    to_swap.update({f"{match.group(0)}": f"{{*}}{match.group(2)}{{*{match.group(1)}}}"})

                # This sentence is no longer{** incomplete}
                for match in re.finditer(re.compile(r"\{\*\*([^}]+)\}"), line.text):
                    to_swap.update({f"{match.group(0)}": f"{{*}}{match.group(1)}{{*}}"})

                # This sentence is no longer{*} incomplete{*}
                for match in re.finditer(re.compile(r"\{\*\}([^{]*)\{\* *\}"), line.text):
                    to_swap.update({f"{match.group(0)}": f"{{**{match.group(1)}}}"})
                # print(to_swap)
                for key, val in to_swap.items():
                    if print_swaps:
                        info(f'autoswapper: Swapped "{key}" for "{val}" on line {i}', self)
                    line.text = line.text.replace(key, val)

            if line.effect.strip() == "***" or line.name.strip() == "***":
                if isinstance(line, Comment):
                    line.TYPE = "Dialogue"
                elif isinstance(line, Dialogue):
                    line.TYPE = "Comment"

            events.append(line)

        doc.events = events
        self.__update_doc(doc)
        return self

    def unfuck_cr(
        self: SubFileSelf,
        default_style: str = "Default",
        keep_flashback: bool = True,
        dialogue_styles: list[str] | None = ["main", "default", "narrator", "narration"],
        top_styles: list[str] | None = ["top"],
        italics_styles: list[str] | None = ["italics", "internal"],
    ) -> SubFileSelf:
        """
        Removes any top and italics styles and replaces them with tags.

        :param default_style:       The default style that everything will be set to
        :param keep_flashback:      If not it will set the flashback styles to default_style
        :param dialogue_styles:     Styles that will be set to default_style
        :param top_styles:          Styles that will be set to default_style and an8 added to tags
        :param italics_styles:      Styles that will be set to default_style and i1 added to tags
        """
        doc = self._read_doc()
        events = []
        for line in doc.events:
            add_italics_tag = False
            if italics_styles:
                for s in italics_styles:
                    if s.casefold() in line.style.casefold():
                        add_italics_tag = True
                        if "flashback" in line.style.lower():
                            line.style = default_style if not keep_flashback else "Flashback"
                        else:
                            line.style = default_style
                        break
            add_top_tag = False
            if top_styles:
                for s in top_styles:
                    if s.casefold() in line.style.casefold():
                        add_top_tag = True
                        if "flashback" in line.style.lower():
                            line.style = default_style if not keep_flashback else "Flashback"
                        else:
                            line.style = default_style
                        break
            if add_italics_tag and add_top_tag:
                line.text = R"{\i1\an8}" + line.text
            elif add_italics_tag:
                line.text = R"{\i1}" + line.text
            elif add_top_tag:
                line.text = R"{\an8}" + line.text

            if not keep_flashback:
                if "flashback" in line.style.lower():
                    line.style = default_style
            else:
                if line.style == "flashback":
                    line.style = "Flashback"
            if dialogue_styles:
                for s in dialogue_styles:
                    if s.casefold() in line.style.casefold():
                        line.style = default_style
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        return self.clean_styles()

    def shift_0(
        self: SubFileSelf, fps: Fraction | PathLike = Fraction(24000, 1001), allowed_styles: list[str] | None = DEFAULT_DIALOGUE_STYLES
    ) -> SubFileSelf:
        """
        Does the famous shift by 0 frames to fix frame timing issues.
        (It's basically just converting time to frame and back)

        This does not currently exactly reproduce the aegisub behaviour but it should have the same effect.

        :param fps:             The fps fraction used for conversions. Also accepts a timecode (v2) file.
        :param allowed_styles:  A list of style names this will run on. Will run on every line if None.
        """
        doc = self._read_doc()
        events = []
        for line in doc.events:
            if not allowed_styles or line.style.lower() in allowed_styles:
                line.start = frame_to_timedelta(timedelta_to_frame(line.start, fps), fps, True)
                line.end = frame_to_timedelta(timedelta_to_frame(line.end, fps), fps, True)
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        return self

    def merge(
        self: SubFileSelf,
        file: PathLike | GlobSearch,
        sync: None | int | str = None,
        sync2: None | str = None,
        fps: Fraction | PathLike = Fraction(24000, 1001),
        use_actor_field: bool = False,
        no_error: bool = False,
    ) -> SubFileSelf:
        """
        Merge another subtitle file with syncing if needed.

        :param file:            The file to be merged.
        :param sync:            Can be None to not adjust timing at all, an int for a frame number or a string for a syncpoint name.
        :param sync2:           The syncpoint you want to use for the second file.
                                This is needed if you specified a frame for sync and still want to use a specific syncpoint.
        :param fps:             The fps used for time calculations. Also accepts a timecode (v2) file.
        :param use_actor_field: Checks the actor field instead of effect for the names if True.
        :param no_error:        Don't error and warn instead if syncpoint not found.
        """

        file = ensure_path_exists(file, self)
        mergedoc = self._read_doc(file)
        doc = self._read_doc()

        events = []
        tomerge = []
        existing_styles = [style.name for style in doc.styles]
        target = None if not isinstance(sync, int) else sync

        # Find syncpoint in current document if sync is a string
        for line in doc.events:
            events.append(line)
            if target == None and isinstance(sync, str):
                field = line.name if use_actor_field else line.effect
                if field.lower().strip() == sync.lower().strip() or line.text.lower().strip() == sync.lower().strip():
                    target = timedelta_to_frame(line.start, fps)

        if target == None and isinstance(sync, str):
            msg = f"Syncpoint '{sync}' was not found."
            if no_error:
                warn(msg, self)
                return self
            raise error(msg, self)

        # Find second syncpoint if any
        second_sync: int | None = None
        for line in mergedoc.events:
            if not isinstance(sync, str) and not sync2:
                break
            else:
                sync2 = sync2 or sync
            field = line.name if use_actor_field else line.effect
            if field.lower().strip() == sync2.lower().strip() or line.text.lower().strip() == sync2.lower().strip():
                second_sync = timedelta_to_frame(line.start, fps)
                mergedoc.events.remove(line)
                break

        sorted_lines = sorted(mergedoc.events, key=lambda event: event.start)

        # Assume the first line to be the second syncpoint if none was found
        if second_sync == None:
            for l in filter(lambda event: event.TYPE != "Comment", sorted_lines):
                second_sync = timedelta_to_frame(l.start, fps)
                break

        # Merge lines from file
        for line in sorted_lines:
            # Don't apply any offset if sync=None for plain merging or if target == source
            if target == None or target == second_sync:
                tomerge.append(line)
                continue

            # Apply frame offset
            offset = (target or -1) - second_sync
            line.start = frame_to_timedelta(timedelta_to_frame(line.start, fps) + offset, fps, True)
            line.end = frame_to_timedelta(timedelta_to_frame(line.end, fps) + offset, fps, True)
            tomerge.append(line)

        if tomerge:
            events.extend(tomerge)
            doc.events = events
            for style in mergedoc.styles:
                if style.name in existing_styles:
                    continue
                doc.styles.append(style)

        self.__update_doc(doc)
        return self

    def syncpoint_merge(
        self: SubFileSelf,
        syncpoint: str,
        mergefile: PathLike | GlobSearch,
        use_actor_field: bool = False,
        use_frames: bool = False,
        fps: Fraction | PathLike = Fraction(24000, 1001),
        override_p1: int | timedelta = None,
        add_offset: int | timedelta = None,
    ) -> SubFileSelf:
        """
        Merge other sub files (Opening/Ending kfx for example) with offsetting by syncpoints

        :param syncpoint:           The syncpoint to be used
        :param mergefile:           The file to be merged
        :param use_actor_field:     Search the actor field instead of the effect field for the syncpoint
        :param use_frames:          Uses frames to shift lines instead of direct timestamps
        :param fps:                 The fps to go off of for the conversion. Also accepts a timecode (v2) file.
        :param override_p1:         A manual override of the initial syncpoint
                                    Obviously either a frame number or timedelta

        :return:                    This SubTrack
        """
        mergefile = ensure_path_exists(mergefile, self)
        was_merged = False

        doc = self._read_doc()
        mergedoc = self._read_doc(mergefile)

        events = []
        tomerge = []
        existing_styles = [style.name for style in doc.styles]

        if isinstance(add_offset, int) and not use_frames:
            add_offset = frame_to_timedelta(add_offset, fps, True)

        for line in doc.events:
            events.append(line)
            if was_merged:
                continue
            field = line.name if use_actor_field else line.effect
            if (
                field.lower().strip() == syncpoint.lower().strip()
                or line.text.lower().strip() == syncpoint.lower().strip()
                or override_p1 is not None
            ):
                was_merged = True
                start = line.start if override_p1 is None else override_p1
                offset: timedelta | int = None
                for l in mergedoc.events:
                    lfield = l.name if use_actor_field else l.effect
                    if lfield.lower().strip() == syncpoint.lower().strip() or l.text.lower().strip() == syncpoint.lower().strip():
                        mergedoc.events.remove(l)
                        if use_frames:
                            offset = timedelta_to_frame(start - l.start, fps)
                        else:
                            offset = start - l.start

                        if add_offset:
                            offset += add_offset
                        break

                for l in sorted(mergedoc.events, key=lambda event: event.start):
                    if offset is None:
                        if use_frames:
                            offset = timedelta_to_frame(start - l.start, fps)
                        else:
                            offset = start - l.start

                        if add_offset:
                            offset += add_offset

                        l.start = start
                        l.end = l.end + (frame_to_timedelta(offset, fps, True) if use_frames else offset)
                    else:
                        l.start = l.start + (frame_to_timedelta(offset, fps, True) if use_frames else offset)
                        l.end = l.end + (frame_to_timedelta(offset, fps, True) if use_frames else offset)
                    tomerge.append(l)

        if was_merged:
            events.extend(tomerge)
            # Merge the styles in aswell
            for style in mergedoc.styles:
                if style.name in existing_styles:
                    continue
                doc.styles.append(style)

            doc.events = events
            self.__update_doc(doc)
        else:
            warn(f"Syncpoint '{syncpoint}' was not found!", self)

        return self

    def collect_fonts(
        self, use_system_fonts: bool = True, search_current_dir: bool = True, additional_fonts: list[PathLike] = [], collect_draw_fonts: bool = True
    ) -> list[FontFile]:
        """
        Collects fonts for current subtitle.
        Note that this places all fonts into the workdir for the episode/Setup and all fonts in it.

        :param use_system_fonts:        Parses and checks against all installed fonts
        :param search_current_dir:      Recursively checks the current work directory for fonts
        :param additional_fonts:        Can be a directory or a path to a file directly (or a list of either)
        :param collect_draw_fonts:      Whether or not to include fonts used for drawing (usually Arial)
                                        See https://github.com/libass/libass/issues/617 for details.

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
            else:
                if f.suffix.lower() not in [".ttf", ".otf"]:
                    raise error(f"'{f.name}' is not a font!", self)
                resolved_paths.append(f)
        from .font import collect_fonts as collect

        debug(f"Collecting fonts for '{self.file.stem}'...", self)

        return collect(self, use_system_fonts, resolved_paths, collect_draw_fonts)

    def restyle(self: SubFileSelf, styles: Style | list[Style], clean_after: bool = True, delete_existing: bool = False) -> SubFileSelf:
        """
        Add (and replace existing) styles to the subtitle file.

        :param styles:          Either a single or a list of ass Styles
        :param clean_after:     Clean unused styles after
        :param delete_existing: Delete all existing styles before adding new ones
        """
        if not isinstance(styles, list):
            styles = [styles]

        styles = styles.copy()

        doc = self._read_doc()
        if delete_existing:
            doc.styles = []

        names = [style.name.casefold() for style in styles]
        existing = [style for style in doc.styles if style.name.casefold() not in names]
        styles.extend(existing)
        doc.styles = styles

        self.__update_doc(doc)
        if clean_after:
            return self.clean_styles()
        else:
            return self

    def resample(
        self: SubFileSelf,
        video: PathLike | None = None,
        src_width: int | None = None,
        src_height: int | None = None,
        use_arch: bool | None = None,
        quiet: bool = True,
    ) -> SubFileSelf:
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
        self.file = shutil.copy(output, self.file)
        clean_temp_files()
        return self

    def separate_signs(self: SubFileSelf, styles: list[str] = DEFAULT_DIALOGUE_STYLES, inverse: bool = False) -> SubFileSelf:
        """
        Basically deletes lines that have any of the passed styles.

        :param styles:      List of style names to get rid of
        :param inverse:     Treat the list as the opposite. Will remove lines that *don't* have any of those styles.
        """
        doc = self._read_doc()
        events = []
        for line in doc.events:
            skip = inverse
            for style in styles:
                if str(line.style).strip().casefold() == style.strip().casefold():
                    skip = not inverse
                    break

            if skip:
                continue
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        return self.clean_styles()

    def change_layers(self: SubFileSelf, styles: list[str] = DEFAULT_DIALOGUE_STYLES, layer: int = 99) -> SubFileSelf:
        """
        Set layer to the specified number on every line with a style you selected.

        :param styles:      List of styles to look for
        :param layer:       The layer you want
        """
        doc = self._read_doc()
        events = []
        for line in doc.events:
            for style in styles:
                if str(line.style).strip().casefold() == style.strip().casefold():
                    line.layer = layer
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        return self

    def purge_macrons(self: SubFileSelf, styles: list[str] | None = DEFAULT_DIALOGUE_STYLES) -> SubFileSelf:
        """
        Removes romaji macrons from every dialogue line.
        German subs use this a lot and a lot of fonts don't support it, so I like to purge them.

        :param styles:      List of styles to look for
        """
        macrons: list[tuple[str, str]] = [("ā", "a"), ("ē", "e"), ("Ī", "i"), ("ō", "o"), ("ū", "u")]
        doc = self._read_doc()
        events = []
        for line in doc.events:
            process = not styles
            for style in styles or []:
                if str(line.style).strip().casefold() == style.strip().casefold():
                    process = True
            if process:
                for macron in macrons + [(m[0].upper(), m[1].upper()) for m in macrons]:
                    line.text: str = line.text.replace(macron[0], macron[1])
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        return self

    def shift(self: SubFileSelf, frames: int, fps: Fraction | PathLike = Fraction(24000, 1001)) -> SubFileSelf:
        """
        Shifts all lines by any frame number.

        :param frames:      Number of frames to shift by
        :param fps:         FPS needed for the timing calculations. Also accepts a timecode (v2) file.
        """
        doc = self._read_doc()
        events = []
        for line in doc.events:
            start = timedelta_to_frame(line.start, fps) + frames
            if start < 0:
                start = 0
            start = frame_to_timedelta(start, fps, compensate=True)
            end = timedelta_to_frame(line.end, fps) + frames
            if end < 0:
                continue
            end = frame_to_timedelta(end, fps, compensate=True)
            line.start = start
            line.end = end
            events.append(line)

        doc.events = events
        self.__update_doc(doc)
        return self

    def copy(self: SubFileSelf) -> SubFileSelf:
        """
        Creates a new copy of the current SubFile object, including its file.
        So you can run anything on the new one without impacting the other one.
        """
        doc = self._read_doc()
        new_path = uniquify_path(self.file)
        with open(new_path, "w", encoding=self.encoding) as writer:
            doc.dump_file(writer)

        new = self.__class__(new_path, self.container_delay, self.source)
        new.encoding = self.encoding
        return new

    @classmethod
    def from_srt(
        cls: type[SubFileSelf], file: PathLike, an8_all_caps: bool = True, fps: Fraction | PathLike = Fraction(24000, 1001), encoding: str = "UTF8"
    ) -> SubFileSelf:
        """
        Convert srt subtitles to an ass SubFile.
        Automatically applies Gandhi styling. Feel free to restyle.
        Also worth noting that this creates a file that assumes 1920x1080. Use the resample function if you need something else.

        :param file:            Input srt file
        :param an8_all_caps:    Automatically an8 every full caps line with over 7 characters because they're usually signs
        :param fps:             FPS needed for the time conversion. Also accepts a timecode (v2) file.
        :param encoding:        Encoding used to read the file. Defaults to UTF8.
        """
        caller = "SubFile.from_srt"
        file = ensure_path_exists(file, caller)

        compiled = re.compile(SRT_REGEX, re.MULTILINE)

        def srt_timedelta(timestamp: str) -> timedelta:
            args = timestamp.split(",")[0].split(":")
            parsed = timedelta(hours=int(args[0]), minutes=int(args[1]), seconds=int(args[2]), milliseconds=int(timestamp.split(",")[1]))
            cope = timedelta_to_frame(parsed, fps)
            cope = frame_to_timedelta(cope, fps, compensate=True)
            return cope

        def convert_tags(text: str) -> str:
            text = text.strip().replace("\n", "\\N")
            if an8_all_caps and text.upper() == text and len(text) > 7:
                text = R"{\an8}" + text
            text = re.sub(r"[\<|{]i[\>|}]", "{\\\i1}", text)
            text = re.sub(r"[\<|{]\/i[\>|}]", "{\\\i}", text)
            text = re.sub(r"[\<|{]b[\>|}]", "{\\b1}", text)
            text = re.sub(r"[\<|{]\/b[\>|}]", "{\\b}", text)
            text = re.sub(r"[\<|{]u[\>|}]", R"{\\u1}", text)
            text = re.sub(r"[\<|{]\/u[\>|}]", R"{\\u}", text)
            return text

        doc = create_document()

        with open(file, "r", encoding=encoding) as reader:
            content = reader.read() + "\n"
            for match in compiled.finditer(content):
                start = srt_timedelta(match["start"])
                end = srt_timedelta(match["end"])
                text = convert_tags(match["text"])
                doc.events.append(Dialogue(layer=99, start=start, end=end, text=text))

        out = file.with_suffix(".ass")
        with open(out, "w", encoding="utf_8_sig") as writer:
            doc.dump_file(writer)
        out = cls(out, 0, file)
        return out.restyle(GJM_GANDHI_PRESET)

    @classmethod
    def from_mkv(
        cls: type[SubFileSelf], file: PathLike, track: int = 0, preserve_delay: bool = False, quiet: bool = True, **kwargs: Any
    ) -> SubFileSelf:
        """
        Extract subtitle from mkv.

        :param file:            Input mkv file
        :param track:           Relative track number
        :param preserve_delay:  Preserve existing container delay
        :param kwargs:          Other args to pass to `from_srt` if trying to extract srt subtitles
        """
        caller = "SubFile.from_mkv"
        file = ensure_path_exists(file, caller)
        track = get_absolute_track(file, track, TrackType.SUB, caller)

        if track.format not in ["ASS", "UTF-8"]:
            raise error("The selected track is not an ASS or SRT subtitle.", caller)

        mkvextract = get_executable("mkvextract")
        out = Path(get_workdir(), f"{file.stem}_{track.track_id}.{'ass' if track.format == 'ASS' else 'srt'}")
        args = [mkvextract, str(file), "tracks", f"{track.track_id}:{str(out)}"]
        if run_commandline(args, quiet):
            raise error("Failed to extract subtitle!", caller)

        delay = 0 if not preserve_delay else getattr(track, "delay_relative_to_video", 0)

        if track.format == "UTF-8":
            subfile = cls.from_srt(out, **kwargs)
            subfile.container_delay = delay
            subfile.source = file
            return subfile

        return cls(out, delay, file)


SubFileSelf = TypeVar("SubFileSelf", bound=SubFile)
