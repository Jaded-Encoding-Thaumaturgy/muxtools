from __future__ import annotations

from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import TypeVar
from video_timestamps import TimeType, ABCTimestamps
import re

from ..subtitle.sub import SubFile
from ..utils.log import error, info, warn, debug
from ..utils.glob import GlobSearch
from ..utils.download import get_executable
from ..utils.types import Chapter, LooseChapter, PathLike, TimeSourceT, TimeScaleT, TimeScale
from ..utils.parsing import parse_ogm, parse_xml
from ..utils.files import clean_temp_files, ensure_path_exists, ensure_path
from ..utils.env import get_temp_workdir, get_workdir, run_commandline, get_setup_attr
from ..utils.convert import format_timedelta, resolve_timesource_and_scale

__all__ = ["Chapters"]


class Chapters:
    chapters: list[Chapter]
    fps: Fraction | PathLike
    timestamps: ABCTimestamps

    def __init__(
        self,
        chapter_source: PathLike | GlobSearch | LooseChapter | list[LooseChapter],
        timesource: TimeSourceT = Fraction(24000, 1001),
        timescale: TimeScaleT = TimeScale.MKV,
        _print: bool = True,
    ) -> None:
        """
        Convenience class for chapters

        :param chapter_source:      Input either txt with ogm chapters, xml or (a list of) self defined chapters.
        :param timesource:          The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:           Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                    For details check the docstring on the type.
        :param _print:              Prints chapters after parsing and after trimming.
        """
        self.timestamps = resolve_timesource_and_scale(timesource, timescale, caller=self)
        if isinstance(chapter_source, tuple):
            chapters = [chapter_source]
        elif isinstance(chapter_source, list):
            chapters = chapter_source
        else:
            chapter_source = ensure_path(chapter_source, self)
            chapters = parse_xml(chapter_source) if chapter_source.suffix.lower() == ".xml" else parse_ogm(chapter_source)  # type: ignore

        # Convert all framenumbers to timedeltas
        normalized_chapters = list[Chapter]()
        for time_value, name in chapters:
            if isinstance(time_value, int):
                ms = self.timestamps.frame_to_time(time_value, TimeType.START, 3)
                normalized_chapters.append((timedelta(milliseconds=ms), name))
            else:
                normalized_chapters.append((time_value, name))
        self.chapters = normalized_chapters

        if _print and isinstance(chapter_source, Path):
            self.print()

    def trim(self: ChaptersSelf, trim_start: int = 0, trim_end: int = 0, num_frames: int = 0) -> ChaptersSelf:
        """
        Trims the chapters
        """
        if trim_start > 0:
            chapters: list[Chapter] = []
            for time_value, name in self.chapters:
                if self.timestamps.time_to_frame(int(time_value.total_seconds() * 1000), TimeType.START, 3) == 0:
                    chapters.append((time_value, name))
                    continue
                if self.timestamps.time_to_frame(int(time_value.total_seconds() * 1000), TimeType.START, 3) - trim_start < 0:
                    continue
                trim_start_ms = self.timestamps.frame_to_time(trim_start, TimeType.START, 3)
                time_value = time_value - timedelta(milliseconds=trim_start_ms)
                if num_frames:
                    last_frame_ms = self.timestamps.frame_to_time(num_frames - 1, TimeType.START, 3)
                    if time_value > timedelta(milliseconds=last_frame_ms):
                        continue
                chapters.append((time_value, name))

            self.chapters = chapters
        if trim_end is not None and trim_end != 0:
            if trim_end > 0:
                chapters: list[Chapter] = []  # type: ignore[no-redef]
                for chapter in self.chapters:
                    if self.timestamps.time_to_frame(int(chapter[0].total_seconds() * 1000), TimeType.START, 3) < trim_end:
                        chapters.append(chapter)
                self.chapters = chapters

        return self

    def set_names(self: ChaptersSelf, names: list[str | None]) -> ChaptersSelf:
        """
        Renames the chapters

        :param names:   List of names
        """
        old: list[str | None] = [chapter[1] for chapter in self.chapters]
        if len(names) > len(old):
            self.print()
            raise error("Chapters: too many names!", self)
        if len(names) < len(old):
            names += [None] * (len(old) - len(names))

        chapters: list[Chapter] = []
        for i, name in enumerate(names):
            time, _ = self.chapters[i]
            chapters.append((time, name))

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
                ms = self.timestamps.frame_to_time(current[0], TimeType.START, 3)
                current[0] = timedelta(milliseconds=ms)
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
        time, name = self.chapters[chapter]
        ch_frame = self.timestamps.time_to_frame(int(time.total_seconds() * 1000), TimeType.START, 3) + shift_amount
        if ch_frame > 0:
            ms = self.timestamps.frame_to_time(ch_frame, TimeType.START, 3)
            time = timedelta(milliseconds=ms)
        else:
            time = timedelta(seconds=0)
        self.chapters[chapter] = (time, name)
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
            frame = self.timestamps.time_to_frame(int(time.total_seconds() * 1000), TimeType.START, 3)
            print(f"{name}: {format_timedelta(time)} | {frame}")
        print("", end="\n")
        return self

    def to_file(self: ChaptersSelf, out: PathLike | None = None, minus_one_ms_hack: bool = True) -> Path:
        """
        Outputs the chapters to an OGM file

        :param out:                 Can be either a directory or a full file path
        :param minus_one_ms_hack:   If True, every chapter will be shifted by -1ms to avoid issues with some players
        """
        if not out:
            out = get_workdir()
        out = ensure_path(out, self)
        if out.is_dir():
            out_file = out / "chapters.txt"
        else:
            out_file = out
        with open(out_file, "w", encoding="UTF-8") as f:
            chapters = [
                "CHAPTER{num:02d}={time}\nCHAPTER{num:02d}NAME={name}\n".format(
                    num=i + 1,
                    time=format_timedelta(
                        (chapter[0] - timedelta(milliseconds=1)) if minus_one_ms_hack and chapter[0] > timedelta(milliseconds=0) else chapter[0]
                    ),
                    name=chapter[1],
                )
                for i, chapter in enumerate(sorted(self.chapters, key=lambda x: x[0]))
            ]
            f.writelines(chapters)
        return out_file

    @staticmethod
    def from_sub(
        file: PathLike | SubFile,
        timesource: TimeSourceT = None,
        timescale: TimeScaleT = None,
        use_actor_field: bool = False,
        markers: str | list[str] = ["chapter", "chptr"],
        _print: bool = True,
        encoding: str = "utf_8_sig",
    ) -> "Chapters":
        """
        Extract chapters from an ass file or a SubFile.

        :param file:            Input ass file or SubFile
        :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
        :param use_actor_field: Uses the actor field instead of the effect field for identification.
        :param markers:         Markers to check for.
        :param _print:          Prints the chapters after parsing
        :param encoding:        Encoding used to read the ass file if need be
        """
        from ass import parse_file, Comment  # type: ignore[import-untyped]

        caller = "Chapters.from_sub"

        if isinstance(markers, str):
            markers = [markers]

        if isinstance(file, SubFile):
            doc = file._read_doc()
        else:
            file = ensure_path_exists(file, caller)
            with open(file if not file else file, "r", encoding=encoding) as reader:
                doc = parse_file(reader)

        pattern = re.compile(r"\{([^\\=].+?)\}")
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
                    warn(f"Chapter {(len(chapters) + 1):02.0f} does not have a name!", caller)
                    chapters.append((line.start, ""))

        if not chapters:
            warn("Could not find any chapters in subtitle!", caller)

        if timesource is None and (setup_timesource := get_setup_attr("sub_timesource", None)) is not None:
            if not isinstance(setup_timesource, TimeSourceT):
                raise error("Invalid timesource type in Setup!", caller)
            debug("Using default timesource from setup.", caller)
            timesource = setup_timesource

        if timescale is None and (setup_timescale := get_setup_attr("sub_timescale", None)) is not None:
            if not isinstance(setup_timescale, TimeScaleT):
                raise error("Invalid timescale type in Setup!", caller)
            debug("Using default timescale from setup.", caller)
            timescale = setup_timescale

        ch = Chapters(chapters, timesource, timescale)  # type: ignore
        if _print and chapters:
            ch.print()
        return ch

    @staticmethod
    def from_mkv(file: PathLike, timesource: TimeSourceT = None, timescale: TimeScaleT = None, _print: bool = True, quiet: bool = True) -> "Chapters":
        """
        Extract chapters from mkv.

        :param file:            Input mkv file
        :param timesource:      The source of timestamps/timecodes. For details check the docstring on the type.
        :param timescale:       Unit of time (in seconds) in terms of which frame timestamps are represented.\n
                                For details check the docstring on the type.
        :param _print:          Prints the chapters after parsing
        """
        caller = "Chapters.from_mkv"
        file = ensure_path_exists(file, caller)

        mkvextract = get_executable("mkvextract")
        out = Path(get_temp_workdir(), f"{file.stem}_chapters.txt")
        args = [mkvextract, str(file), "chapters", "-s", str(out)]
        if run_commandline(args, quiet):
            raise error("Failed to extract chapters!", caller)

        if timesource is None:
            chapters = Chapters(out, file, _print=_print)
        else:
            chapters = Chapters(out, timesource, timescale, _print)

        clean_temp_files()
        return chapters


ChaptersSelf = TypeVar("ChaptersSelf", bound=Chapters)
