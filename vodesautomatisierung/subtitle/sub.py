from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from typing import Self
import re
from ass import Document, Comment, Dialogue, parse as parseDoc

from ..utils.log import debug, info, warn
from ..utils.convert import frame_to_timedelta, timedelta_to_frame
from ..utils.glob import GlobSearch
from ..utils.files import MuxingFile, PathLike, ensure_path_exists, make_output

DEFAULT_DIALOGUE_STYLES = ["default", "main", "alt", "overlap", "flashback", "top", "italics"]


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
                    if style.name.casefold() in [s.name.casefold() for s in existing_styles]:
                        warn(f"Ignoring style '{style.name}' due to preexisting style of the same name.", self)
                        continue
                    main.styles.append(style)

            out = make_output(self.file[0], "ass", "merged")
            with open(out, "w", encoding=self.encoding) as writer:
                main.dump_file(writer)

            self.file = out
            debug("Done")
        else:
            self.file = ensure_path_exists(self.file, self)
            out = make_output(self.file, "ass", "vof")
            with open(out, "w", encoding=self.encoding) as writer:
                self.__read_doc().dump_file(writer)
            self.file = out

    def __read_doc(self, file: PathLike | None = None) -> Document:
        with open(self.file if not file else file, "r", encoding=self.encoding) as reader:
            return parseDoc(reader)

    def __update_doc(self, doc: Document):
        with open(self.file, "w", encoding=self.encoding) as writer:
            doc.dump_file(writer)

    def clean_styles(self) -> Self:
        """
        Deletes unused styles from the document
        """
        doc = self.__read_doc()
        used_styles = {line.style for line in doc.events if line.TYPE == "Dialogue"}
        doc.styles = [style for style in doc.styles if style.name in used_styles]
        self.__update_doc(doc)
        return self

    def autoswapper(self, allowed_styles: list[str] | None = DEFAULT_DIALOGUE_STYLES, print_swaps: bool = False) -> Self:
        """
        autoswapper does the swapping.
        Too lazy to explain

        :param allowed_styles:      List of allowed styles to do the swapping on
                                    Will run on every line if passed `None`
        :param print_swaps:         Prints the swaps

        :return:                    This SubTrack
        """
        doc = self.__read_doc()

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
        self,
        default_style: str = "Default",
        keep_flashback: bool = True,
        dialogue_styles: list[str] | None = ["main", "default"],
        top_styles: list[str] | None = ["top"],
        italics_styles: list[str] | None = ["italics", "internal"],
    ) -> Self:
        """
        Removes any top and italics styles and replaces them with tags.

        :param default_style:       The default style that everything will be set to
        :param keep_flashback:      If not it will set the flashback styles to default_style
        :param dialogue_styles:     Styles that will be set to default_style
        :param top_styles:          Styles that will be set to default_style and an8 added to tags
        :param italics_styles:      Styles that will be set to default_style and i1 added to tags
        """
        doc = self.__read_doc()
        events = []
        for line in doc.events:
            add_italics_tag = False
            if italics_styles:
                for s in italics_styles:
                    if s.casefold() in line.style.casefold():
                        add_italics_tag = True
                        break
            add_top_tag = False
            if top_styles:
                for s in top_styles:
                    if s.casefold() in line.style.casefold():
                        add_top_tag = True
                        break
            if add_italics_tag and add_top_tag:
                line.text = R"{\i1\an8}" + line.text
            elif add_italics_tag:
                line.text = R"{\i1}" + line.text
            elif add_top_tag:
                line.text = R"{\an8}" + line.text

            if not keep_flashback and "flashback" in line.style.lower():
                line.style = default_style
            if dialogue_styles:
                for s in dialogue_styles:
                    if s.casefold() in line.style.casefold():
                        line.style = default_style
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        self.clean_styles()
        return self

    def shift_0(self, fps: Fraction = Fraction(24000, 1001), allowed_styles: list[str] | None = DEFAULT_DIALOGUE_STYLES) -> Self:
        """
        Does the famous shift by 0 frames to fix frame timing issues
        (It's basically just converting time to frame and back)

        This does not currently exactly reproduce the aegisub behaviour but it should have the same effect
        """
        doc = self.__read_doc()
        events = []
        for line in doc.events:
            if not allowed_styles or line.style.lower() in allowed_styles:
                line.start = frame_to_timedelta(timedelta_to_frame(line.start, fps), fps)
                line.end = frame_to_timedelta(timedelta_to_frame(line.end, fps), fps)
            events.append(line)
        doc.events = events
        self.__update_doc(doc)
        return self

    def syncpoint_merge(
        self,
        syncpoint: str,
        mergefile: PathLike | GlobSearch,
        use_actor_field: bool = False,
        use_frames: bool = False,
        fps: Fraction = Fraction(24000, 1001),
        override_p1: int | timedelta = None,
        add_offset: int | timedelta = None,
    ) -> Self:
        """
        Merge other sub files (Opening/Ending kfx for example) with offsetting by syncpoints

        :param syncpoint:           The syncpoint to be used
        :param mergefile:           The file to be merged
        :param use_actor_field:     Search the actor field instead of the effect field for the syncpoint
        :param use_frames:          Uses frames to shift lines instead of direct timestamps
        :param fps:                 The fps to go off of for the conversion
        :param override_p1:         A manual override of the initial syncpoint
                                    Obviously either a frame number or timedelta

        :return:                    This SubTrack
        """
        mergefile = ensure_path_exists(mergefile, self)
        was_merged = False

        doc = self.__read_doc()
        mergedoc = self.__read_doc(mergefile)

        events = []
        tomerge = []
        existing_styles = [style.name for style in doc.styles]

        if isinstance(add_offset, int) and not use_frames:
            add_offset = frame_to_timedelta(add_offset, fps)

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
                        l.end = l.end + (frame_to_timedelta(offset, fps) if use_frames else offset)
                    else:
                        l.start = l.start + (frame_to_timedelta(offset, fps) if use_frames else offset)
                        l.end = l.end + (frame_to_timedelta(offset, fps) if use_frames else offset)
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
