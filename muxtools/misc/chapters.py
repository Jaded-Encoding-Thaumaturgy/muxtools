from __future__ import annotations

from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import TypeVar
from video_timestamps import TimeType
import os
import re

from ..subtitle.sub import SubFile
from ..utils.log import error, info, warn
from ..utils.glob import GlobSearch
from ..utils.download import get_executable
from ..utils.types import Chapter, PathLike
from ..utils.parsing import parse_ogm, parse_xml
from ..utils.files import clean_temp_files, ensure_path_exists, ensure_path
from ..utils.env import get_temp_workdir, get_workdir, run_commandline
from ..utils.convert import format_timedelta, frame_to_ms, ms_to_frame

__all__ = ["Chapters"]


class Chapters:
    chapters: list[Chapter] = []
    fps: Fraction | PathLike

    def __init__(
        self, chapter_source: PathLike | GlobSearch | Chapter | list[Chapter], fps: Fraction | PathLike = Fraction(24000, 1001), _print: bool = True
    ) -> None:
        """
        Convenience class for chapters

        :param chapter_source:      Input either txt with ogm chapters, xml or (a list of) self defined chapters.
        :param fps:                 Needed for timestamp convertion. Assumes 24000/1001 by default. Also accepts a timecode (v2, v4) file.
        :param _print:              Prints chapters after parsing and after trimming.
        """
        self.fps = fps
        if isinstance(chapter_source, tuple):
            self.chapters = [chapter_source]
        elif isinstance(chapter_source, list):
            self.chapters = chapter_source
        else:
            # Handle both OGM .txt files and xml files
            if isinstance(chapter_source, GlobSearch):
                chapter_source = chapter_source.paths[0]
            chapter_source = chapter_source if isinstance(chapter_source, Path) else Path(chapter_source)

            self.chapters = parse_xml(chapter_source) if chapter_source.suffix.lower() == ".xml" else parse_ogm(chapter_source)
            if _print:
                self.print()

        # Convert all framenumbers to timedeltas
        chapters = []
        for ch in self.chapters:
            if isinstance(ch[0], int):
                current = list(ch)
                current[0] = timedelta(milliseconds=frame_to_ms(current[0], TimeType.EXACT, self.fps, False))
                chapters.append(tuple(current))
            else:
                chapters.append(ch)
        self.chapters = chapters

    def trim(self: ChaptersSelf, trim_start: int = 0, trim_end: int = 0, num_frames: int = 0) -> ChaptersSelf:
        """
        Trims the chapters
        """
        if trim_start > 0:
            chapters: list[Chapter] = []
            for chapter in self.chapters:
                if ms_to_frame(int(chapter[0].total_seconds() * 1000), TimeType.START, self.fps) == 0:
                    chapters.append(chapter)
                    continue
                if ms_to_frame(int(chapter[0].total_seconds() * 1000), TimeType.START, self.fps) - trim_start < 0:
                    continue
                current = list(chapter)
                current[0] = current[0] - timedelta(milliseconds=frame_to_ms(trim_start, TimeType.EXACT, self.fps, False))
                if num_frames:
                    if current[0] > timedelta(milliseconds=frame_to_ms(num_frames - 1, TimeType.EXACT, self.fps, False)):
                        continue
                chapters.append(tuple(current))

            self.chapters = chapters
        if trim_end != 0:
            if trim_end > 0:
                chapters: list[Chapter] = []
                for chapter in self.chapters:
                    if ms_to_frame(int(chapter[0].total_seconds() * 1000), TimeType.START, self.fps) < trim_end:
                        chapters.append(chapter)
                self.chapters = chapters

        return self

    def set_names(self: ChaptersSelf, names: list[str | None]) -> ChaptersSelf:
        """
        Renames the chapters

        :param names:   List of names
        """
        old: list[str] = [chapter[1] for chapter in self.chapters]
        if len(names) > len(old):
            self.print()
            raise error("Chapters: too many names!", self)
        if len(names) < len(old):
            names += [None] * (len(old) - len(names))

        chapters: list[Chapter] = []
        for i, name in enumerate(names):
            current = list(self.chapters[i])
            current[1] = name
            chapters.append(tuple(current))

        self.chapters = chapters
        return self

    def add(self: ChaptersSelf, chapters: Chapter | list[Chapter], index: int = 0) -> ChaptersSelf:
        """
        Adds a chapter at the specified index
        """
        if isinstance(chapters, tuple):
            chapters = [chapters]
        else:
            chapters = chapters

        converted = []
        for ch in chapters:
            if isinstance(ch[0], int):
                current = list(ch)
                current[0] = timedelta(milliseconds=frame_to_ms(current[0], TimeType.EXACT, self.fps, False))
                converted.append(tuple(current))
            else:
                converted.append(ch)

        for ch in converted:
            self.chapters.insert(index, ch)
            index += 1
        return self

    def shift_chapter(self: ChaptersSelf, chapter: int = 0, shift_amount: int = 0) -> ChaptersSelf:
        """
        Used to shift a single chapter by x frames

        :param chapter:         Chapter number (starting at 0)
        :param shift_amount:    Frames to shift by
        """
        ch = list(self.chapters[chapter])
        ch_frame = ms_to_frame(int(ch[0].total_seconds() * 1000), TimeType.START, self.fps) + abs(shift_amount)
        if ch_frame >= 0:
            ch[0] = timedelta(milliseconds=frame_to_ms(ch_frame, TimeType.EXACT, self.fps, False))
        else:
            ch[0] = timedelta(seconds=0)
        self.chapters[chapter] = tuple(ch)
        return self

    def shift(self: ChaptersSelf, shift_amount: int) -> ChaptersSelf:
        """
        Shifts all chapters by x frames.

        :param shift_amount:    Frames to shift by
        """
        return [self.shift_chapter(i, shift_amount) for i, _ in enumerate(self.chapters)][-1]

    def print(self: ChaptersSelf) -> ChaptersSelf:
        """
        Prettier print for these because default timedelta formatting sucks
        """
        info("Chapters:")
        for time, name in self.chapters:
            print(f"{name}: {format_timedelta(time)} | {ms_to_frame(int(time.total_seconds() * 1000), TimeType.START, self.fps)}")
        print("", end="\n")
        return self

    def to_file(self: ChaptersSelf, out: PathLike | None = None) -> str:
        """
        Outputs the chapters to an OGM file

        :param out:     Can be either a directory or a full file path
        """
        if not out:
            out = get_workdir()
        out = ensure_path(out, self)
        if out.is_dir():
            out_file = os.path.join(out, "chapters.txt")
        else:
            out_file = out
        with open(out_file, "w", encoding="UTF-8") as f:
            f.writelines(
                [
                    f"CHAPTER{i:02d}={format_timedelta(chapter[0])}\nCHAPTER{i:02d}NAME=" f'{chapter[1] if chapter[1] else ""}\n'
                    for i, chapter in enumerate(self.chapters)
                ]
            )
        return out_file

    @staticmethod
    def from_sub(
        file: PathLike | SubFile,
        fps: Fraction | PathLike = Fraction(24000, 1001),
        use_actor_field: bool = False,
        markers: str | list[str] = ["chapter", "chptr"],
        _print: bool = True,
        encoding: str = "utf_8_sig",
    ) -> "Chapters":
        """
        Extract chapters from an ass file or a SubFile.

        :param file:            Input ass file or SubFile
        :param fps:             FPS passed to the chapter class for further operations. Also accepts a timecode (v2, v4) file.
        :param use_actor_field: Uses the actor field instead of the effect field for identification.
        :param markers:         Markers to check for.
        :param _print:          Prints the chapters after parsing
        :param encoding:        Encoding used to read the ass file if need be
        """
        from ass import parse_file, Comment

        if isinstance(markers, str):
            markers = [markers]

        if isinstance(file, SubFile):
            doc = file._read_doc()
        else:
            file = ensure_path_exists(file, "Chapters")
            with open(file if not file else file, "r", encoding=encoding) as reader:
                doc = parse_file(reader)

        pattern = re.compile(r"\{([^\\].+?)\}")
        chapters = list[Chapter]()
        for line in doc.events:
            field_value = str(line.name).lower() if use_actor_field else str(line.effect).lower()
            found = [m in field_value for m in markers]
            if any(found):
                match = pattern.search(line.text)
                if match:
                    chapters.append((line.start, match.group(1)))
                elif isinstance(line, Comment) and line.text:
                    chapters.append((line.start, str(line.text).strip()))
                else:
                    warn(f"Chapter {(len(chapters) + 1):02.0f} does not have a name!", "Chapters")
                    chapters.append((line.start, ""))

        if not chapters:
            warn("Could not find any chapters in subtitle!", "Chapters")
        ch = Chapters(chapters, fps)
        if _print and chapters:
            ch.print()
        return ch

    @staticmethod
    def from_mkv(file: PathLike, fps: Fraction | PathLike = Fraction(24000, 1001), _print: bool = True, quiet: bool = True) -> "Chapters":
        """
        Extract chapters from mkv.

        :param file:            Input mkv file
        :param fps:             FPS passed to the chapter class for further operations. Also accepts a timecode (v2, v4) file.
        :param _print:          Prints the chapters after parsing
        """
        caller = "Chapters.from_mkv"
        file = ensure_path_exists(file, caller)

        mkvextract = get_executable("mkvextract")
        out = Path(get_temp_workdir(), f"{file.stem}_chapters.txt")
        args = [mkvextract, str(file), "chapters", "-s", str(out)]
        if run_commandline(args, quiet):
            raise error("Failed to extract chapters!", caller)
        chapters = Chapters(out, fps, _print)
        clean_temp_files()
        return chapters


ChaptersSelf = TypeVar("ChaptersSelf", bound=Chapters)
