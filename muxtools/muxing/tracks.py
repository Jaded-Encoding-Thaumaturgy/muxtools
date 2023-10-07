from pathlib import Path

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

    def __init__(
        self, file: PathLike, type: str | int | TrackType, name: str = "", lang: str = "", default: bool = True, forced: bool = False, delay: int = 0
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

    def mkvmerge_args(self) -> str:
        self.file = self.file if isinstance(self.file, Path) else Path(self.file)
        if self.type == TrackType.ATTACHMENT:
            is_font = self.file.suffix.lower() in [".ttf", ".otf"]
            if not is_font and not self.lang:
                raise ValueError(f"Please specify a mimetype for the attachments if they're not fonts!")
            if not is_font:
                return f' --attachment-mime-type {self.lang} --attach-file "{self.file.resolve()}"'
            else:
                return f' --attachment-mime-type {"font/ttf" if self.file.suffix.lower() == ".ttf" else "font/otf"} --attach-file "{self.file.resolve()}"'
        elif self.type == TrackType.MKV:
            return f' {self.name.strip()} "{self.file.resolve()}"'
        elif self.type == TrackType.CHAPTERS:
            return f' --chapters "{self.file.resolve()}"'
        name_args = f' --track-name 0:"{self.name}"' if self.name else ""
        lang_args = f" --language 0:{self.lang}" if self.lang else ""
        delay_args = f" --sync 0:{self.delay}" if self.delay else ""
        default_args = f' --default-track-flag 0:{"yes" if self.default else "no"}'
        forced_args = f' --forced-display-flag 0:{"yes" if self.forced else "no"}'
        timecode_args = ""
        if isinstance(self, VideoTrack) and self.timecode_file is not None:
            timecode_args = f' --timestamps 0:"{self.timecode_file.resolve()}"'
        return f'{timecode_args}{name_args}{lang_args}{default_args}{forced_args}{delay_args} "{self.file.resolve()}"'


class VideoTrack(_track):
    """
    _track object with VIDEO type preselected and japanese language default
    """

    timecode_file: PathLike | None = None

    def __init__(
        self,
        file: PathLike | GlobSearch,
        name: str = "",
        lang: str = "ja",
        default: bool = True,
        forced: bool = False,
        delay: int = 0,
        timecode_file: PathLike | GlobSearch = None,
    ) -> None:
        if timecode_file is not None:
            self.timecode_file = ensure_path_exists(timecode_file, self)
        super().__init__(file, TrackType.VIDEO, name, lang, default, forced, delay)


class AudioTrack(_track):
    """
    _track object with AUDIO type preselected and japanese language default
    """

    def __init__(
        self, file: PathLike | GlobSearch, name: str = "", lang: str = "ja", default: bool = True, forced: bool = False, delay: int = 0
    ) -> None:
        super().__init__(file, TrackType.AUDIO, name, lang, default, forced, delay)


class Attachment(_track):
    """
    pseudo _track object for attachments
    """

    def __init__(self, file: str | Path, mimetype: str = "") -> None:
        super().__init__(file, TrackType.ATTACHMENT, "", mimetype, False, False, 0)


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
    ) -> None:
        super().__init__(file, TrackType.SUB, name, lang, default, forced, delay)


class Premux(_track):
    def __init__(
        self,
        file: PathLike | GlobSearch,
        video: int | list[int] | None = -1,
        audio: int | list[int] | None = -1,
        subtitles: int | list[int] | None = -1,
        keep_attachments: bool = True,
        mkvmerge_args: str = "--no-global-tags",
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
        """
        args = ""
        if video is None:
            args += " -D"
        elif video != -1:
            if isinstance(video, list):
                lv = []
                for num in video:
                    abso = get_absolute_tracknum(file, num, TrackType.VIDEO)
                    lv.append(abso)
                args += f" -d {','.join(str(i) for i in lv)}"
            else:
                abso = get_absolute_tracknum(file, video, TrackType.VIDEO)
                args += f" -d {abso}"

        if audio is None:
            args += " -A"
        elif audio != -1:
            if isinstance(audio, list):
                la = []
                for num in audio:
                    abso = get_absolute_tracknum(file, num, TrackType.AUDIO)
                    la.append(abso)
                args += f" -a {','.join(str(i) for i in la)}"
            else:
                abso = get_absolute_tracknum(file, audio, TrackType.AUDIO)
                args += f" -a {abso}"

        if subtitles is None:
            args += " -S"
        elif subtitles != -1:
            if isinstance(subtitles, list):
                ls = []
                for num in subtitles:
                    abso = get_absolute_tracknum(file, num, TrackType.SUB)
                    ls.append(abso)
                args += f" -s {','.join(str(i) for i in ls)}"
            else:
                abso = get_absolute_tracknum(file, subtitles, TrackType.SUB)
                args += f" -s {abso}"

        if not keep_attachments:
            args += " -M"

        args = f" {args.strip()} {mkvmerge_args.strip()}"
        super().__init__(file, TrackType.MKV, args, "", False, False, 0)


VT = VideoTrack
AT = AudioTrack
ST = SubTrack
MkvTrack = Premux
