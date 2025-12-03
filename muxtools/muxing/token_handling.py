import re
from typing_extensions import Any

from ..utils.language_util import standardize_tag
from ..utils.types import PathLike, TrackType
from ..utils.probe import ParsedFile, TrackInfo
from ..utils.log import error

__all__ = ["apply_dynamic_tokens"]

PROPERTIES = ["lang", "lang3", "lang3b", "language", "codec", "format", "ch", "channels", "res", "resolution", "depth", "bits"]
TOKEN_REGEX = re.compile(
    rf"(?:\$|#)(?P<type>(?:v|a|s))?(?P<prop>(?:{'|'.join(PROPERTIES)}))(?:(?:_(?P<num>\d+))|(?:_(?P<lang>[^_0-9\$\n]+)(?:_(?P<num2>\d+))?))?(?:\$|#)",
    re.I,
)
# https://regex101.com/r/NYzJyz/1


def _matching_track_type(value: str | None) -> TrackType | None:
    match str(value).lower():
        case "v":
            return TrackType.VIDEO
        case "a":
            return TrackType.AUDIO
        case "s":
            return TrackType.SUB
        case _:
            return None


def _get_prop(prop: str, track: TrackInfo, user_lang: str | None, token: str, caller: Any | None = None) -> str:
    if prop.lower() in ["ch", "channels"] and track.type != TrackType.AUDIO:
        raise error(f"Cannot fill token '{token}' for missing audio track! (Index {track.index})", caller)

    if prop.lower() in ["res", "resolution"] and track.type != TrackType.VIDEO:
        raise error(f"Cannot fill token '{token}' for missing video track! (Index {track.index})", caller)

    if prop.lower() in ["depth", "bits"] and track.type not in [TrackType.VIDEO, TrackType.AUDIO]:
        raise error(f"Cannot fill token '{token}' for missing video / audio track! (Index {track.index})", caller)

    lang = standardize_tag(user_lang, caller)[0] if user_lang else track.sanitized_lang

    match prop.lower():
        case "ch" | "channels":
            if not track.raw_ffprobe.channels:
                raise error(f"Track {track.index} does not have a valid audio channel number! (requested via '{token}')", caller)
            if track.raw_ffprobe.channel_layout:
                layout = str(track.raw_ffprobe.channel_layout).lower()
                layout = layout if " " not in layout else layout.split(" ")[0]
                if (match := re.match(r"\d+\.\d+(?:\.\d+)?", layout)) is not None:
                    return match.group(0)
                elif "lfe" in layout:
                    return f"{int(track.raw_ffprobe.channels) - 1}.1"

            return f"{int(track.raw_ffprobe.channels)}.0"

        case "res" | "resolution":
            if not track.raw_ffprobe.height:
                raise error(f"Track {track.index} does not have a valid resolution! (requested via '{token}')", caller)
            return f"{int(track.raw_ffprobe.height)}p"

        case "codec" | "format":
            if track.type == TrackType.AUDIO:
                form = track.get_audio_format()
                if not form:
                    raise error(f"Track {track.index} does not have a known audio format! (requested via '{token}')", caller)
                return form.display_name
            else:
                return track.codec_name.upper()

        case "bits" | "depth":
            if not track.bit_depth:
                raise error(f"Track {track.index} does not have a valid bit depth! (requested via '{token}')", caller)
            return str(track.bit_depth)

        case "lang":
            return lang.to_tag().upper()
        case "lang3":
            return lang.to_alpha3().upper()
        case "lang3b":
            return lang.to_alpha3("B").upper()
        case "language":
            return lang.display_name()

        case _:
            raise error(f"Unknown prop requested in token '{token}'.", caller)


def replace_with_temp_tokens(string: str) -> str:
    """
    Replace regular $ tokens with # tokens to be able to be used in filenames temporarily.
    """
    new = string
    for match in re.finditer(TOKEN_REGEX, string):
        new = new.replace(match.group(0), f"#{match.group(0)[1:-1]}#")
    return new


def _apply_tokens_via_track(string: str, token_source: TrackInfo, user_lang: str | None = None, caller: Any | None = None) -> str:
    matches = list(re.finditer(TOKEN_REGEX, string))
    if not matches:
        return string

    new = string

    for match in matches:
        groups = match.groupdict()
        replacement = _get_prop(str(groups["prop"]), token_source, user_lang, match.group(0), caller)
        new = new.replace(match.group(0), replacement)

    return new


def apply_dynamic_tokens(
    string: str, token_source: PathLike | ParsedFile, is_global: bool, user_lang: str | None = None, caller: Any | None = None
) -> str:
    """
    Apply dynamic tokens to naming strings based on a file and/or user selected language (for raw tracks).

    :param string:          The string to manipulate
    :param token_source:    The file to read metadata from
    :param is_global:       Should be true if this string is meant to be used for a filename and False for tracks
    :param user_lang:       The language to be used if there is none or if it should be overridden
    :param caller:          The object to be used for the logging, mostly for internal usage

    :return:                The modified string if anything was there to modify, otherwise the untouched input.
    """
    caller = caller or apply_dynamic_tokens

    matches = list(re.finditer(TOKEN_REGEX, string))
    if not matches:
        return string

    source = token_source if isinstance(token_source, ParsedFile) else ParsedFile.from_file(token_source, caller)
    new = string

    for match in matches:
        groups = match.groupdict()

        if is_global and not groups["type"]:
            if groups["prop"].lower() in ["res", "resolution"]:
                groups["type"] = "v"
            elif groups["prop"].lower() in ["ch", "channels"]:
                groups["type"] = "a"
            else:
                raise error(f"Ambiguous token '{match.group(0)}' used. Please specify a track type!", caller)

        tracktype = _matching_track_type(groups["type"])
        if groups["lang"]:
            relative_id = None
        else:
            relative_id = 0 if groups["num"] is None else int(groups["num"])

        post_filter_index = 0 if groups["num2"] is None else int(groups["num2"])

        track = source.find_tracks(
            type=tracktype,
            lang=groups["lang"],
            relative_id=relative_id,
            error_if_empty=True,
            caller=caller,
        )[post_filter_index]

        replacement = _get_prop(str(groups["prop"]), track, user_lang, match.group(0), caller)
        new = new.replace(match.group(0), replacement)

    return new
