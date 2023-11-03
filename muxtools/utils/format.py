from pymediainfo import MediaInfo, Track
from .types import TrackType, PathLike, AudioFormat, VideoFormat
from .files import ensure_path_exists
from .log import error, warn
import re


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


# fmt: off
audio_formats = [
    # Lossy
    AudioFormat("AC-3",         "ac3",      "A_AC3"),
    AudioFormat("E-AC-3",       "eac3",     "A_EAC3"),
    AudioFormat("AAC*",         "m4a",      "A_AAC*"), # Lots of different AAC formats idk what they mean, don't care either
    AudioFormat("Opus",         "opus",     "A_OPUS"),
    AudioFormat("Vorbis",       "ogg",      "A_VORBIS", lossy=True, supports_mp4=False),
    AudioFormat("/",            "mp3",      "mp4a-6B"), # MP3 has the format name split up into 3 variables so we're gonna ignore this
    
    # Lossless
    AudioFormat("FLAC",         "flac",     "A_FLAC", lossy=False),
    AudioFormat("ALAC",         "alac",     "A_ALAC", lossy=False),
    AudioFormat("MLP FBA*",     "thd",      "A_TRUEHD", lossy=False), # Atmos stuff has some more shit in the format name
    AudioFormat("PCM*",         "wav",      "A_PCM*", lossy=False, supports_mp4=False),

    # Disgusting DTS Stuff
    AudioFormat("DTS XLL*",     "dtshd",    "A_DTS", lossy=False), # Can be HD-MA or Headphone X or X, who the fuck knows
    AudioFormat("DTS",          "dts",      "A_DTS"), # Can be lossy
]

video_formats = [
    VideoFormat("AVC",      "avc",      "V_MPEG4/ISO/AVC",  True, [".h264", ".264"]),
    VideoFormat("HEVC",     "hevc",     "V_MPEGH/ISO/HEVC", True, [".h265", ".265"]),
    VideoFormat("MPEG-2",   "mpeg2",    "V_MPEG2"),
    
    VideoFormat("AV1",      "av1",      "V_AV1"),
    VideoFormat("VP9",      "vp9",      "V_VP9"),
    VideoFormat("VP8",      "vp8",      "V_VP8"),
    VideoFormat("VC-1",     "vc1",      "V_MS/VFW/FOURCC*")
]
# fmt: on


def format_from_track(track: Track) -> AVForm | None:
    for format in video_formats + audio_formats:
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
