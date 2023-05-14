from pymediainfo import MediaInfo, Track
from utils.types import TrackType, PathLike, AudioFormat
from utils.files import ensure_path_exists
from utils.log import error, warn
import re

# Of course these are not all of the formats possible but those are the most common from what I know.
# fmt: off
formats = [
    # Lossy
    AudioFormat("AC-3",         "ac3",      "A_AC3"),
    AudioFormat("E-AC-3",       "eac3",     "A_EAC3"),
    AudioFormat("AAC",          "aac",      "A_AAC*"), # Lots of different AAC formats idk what they mean, don't care either
    AudioFormat("Opus",         "opus",     "A_OPUS"),
    AudioFormat("Vorbis",       "ogg",      "A_VORBIS"),
    
    # Lossless
    AudioFormat("FLAC",         "flac",     "A_FLAC", False),
    AudioFormat("MLP FBA*",     "thd",      "A_TRUEHD", False), # Atmos stuff has some more shit in the format name
    AudioFormat("PCM*",         "wav",      "A_PCM*", False),

    # Disgusting DTS Stuff
    AudioFormat("DTS XLL",      "dtshd",    "A_DTS", False), # Can be HD-MA or Headphone X or X, who the fuck knows
    AudioFormat("DTS",          "dts",      "A_DTS"), # Can be lossy
]
# fmt: on


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
                raise error(f"Your requested track doesn't exist.", get_absolute_track)
        case TrackType.AUDIO:
            if not audios:
                raise error(f"No audio tracks have been found in '{file.name}'!", get_absolute_track)
            try:
                return audios[track]
            except:
                raise error(f"Your requested track doesn't exist.", get_absolute_track)
        case TrackType.SUB:
            if not subtitles:
                raise error(f"No subtitle tracks have been found in '{file.name}'!", get_absolute_track)
            try:
                return subtitles[track]
            except:
                raise error(f"Your requested track doesn't exist.", get_absolute_track)
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


def format_from_track(track: Track) -> AudioFormat | None:
    for format in formats:
        f = str(track.format)
        if hasattr(track, "format_additionalfeatures") and track.format_additionalfeatures:
            f = f"{f} {track.format_additionalfeatures}"
        if "*" in format.format:
            # matches = filter([f.lower()], format.format.lower())
            if re.match(format.format.replace("*", ".*"), f, re.IGNORECASE):
                return format
        else:
            if format.format.casefold() == f.casefold():
                return format

        if "*" in format.codecid:
            # matches = filter([str(track.codec_id).lower()], format.codecid)
            if re.match(format.codecid.replace("*", ".*"), str(track.codec_id), re.IGNORECASE):
                return format
        else:
            if format.codecid.casefold() == str(track.codec_id).casefold():
                return format
    return None


def is_fancy_codec(track: Track) -> bool:
    """
    Tries to check if a track is some fancy DTS (X, Headphone X) or TrueHD with Atmos

    :param track:   Input track to check
    """
    codec_id = str(track.codec_id).casefold()
    if codec_id == "A_TRUEHD".casefold():
        # If it contains something other than "MLP FBA" it's probably atmos
        return bool(re.sub("MLP FBA", "", str(track.format).strip(), re.IGNORECASE))
    elif codec_id == "A_DTS".casefold():
        # Not even lossless if this doesn't exist
        if not hasattr(track, "format_additionalfeatures"):
            return False
        # If those additional features contain something after removing "XLL" its some fancy stuff
        return bool(re.sub("XLL", "", str(track.format_additionalfeatures).strip(), re.IGNORECASE))

    return False
