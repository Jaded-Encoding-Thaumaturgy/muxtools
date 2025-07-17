from pathlib import Path
from typing_extensions import Self

from ..misc import Chapters
from ..utils import PathLike, ensure_path_exists, make_output, ensure_path, get_executable, run_commandline, clean_temp_files
from ..utils.files import create_tags_xml
from ..utils.log import error

__all__ = ["MKVPropEdit"]


class MKVPropEdit:
    _main_args: list[str]
    _track_args: list[str]
    _fileIn: Path
    _has_info: bool = False
    _video_index: int = 1
    _audio_index: int = 1
    _subtitle_index: int = 1
    _executable: Path

    def __init__(
        self, fileIn: PathLike, track_statistics: bool | None = None, chapters: PathLike | Chapters = None, tags: dict[str, str] | None = None
    ):
        """
        Creates the mkvpropedit helper including any modifications possible on the global scope.

        :param fileIn:              File to edit.
        :param track_statistics:    Whether to update or remove track statistics like bitrate.\n
                                    `None` will do nothing while `True` will add/replace them and `False` will remove them.

        :param chapters:            Chapters to add to the file. This can be any txt or xml file in the same formats that mkvmerge takes.\n
                                    It can also take a muxtools Chapters object and create a txt from that.\n
                                    An empty string will remove any chapters. `None` will do nothing.

        :param tags:                Global tags to add. This will replace all custom tags set before.\n
                                    An empty dict will remove any global tags. `None` will do nothing.
        """
        self._executable = ensure_path(get_executable("mkvpropedit"), self)
        self._fileIn = ensure_path_exists(fileIn, self)
        self._main_args = []
        self._track_args = []

        if track_statistics is not None:
            self._main_args.append("--add-track-statistics-tags" if track_statistics else "--delete-track-statistics-tags")

        if chapters is not None:
            if isinstance(chapters, str) and not chapters:
                self._main_args.extend(["-c", ""])
            else:
                if isinstance(chapters, Chapters):
                    chapters = chapters.to_file()
                chapters = ensure_path_exists(chapters, self)
                if chapters.suffix.lower() not in [".txt", ".xml"]:
                    raise error("Chapters have to be a txt or xml file.", self)
                self._main_args.extend(["-c", str(chapters)])
        if tags is not None:
            out = ""
            if len(tags) > 0:
                out = make_output(fileIn, "xml", "global_tags", temp=True)
                create_tags_xml(out, tags)
            self._main_args.extend(["-t", f"global:{str(out)}"])

    def _edit_args(self, name: str, value: bool | str | None) -> list[str]:
        if value is None:
            return []

        if isinstance(value, bool):
            return ["-s", f"{name}={str(int(value))}"]
        else:
            if not value:
                return ["-d", name]
            else:
                return ["-s", f"{name}={value}"]

    def _edit_track(
        self,
        type: str,
        index: int,
        title: str | None,
        language: str | None,
        default: bool | None,
        forced: bool | None,
        tags: dict[str, str] | None,
        **kwargs: bool | str | None,
    ):
        selector = type if index <= 0 else f"track:{type}{index}"
        if tags is not None:
            out = ""
            if len(tags) > 0:
                out = make_output(self._fileIn, "xml", f"{type}{index}_tags", temp=True)
                create_tags_xml(out, tags)
            self._main_args.extend(["-t", f"{selector}:{str(out)}"])
        if not any([not_none for not_none in (title, language, default, forced) if not_none is not None]) and not kwargs:
            return

        args = ["-e", selector]
        to_append = [
            *self._edit_args("title" if type == "info" else "name", title),
            *self._edit_args("language", language),
            *self._edit_args("flag-default", default),
            *self._edit_args("flag-forced", forced),
        ]
        args.extend(to_append)

        for k, v in kwargs.items():
            if not k.endswith("_"):
                k = k[:-1].replace("_", "-")
            if e_args := self._edit_args(k, v):
                args.extend(e_args)

        self._track_args.extend(args)

    def info(
        self,
        title: str | None = None,
        date: str | None = None,
        muxing_application: str | None = None,
        writing_application: str | None = None,
        **kwargs: bool | str | None,
    ):
        """
        Edit properties for the main info section.

        `None` always means the property will be left untouched while an empty string will remove the property outright.\n
        Bool values are converted to their respective integer to be passed on to mkvpropedit.

        :param title:               The title for the whole movie
        :param date:                The date the file was created
        :param muxing_application:  The name of the application or library used for multiplexing the file
        :param writing_application: The name of the application or library used for writing the file
        :param kwargs:              Any other properties to set or remove.\n
                                    Check out the 'Segment information' section in `mkvpropedit -l` to see what's available.
        """
        if self._has_info:
            raise error("Info tagging was already added!", self)
        self._edit_track("info", -1, title, date=date, muxing_application=muxing_application, writing_application=writing_application, **kwargs)
        self._has_info = True
        return self

    def video_track(
        self,
        name: str | None = None,
        language: str | None = None,
        default: bool | None = None,
        forced: bool | None = None,
        tags: dict[str, str] | None = None,
        **kwargs: bool | str | None,
    ) -> Self:
        """
        Edit properties for the next video track in the file.

        `None` always means the property will be left untouched while an empty string will remove the property outright.\n
        Bool values are converted to their respective integer to be passed on to mkvpropedit.

        :param name:                A human-readable track name
        :param language:            Specifies the language of the track
        :param default:             Specifies whether a track should be eligible for automatic selection
        :param forced:              Specifies whether a track should be played with tracks of a different type but same language

        :param tags:                Any custom/arbitrary tags to set for the track.\n
                                    Do note that this will replace all custom tags the track may already have.\n
                                    An empty dict will remove any custom tags. `None` will do nothing.

        :param kwargs:              Any other properties to set or remove.\n
                                    Check out the 'Track headers' section in `mkvpropedit -l` to see what's available.
        """
        self._edit_track("v", self._video_index, name, language, default, forced, tags, **kwargs)
        self._video_index += 1
        return self

    def audio_track(
        self,
        name: str | None = None,
        language: str | None = None,
        default: bool | None = None,
        forced: bool | None = None,
        tags: dict[str, str] | None = None,
        **kwargs: bool | str | None,
    ) -> Self:
        """
        Edit properties for the next audio track in the file.

        `None` always means the property will be left untouched while an empty string will remove the property outright.\n
        Bool values are converted to their respective integer to be passed on to mkvpropedit.

        :param name:                A human-readable track name
        :param language:            Specifies the language of the track
        :param default:             Specifies whether a track should be eligible for automatic selection
        :param forced:              Specifies whether a track should be played with tracks of a different type but same language

        :param tags:                Any custom/arbitrary tags to set for the track.\n
                                    Do note that this will replace all custom tags the track may already have.\n
                                    An empty dict will remove any custom tags. `None` will do nothing.

        :param kwargs:              Any other properties to set or remove.\n
                                    Check out the 'Track headers' section in `mkvpropedit -l` to see what's available.
        """
        self._edit_track("a", self._audio_index, name, language, default, forced, tags, **kwargs)
        self._audio_index += 1
        return self

    def sub_track(
        self,
        name: str | None = None,
        language: str | None = None,
        default: bool | None = None,
        forced: bool | None = None,
        tags: dict[str, str] | None = None,
        **kwargs: bool | str | None,
    ) -> Self:
        """
        Edit properties for the next subtitle track in the file.

        `None` always means the property will be left untouched while an empty string will remove the property outright.\n
        Bool values are converted to their respective integer to be passed on to mkvpropedit.

        :param name:                A human-readable track name
        :param language:            Specifies the language of the track
        :param default:             Specifies whether a track should be eligible for automatic selection
        :param forced:              Specifies whether a track should be played with tracks of a different type but same language

        :param tags:                Any custom/arbitrary tags to set for the track.\n
                                    Do note that this will replace all custom tags the track may already have.\n
                                    An empty dict will remove any custom tags. `None` will do nothing.

        :param kwargs:              Any other properties to set or remove.\n
                                    Check out the 'Track headers' section in `mkvpropedit -l` to see what's available.
        """
        self._edit_track("s", self._subtitle_index, name, language, default, forced, tags, **kwargs)
        self._subtitle_index += 1
        return self

    def run(self, quiet: bool = True, error_on_failure: bool = True) -> bool:
        """
        Run the mkvpropedit process.

        :param quiet:               Supresses the output.\n
                                    The stdout will still be printed on failure regardless of this setting.

        :param error_on_failure:    Raise an exception on failure.\n
                                    Otherwise this function will return a bool indicating the success.
        """
        args = [str(self._executable), str(self._fileIn)] + self._main_args + self._track_args
        code = run_commandline(args, quiet, mkvmerge=True)
        clean_temp_files()
        if code > 1 and error_on_failure:
            raise error(f"Failed to edit properties for '{self._fileIn.name}'!")

        return code < 2
