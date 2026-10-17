from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Generator, Sequence

from mkvinfo import MKVInfo, Attachment as MKVAttachment

from ..muxing.tracks import Attachment, AudioTrack, SubTrack, VideoTrack
from ..utils.download import get_executable
from ..utils.env import get_workdir, run_commandline
from ..utils.files import ensure_path, make_output, uniquify_path
from ..utils.log import error
from ..utils.probe import ParsedFile
from ..utils.types import PathLike, TrackType

__all__ = ["MKVExtract"]


class MKVExtract:
    """
    A helper for mkvextract to extract tracks and attachments without conversion.
    """

    _VIDEO_EXTENSIONS: ClassVar[dict[str, str]] = {
        "v_av1": "ivf",
        "v_mpeg1": "m1v",
        "v_mpeg4/iso/avc": "h264",
        "v_mpeg4/iso/asp": "avi",
        "v_mpeg4/iso/ap": "avi",
        "v_mpeg4/iso/hevc": "h265",
        "v_mpeg4/iso/sp": "avi",
        "v_mpeg2": "m2v",
        "v_mpegh/iso/hevc": "h265",
        "v_ms/vfw/fourcc": "avi",
        "v_theora": "ogv",
        "v_vp8": "ivf",
        "v_vp9": "ivf",
    }
    _SUB_EXTENSIONS: ClassVar[dict[str, str]] = {
        "s_ass": "ass",
        "s_hdmv/pgs": "sup",
        "s_ssa": "ssa",
        "s_text/ascii": "srt",
        "s_text/ass": "ass",
        "s_text/ssa": "ssa",
        "s_text/usf": "usf",
        "s_text/utf8": "srt",
        "s_text/webvtt": "vtt",
        "s_vobsub": "idx",
    }

    def __init__(self, fileIn: PathLike, output: PathLike = None) -> None:
        """
        Creates the mkvextract helper for a Matroska or WebM file.

        :param fileIn:              File to extract from.
        :param output:              Default output directory. `None` uses `get_workdir()`.\n
                                    The directory will be created if it does not exist.
        """
        self._parsed = ParsedFile.from_file(fileIn, self, _allow_unknown_codecs=True)
        self._fileIn = self._parsed.source
        self.output = ensure_path(get_workdir() if output is None else output, self)
        if self.output.exists() and not self.output.is_dir():
            raise ValueError(f"Extraction output '{self.output}' is not a directory.")
        self.output.mkdir(parents=True, exist_ok=True)
        try:
            self._info = self._parsed.raw_mkvmerge or MKVInfo.from_file(self._fileIn, mkvmerge=get_executable("mkvmerge"))
        except Exception as exc:
            raise error(f"Could not parse '{self._fileIn.name}' as Matroska/WebM.", self) from exc
        container = self._info.container
        if not container.recognized or not container.supported or (container.type or "").casefold() not in {"matroska", "webm"}:
            raise ValueError(f"'{self._fileIn.name}' is not a supported Matroska/WebM file.")

        self._executable = get_executable("mkvextract")

    @contextmanager
    def _extract(self, args: list[str], paths: list[Path], quiet: bool) -> Generator[None, None, None]:
        if any(path.resolve() == self._fileIn for path in paths):
            raise ValueError("Extraction output cannot overwrite the source file.")
        existing = {path for path in paths if path.exists()}
        try:
            code = run_commandline([self._executable, str(self._fileIn), *args], quiet, mkvmerge=True)
            if code not in (0, 1) or any(not path.is_file() for path in paths):
                raise error(f"Failed to extract from '{self._fileIn.name}'.", self)
            yield
        except Exception:
            for path in paths:
                if path not in existing:
                    path.unlink(missing_ok=True)
            raise

    def _extract_track[T: VideoTrack | AudioTrack | SubTrack](
        self, track_class: type[T], track_type: TrackType, track: int, output: PathLike, quiet: bool, **kwargs: Any
    ) -> T:
        parsed = self._parsed.find_tracks(type=track_type, relative_id=track, error_if_empty=True, caller=self)[0]
        if parsed.raw_mkvmerge is None:
            media = [item for item in self._parsed.tracks if item.type in (TrackType.VIDEO, TrackType.AUDIO, TrackType.SUB)]
            if len(media) != len(self._info.tracks):
                raise error(f"Could not match track metadata in '{self._fileIn.name}'.", self)
            parsed.raw_mkvmerge = self._info.tracks[media.index(parsed)]
        identified = parsed.raw_mkvmerge
        properties = identified.properties
        if track_type == TrackType.AUDIO:
            audio_format = parsed.get_audio_format()
            extension = audio_format.extension if audio_format else None
        else:
            formats = self._VIDEO_EXTENSIONS if track_type == TrackType.VIDEO else self._SUB_EXTENSIONS
            extension = formats.get((properties.codec_id or "").casefold())
        if extension is None:
            raise ValueError(f"Unsupported {track_type.name.lower()} format '{identified.codec}'.")

        target = ensure_path(self.output if output is None else output, self)
        companions = (".sub",) if extension == "idx" else ()
        if target.is_dir():
            target = Path(uniquify_path(target / f"{self._fileIn.stem}_{identified.id}.{extension}", companion_extensions=companions))
        media = make_output(self._fileIn, extension, user_passed=target)
        media.parent.mkdir(parents=True, exist_ok=True)
        paths = [media, *[media.with_suffix(ext) for ext in companions]]
        args = ["tracks", f"{identified.id}:{media}"]

        # Codec priming stays in extracted audio; subtracting it again shifts remuxed audio early.
        delay = max(properties.minimum_timestamp or 0, 0) // 1_000_000 if track_type == TrackType.AUDIO else 0
        options = {
            "name": properties.track_name if properties.track_name is not None else (parsed.title or ""),
            "lang": parsed.sanitized_lang.to_tag(),
            "default": properties.default_track if properties.default_track is not None else parsed.is_default,
            "forced": properties.forced_track if properties.forced_track is not None else parsed.is_forced,
            "tags": dict(parsed.other_tags),
            "delay": delay,
        } | kwargs
        if track_type == TrackType.VIDEO and options.get("timecode_file") is None:
            timestamps = Path(uniquify_path(media.with_suffix(".txt")))
            options["timecode_file"] = timestamps
            paths.append(timestamps)
            args.extend(["timestamps_v2", f"{identified.id}:{timestamps}"])
        with self._extract(args, paths, quiet):
            return track_class(media, **options)

    def video_track(self, track: int = 0, output: PathLike = None, quiet: bool = True, **kwargs: Any) -> VideoTrack:
        """
        Extract a video track from the file.

        The track name, language, default/forced flags and custom tags are inherited unless overridden.\n
        Timestamps are extracted automatically to preserve variable frame rate and container timing.

        :param track:               Relative video track number, starting at 0.
        :param output:              Custom output. Can be an existing directory or a file.\n
                                    `None` uses the default output directory of the helper.\n
                                    The file extension will be set automatically.

        :param quiet:               Suppresses the output.\n
                                    The stdout will still be printed on failure regardless of this setting.

        :param kwargs:              Any other parameters to pass to `VideoTrack`. These override inherited metadata.\n
                                    Pass `timecode_file` to use existing timestamps instead of extracting them.\n
                                    `delay` adds a shift in ms to the timestamped video.

        :return:                    The extracted video as a `VideoTrack`.
        """
        return self._extract_track(VideoTrack, TrackType.VIDEO, track, output, quiet, **kwargs)

    def audio_track(self, track: int = 0, output: PathLike = None, quiet: bool = True, **kwargs: Any) -> AudioTrack:
        """
        Extract an audio track from the file without conversion.

        The track name, language, default/forced flags and custom tags are inherited unless overridden.\n
        The format has to be supported by `AudioFormat`. Existing container timing is preserved.

        :param track:               Relative audio track number, starting at 0.
        :param output:              Custom output. Can be an existing directory or a file.\n
                                    `None` uses the default output directory of the helper.\n
                                    The file extension will be set automatically.

        :param quiet:               Suppresses the output.\n
                                    The stdout will still be printed on failure regardless of this setting.

        :param kwargs:              Any other parameters to pass to `AudioTrack`. These override inherited metadata.\n
                                    `delay` replaces the preserved source offset in ms.

        :return:                    The extracted audio as an `AudioTrack`.
        """
        return self._extract_track(AudioTrack, TrackType.AUDIO, track, output, quiet, **kwargs)

    def sub_track(self, track: int = 0, output: PathLike = None, quiet: bool = True, **kwargs: Any) -> SubTrack:
        """
        Extract a subtitle track from the file without conversion. SRT will stay SRT.

        The track name, language, default/forced flags and custom tags are inherited unless overridden.\n
        Existing subtitle timing is preserved. VobSub returns an `.idx` file with its `.sub` companion.

        :param track:               Relative subtitle track number, starting at 0.
        :param output:              Custom output. Can be an existing directory or a file.\n
                                    `None` uses the default output directory of the helper.\n
                                    The file extension will be set automatically.

        :param quiet:               Suppresses the output.\n
                                    The stdout will still be printed on failure regardless of this setting.

        :param kwargs:              Any other parameters to pass to `SubTrack`. These override inherited metadata.\n
                                    `delay` adds a shift in ms to the extracted subtitles.

        :return:                    The extracted subtitle as a `SubTrack`.
        """
        return self._extract_track(SubTrack, TrackType.SUB, track, output, quiet, **kwargs)

    def _attachment_output(self, item: MKVAttachment, output: PathLike, reserved: Sequence[PathLike] = ()) -> Path:
        target = ensure_path(self.output if output is None else output, self)
        if target.is_dir():
            name = item.file_name.replace("\\", "/").rsplit("/", 1)[-1]
            name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name).rstrip(" .") or f"attachment_{item.id}"
            if re.match(r"^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", name, re.I):
                name = f"_{name}"
            target = Path(uniquify_path(target / name, reserved=reserved))
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def attachment(
        self, track: int = 0, output: PathLike = None, quiet: bool = True, *, name: str | None = None, mimetype: str | None = None
    ) -> Attachment:
        """
        Extract an attachment from the file.

        The original attachment name and MIME type are inherited unless overridden.

        :param track:               Relative attachment number, starting at 0.
        :param output:              Custom output. Can be an existing directory or a file.\n
                                    `None` uses the default output directory of the helper.\n
                                    Generated filenames are based on the original attachment name.

        :param quiet:               Suppresses the output.\n
                                    The stdout will still be printed on failure regardless of this setting.

        :param name:                Name of the attachment when muxing. `None` keeps the original name.
        :param mimetype:            MIME type of the returned attachment. `None` keeps the original MIME type.
        :return:                    The extracted attachment as an `Attachment`.
        """
        if track < 0 or track >= len(self._info.attachments):
            raise ValueError(f"Could not find attachment {track} in '{self._fileIn.name}'.")
        item = self._info.attachments[track]
        path = self._attachment_output(item, output)
        with self._extract(["attachments", f"{item.id}:{path}"], [path], quiet):
            return Attachment(
                path, mimetype=(item.content_type or "") if mimetype is None else mimetype, name=item.file_name if name is None else name
            )

    def attachments(self, output: PathLike = None, quiet: bool = True) -> list[Attachment]:
        """
        Extract all attachments from the file in one pass.

        Original attachment names and MIME types are preserved.

        :param output:              Output directory. `None` uses the default output directory of the helper.\n
                                    The directory will be created if it does not exist.

        :param quiet:               Suppresses the output.\n
                                    The stdout will still be printed on failure regardless of this setting.

        :return:                    A list of `Attachment` objects in source order.\n
                                    An empty list is returned if the file has no attachments.
        """
        target = ensure_path(self.output if output is None else output, self)
        if target.exists() and not target.is_dir():
            raise ValueError("The output for attachments must be a directory.")
        target.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for item in self._info.attachments:
            paths.append(self._attachment_output(item, target, reserved=paths))
        if not paths:
            return []
        args = ["attachments", *[f"{item.id}:{path}" for item, path in zip(self._info.attachments, paths)]]
        with self._extract(args, paths, quiet):
            return [Attachment(path, mimetype=item.content_type or "", name=item.file_name) for item, path in zip(self._info.attachments, paths)]
