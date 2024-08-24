from pathlib import Path
from shlex import split as split_args

from ..utils.files import make_output, create_tags_xml
from ..utils.glob import GlobSearch
from ..utils.types import PathLike, TrackType
from ..utils.files import ensure_path_exists, get_absolute_tracknum

# fmt: off
__all__ = [
    "VideoTrack", "AudioTrack", "SubTrack",
    "VT", "AT", "ST",
    "Attachment", "Premux", "MkvTrack"
]


# fmt: on


class _track:
    file: Path
    type: TrackType
    default: bool
    forced: bool
    name: str
    lang: str
    delay: int
    args: list[str] | None
    tags: dict[str, str] | None

    def __init__(
        self,
        file: PathLike,
        type: str | int | TrackType,
        name: str = "",
        lang: str = "",
        default: bool = True,
        forced: bool = False,
        delay: int = 0,
        args: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        from .muxfiles import MuxingFile

        """
        :param file:        Filepath as string or Path object
        :param type:        TrackType enum, or int or string (1 = 'video', 2 = 'audio', 3 = 'sub')
        :param name:        The track name in the resulting mkv file
        :param lang:        The language tag for the track
        :param default:     Default flag
        :param forced:      Forced flag
        :param delay:       Container delay of track in ms
        """
        self.file = ensure_path_exists(file, self)
        self.default = default
        self.forced = forced
        self.name = name
        self.delay = file.container_delay if isinstance(file, MuxingFile) else delay
        self.lang = lang
        self.type = type if isinstance(type, TrackType) else (TrackType(type) if isinstance(type, int) else TrackType[type.upper()])
        self.args = args
        self.tags = tags

    def mkvmerge_args(self) -> list[str]:
        filepath = str(self.file.resolve())
        if self.type == TrackType.ATTACHMENT:
            is_font = self.file.suffix.lower() in [".ttf", ".otf", ".ttc", ".otc"]
            if not is_font and not self.lang:
                raise ValueError("Please specify a mimetype for the attachments if they're not fonts!")
            if not is_font:
                args = ["--attachment-mime-type", self.lang]
            else:
                args = ["--attachment-mime-type", "application/x-truetype-font"]
            if self.name:
                args.extend(["--attachment-name", self.name])

            args.extend(["--attach-file", filepath])
            return args

        elif self.type == TrackType.MKV:
            return [*self.args, filepath]
        elif self.type == TrackType.CHAPTERS:
            return ["--chapters", filepath]

        args = ["--no-global-tags", "--track-name", f"0:{self.name}"]

        if self.tags and not all([not bool(v) for _, v in self.tags.items()]):
            tags_file = make_output(self.file, "xml", "_tags", temp=True)
            create_tags_xml(tags_file, self.tags)
            args.extend(["--tags", f"0:{str(tags_file)}"])

        if self.lang:
            args.extend(["--language", f"0:{self.lang}"])
        if self.delay:
            args.extend(["--sync", f"0:{self.delay}"])
        args.extend(
            [
                "--default-track-flag",
                f"0:{'yes' if self.default else 'no'}",
                "--forced-display-flag",
                f"0:{'yes' if self.forced else 'no'}",
            ]
        )
        if self.args:
            args.extend(self.args)
        args.append(filepath)
        return args


class VideoTrack(_track):
    """
    _track object with VIDEO type preselected and japanese language default

    :param timecode_file:       Pass a path for proper vfr playback if needed.
    :param crop:                Container based cropping with (horizontal, vertical) or (left, top, right, bottom).
                                Will crop the same on all sides if passed a single integer.
    """

    def __init__(
        self,
        file: PathLike | GlobSearch,
        name: str = "",
        lang: str = "ja",
        default: bool = True,
        forced: bool = False,
        delay: int = 0,
        timecode_file: PathLike | GlobSearch | None = None,
        crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None,
        args: list[str] = [],
        tags: dict[str, str] | None = None,
    ) -> None:
        if timecode_file is not None:
            args.extend(["--timestamps", f"0:{ensure_path_exists(timecode_file, self).resolve()}"])
        if crop:
            if isinstance(crop, int):
                crop = tuple([crop] * 4)
            elif len(crop) == 2:
                crop = crop * 2
            args.extend(["--cropping", f"0:{crop[0]},{crop[1]},{crop[2]},{crop[3]}"])
        super().__init__(file, TrackType.VIDEO, name, lang, default, forced, delay, args, tags)


class AudioTrack(_track):
    """
    _track object with AUDIO type preselected and japanese language default
    """

    def __init__(
        self,
        file: PathLike | GlobSearch,
        name: str = "",
        lang: str = "ja",
        default: bool = True,
        forced: bool = False,
        delay: int = 0,
        args: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        super().__init__(file, TrackType.AUDIO, name, lang, default, forced, delay, args, tags)


class Attachment(_track):
    """
    pseudo _track object for attachments
    """

    def __init__(self, file: str | Path, mimetype: str = "", name: str = "") -> None:
        super().__init__(file, TrackType.ATTACHMENT, lang=mimetype, name=name)


class SubTrack(_track):
    """
    _track object with SUB type preselected and english language default

    Supports merging multiple files by passing a List of Path objects or filepath strings
    and of course also a GlobSearch
    """

    def __init__(
        self,
        file: PathLike | GlobSearch,
        name: str = "",
        lang: str = "en",
        default: bool = True,
        forced: bool = False,
        delay: int = 0,
        args: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        super().__init__(file, TrackType.SUB, name, lang, default, forced, delay, args, tags)


class Premux(_track):
    def __init__(
        self,
        file: PathLike | GlobSearch,
        video: int | list[int] | None = -1,
        audio: int | list[int] | None = -1,
        subtitles: int | list[int] | None = -1,
        keep_attachments: bool = True,
        mkvmerge_args: str | list[str] = "--no-global-tags",
        assume_absolute: bool = False,
    ) -> None:
        """
        Custom Track object to arbitrarily grab tracks from an existing file.

        For all track params:
        `None` means there won't be any chosen and `-1` means all will be chosen.
        You can also specify a single or multiple *relative* track numbers to choose any.

        :param video:               Video Track(s) to choose
        :param audio:               Audio Track(s) to choose
        :param subtitles:           Subtitle Track(s) to choose
        :param keep_attachments:    Whether to keep attachments from the file. Fonts for example.
        :param mkvmerge_args:       Any other args you may want to pass.
        :param assume_absolute:     Assume that the track numbers passed were already absolute to begin with.
                                    If False it will simply get absolute numbers derived from the relative ones.
        """
        args = ""
        if video is None:
            args += " -D"
        elif video != -1:
            if isinstance(video, list):
                lv = []
                for num in video:
                    abso = get_absolute_tracknum(file, num, TrackType.VIDEO) if not assume_absolute else num
                    lv.append(abso)
                args += f" -d {','.join(str(i) for i in lv)}"
            else:
                abso = get_absolute_tracknum(file, video, TrackType.VIDEO) if not assume_absolute else video
                args += f" -d {abso}"

        if audio is None:
            args += " -A"
        elif audio != -1:
            if isinstance(audio, list):
                la = []
                for num in audio:
                    abso = get_absolute_tracknum(file, num, TrackType.AUDIO) if not assume_absolute else num
                    la.append(abso)
                args += f" -a {','.join(str(i) for i in la)}"
            else:
                abso = get_absolute_tracknum(file, audio, TrackType.AUDIO) if not assume_absolute else audio
                args += f" -a {abso}"

        if subtitles is None:
            args += " -S"
        elif subtitles != -1:
            if isinstance(subtitles, list):
                ls = []
                for num in subtitles:
                    abso = get_absolute_tracknum(file, num, TrackType.SUB) if not assume_absolute else num
                    ls.append(abso)
                args += f" -s {','.join(str(i) for i in ls)}"
            else:
                abso = get_absolute_tracknum(file, subtitles, TrackType.SUB) if not assume_absolute else subtitles
                args += f" -s {abso}"

        if not keep_attachments:
            args += " -M"

        args = split_args(args.strip())
        mkvmerge_args = split_args(mkvmerge_args.strip()) if isinstance(mkvmerge_args, str) else mkvmerge_args
        super().__init__(file, TrackType.MKV, args=args + mkvmerge_args)


VT = VideoTrack
AT = AudioTrack
ST = SubTrack
MkvTrack = Premux
