from dataclasses import dataclass
from enum import IntEnum
import requests
import logging

from ..utils.types import PathLike
from ..utils.log import debug, error, info
from ..utils.files import create_tags_xml


# https://github.com/Radarr/Radarr/blob/29ba6fe5563e737f0f87919e48f556e39284e6bb/src/NzbDrone.Common/Cloud/RadarrCloudRequestBuilder.cs#L31
# skill issue
API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIxYTczNzMzMDE5NjFkMDNmOTdmODUzYTg3NmRkMTIxMiIsInN1YiI6IjU4NjRmNTkyYzNhMzY4MGFiNjAxNzUzNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.gh1BwogCCKOda6xj9FRMgAAj_RYKMMPC3oNlcBtlmwk"
BASE_URL = "https://api.themoviedb.org/3"

logging.getLogger("urllib3.connectionpool").setLevel(logging.CRITICAL)


__all__ = ["TmdbConfig", "TitleTMDB", "TMDBOrder"]


class TMDBOrder(IntEnum):
    """
    TMDB Episode groups or orders. Don't think there is a universally agreed on name.\n
    This enum is for automatically selecting one with the given type.
    """

    ORIGINAL_AIR_DATE = 1
    """Original air date order"""
    ABSOLUTE = 2
    """Absolute numbering order"""
    DVD = 3
    """DVD order"""
    DIGITAL = 4
    """Digital order"""
    STORY_ARC = 5
    """Story Arc order"""
    PRODUCTION = 6
    """
    Production order, this is usually what contains the proper seasons now that 
    TMDB mods decided to be weird.

    See https://www.themoviedb.org/tv/95479/discuss/64a5672ada10f0011cb49f99
    """
    TV = 7
    """TV order"""


@dataclass
class MediaMetadata:
    tmdb_id: int
    tvdb_id: int
    imdb_id: str
    summary: str

    release_date: str | None = None


@dataclass
class EpisodeMetadata:
    title: str
    release_date: str
    synopsis: str
    thumb_url: str


