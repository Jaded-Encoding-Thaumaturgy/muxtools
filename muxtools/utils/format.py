from pymediainfo import MediaInfo, Track
from .types import TrackType, PathLike
from .files import ensure_path_exists
from .log import error


def get_absolute_track(file: PathLike, track: int, type: TrackType) -> Track:
    """
    Finds the absolute track for a relative track number of a specific type.

    :param file:    String or pathlib based Path
    :param track:   Relative track number
    :param type:    TrackType of the requested relative track
    """
    file = ensure_path_exists(file, get_absolute_track)
    mediainfo = MediaInfo.parse(file)

    current = 0
    # Weird mediainfo quirks
    for t in mediainfo.tracks:
        if t.track_type.lower() not in ["video", "audio", "text"]:
            continue
        t.track_id = current
        current += 1

    videos = mediainfo.video_tracks
    audios = mediainfo.audio_tracks
    subtitles = mediainfo.text_tracks
    match type:
        case TrackType.VIDEO:
            if not videos:
                raise error(f"No video tracks have been found in '{file.name}'!", get_absolute_track)
            try:
                return videos[track]
            except:
                raise error("Your requested track doesn't exist.", get_absolute_track)
        case TrackType.AUDIO:
            if not audios:
                raise error(f"No audio tracks have been found in '{file.name}'!", get_absolute_track)
            try:
                return audios[track]
            except:
                raise error("Your requested track doesn't exist.", get_absolute_track)
        case TrackType.SUB:
            if not subtitles:
                raise error(f"No subtitle tracks have been found in '{file.name}'!", get_absolute_track)
            try:
                return subtitles[track]
            except:
                raise error("Your requested track doesn't exist.", get_absolute_track)
        case _:
            raise error("Not implemented for anything other than Video, Audio or Subtitles.", get_absolute_track)


def get_absolute_tracknum(file: PathLike, track: int, type: TrackType) -> int:
    """
    Finds the absolute track number for a relative track number of a specific type.

    :param file:    String or pathlib based Path
    :param track:   Relative track number
    :param type:    TrackType of the requested relative track
    """
    return get_absolute_track(file, track, type).track_id