@dataclass
class TmdbConfig:
    """
    A simple configuration class for TMDB Usage in muxing.

    :param id:              TMDB Media ID. The numerical part in URLs like https://www.themoviedb.org/tv/82684/...
    :param season:          The number of the season. If given an order this will be the Nth subgroup in that order.
    :param movie:           Is this a movie?
    :param order:           Episode group/order enum or a string for an exact ID. Obviously not applicable to a movie.
    :param language:        The metadata language. Defaults to english.
                            This requires ISO 639-1 codes. See https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
                            Be aware that some metadata might just not exist in your requested language. Check beforehand.

    :param offset:          Offset to apply to the current number used in the setup that will be matched to the TMDB number.

    :param write_title:     Writes the episode title to the `DESCRIPTION` mkv tag if True
    :param write_ids:       Writes the IDs (IMDB, TVDB, TMDB) to their respective mkv tags if True
    :param write_date:      Writes the episode release date to the `DATE_RELEASED` mkv tag if True
    :param write_cover:     Download episode thumbnail from TMDB to use as cover art attachment for the MKV.
    :param write_summary:   Writes the series summary/synopsis to the `SUMMARY` mkv tag if True
    :param write_synopsis:  Writes the individual episode synopsis to the `SYNOPSIS` mkv tag if True
    :param replace_spaces:  Replaces spaces in titles with dots if True and with whatever string you passed if a string.
    """

    id: int
    season: int = 1
    movie: bool = False
    order: TMDBOrder | str | None = None
    language: str = "en-US"
    offset: int = 0

    write_ids: bool = True
    write_date: bool = True
    write_title: bool = False
    write_cover: bool = False
    write_summary: bool = False
    write_synopsis: bool = False
    replace_spaces: str | bool = False

    def needs_xml(self) -> bool:
        return self.write_ids or self.write_date or self.write_title or self.write_summary or self.write_synopsis

    def get_media_meta(self) -> MediaMetadata:
        url = f"{BASE_URL}/{'movie' if self.movie else 'tv'}/{self.id}?language={self.language}"
        headers = {"accept": "application/json", "Authorization": f"Bearer {API_KEY}"}
        response = requests.get(url, headers=headers)

        if response.status_code > 202:
            ex = error(f"Media Metadata Request has failed! ({response.status_code})", self)
            debug(response.text)
            raise ex

        mediajson = response.json()

        url = f"{BASE_URL}/{'movie' if self.movie else 'tv'}/{self.id}/external_ids"
        response = requests.get(url, headers=headers)
        other_ids = response.json()

        return MediaMetadata(
            self.id,
            other_ids.get("tvdb_id", 0),
            other_ids.get("imdb_id", ""),
            mediajson.get("overview", ""),
            mediajson.get("release_date", None) if self.movie else None,
        )

    def get_episode_meta(self, num: int) -> EpisodeMetadata:
        if not hasattr(self, "episodes"):
            headers = {"accept": "application/json", "Authorization": f"Bearer {API_KEY}"}
            if self.order:
                if not hasattr(self, "order_id"):
                    if isinstance(self.order, str):
                        setattr(self, "order_id", self.order)
                    else:
                        orders_url = f"{BASE_URL}/tv/{self.id}/episode_groups"
                        order_resp = requests.get(orders_url, headers=headers)
                        orders = order_resp.json()["results"]
                        if not orders:
                            raise error("Could not find any episode groups/orders for this show.", self)
                        filtered = [order for order in orders if order["type"] == self.order]
                        if not filtered:
                            raise error(f"Could not find an episode groups/orders for type {self.order.name}.", self)

                        wanted_order = sorted(filtered, key=lambda it: it["group_count"])[0]
                        info(f"Selecting episode group '{wanted_order['name']}'.", self)
                        setattr(self, "order_id", str(wanted_order["id"]))

                url = f"{BASE_URL}/tv/episode_group/{self.order_id}?language={self.language}"
            else:
                url = f"{BASE_URL}/tv/{self.id}/season/{self.season}?language={self.language}"

            meta_response = requests.get(url, headers=headers)

            if meta_response.status_code > 202:
                ex = error(f"Episode Metadata Request has failed! ({meta_response.status_code})", self)
                debug(meta_response.text)
                raise ex

            json_resp: dict = meta_response.json()
            if "groups" in json_resp:
                groups = json_resp["groups"]
                try:
                    group = [group for group in groups if group["order"] == self.season][0]
                except:
                    raise error(f"Could not find subgroup for the number {self.season}.", self)
                self.episodes = group["episodes"]
            else:
                self.episodes = json_resp["episodes"]

        try:
            episode: dict = self.episodes[(num + self.offset) - 1]
        except:
            raise error(f"Failed to find or parse episode {num:02}!", self)

        title: str = episode.get("name", "")
        if self.replace_spaces is True:
            title = title.replace(" ", ".")
        elif isinstance(self.replace_spaces, str):
            title = title.replace(" ", self.replace_spaces)

        return EpisodeMetadata(
            title,
            episode.get("air_date", ""),
            episode.get("overview", ""),
            f"https://image.tmdb.org/t/p/w780{episode.get('still_path')}" if self.write_cover else "",
        )

    def make_xml(self, media: MediaMetadata, episode: EpisodeMetadata | None = None) -> PathLike:
        from ..utils.files import make_output

        tags = dict()

        if self.write_title and episode:
            tags.update(DESCRIPTION=episode.title)
        if self.write_ids:
            if not self.movie and media.tvdb_id:
                tags.update(TVDB=media.tvdb_id)
            prefix = "movie/" if self.movie else "tv/"
            tags.update(TMDB=prefix + str(media.tmdb_id))
            tags.update(IMDB=media.imdb_id)
        if self.write_date:
            if self.movie:
                if media.release_date:
                    tags.update(DATE_RELEASED=media.release_date)
            else:
                tags.update(DATE_RELEASED=episode.release_date)
        if self.write_summary:
            tags.update(SUMMARY=media.summary)
        if self.write_synopsis and not self.movie:
            tags.update(SYNOPSIS=episode.synopsis)

        outfile = make_output("tags", "xml")
        create_tags_xml(outfile, tags)

        return outfile


def TitleTMDB(
    id: int, season: int = 1, movie: bool = False, language: str = "en-US", offset: int = 0, order: TMDBOrder | str | None = None
) -> TmdbConfig:
    """
    Shortcut function to get a TMDB config with just titles enabled.

    :param id:              TMDB Media ID. The numerical part in URLs like https://www.themoviedb.org/tv/82684/...
    :param season:          The number of the season. If given an order this will be the Nth subgroup in that order.
    :param movie:           Is this a movie?
    :param order:           Episode group/order enum or a string for an exact ID. Obviously not applicable to a movie.
    :param language:        The metadata language. Defaults to english.
                            This requires ISO 639-1 codes. See https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
                            Be aware that some metadata might just not exist in your requested language. Check beforehand.

    :param offset:          Offset to apply to the current number used in the setup that will be matched to the TMDB number.
    """
    return TmdbConfig(id, season, movie, order, language, offset, False, False, False, False, False, False)
