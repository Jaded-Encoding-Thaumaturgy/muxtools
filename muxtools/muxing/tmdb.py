import xml.etree.ElementTree as ET
from dataclasses import dataclass
import requests
import logging

from ..utils.types import PathLike
from ..utils.log import debug, error


# https://github.com/Radarr/Radarr/blob/29ba6fe5563e737f0f87919e48f556e39284e6bb/src/NzbDrone.Common/Cloud/RadarrCloudRequestBuilder.cs#L31
# skill issue
API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIxYTczNzMzMDE5NjFkMDNmOTdmODUzYTg3NmRkMTIxMiIsInN1YiI6IjU4NjRmNTkyYzNhMzY4MGFiNjAxNzUzNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.gh1BwogCCKOda6xj9FRMgAAj_RYKMMPC3oNlcBtlmwk"
BASE_URL = "https://api.themoviedb.org/3/"

logging.getLogger("urllib3.connectionpool").setLevel(logging.CRITICAL)


__all__ = ["TmdbConfig", "TitleTMDB"]


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
    :param season:          The number of the season.
    :param movie:           Is this a movie?
    :param language:        The metadata language. Defaults to english.
                            This requires ISO 639-1 codes. See https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
                            Be aware that some metadata might just not exist in your requested language. Check beforehand.

    :param write_title:     Writes the episode title to the `DESCRIPTION` mkv tag if True
    :param write_ids:       Writes the IDs (IMDB, TVDB, TMDB) to their respective mkv tags if True
    :param write_date:      Writes the episode release date to the `DATE_RELEASED` mkv tag if True
    :param write_cover:     Download episode thumbnail from TMDB to use as cover art attachment for the MKV.
    :param write_summary:   Writes the series summary/synopsis to the `SUMMARY` mkv tag if True
    :param write_synposis:  Writes the individual episode synopsis to the `SYNOPSIS` mkv tag if True
    """

    id: int
    season: int = 1
    movie: bool = False
    language: str = "en-US"

    write_ids: bool = True
    write_date: bool = True
    write_title: bool = False
    write_cover: bool = False
    write_summary: bool = False
    write_synposis: bool = False

    def needs_xml(self) -> bool:
        return self.write_ids or self.write_date or self.write_title or self.write_summary or self.write_synposis

    def get_media_meta(self) -> MediaMetadata:
        url = f"{BASE_URL}/{'movie' if self.movie else 'tv'}/{self.id}?language={self.language}"
        headers = {"accept": "application/json", "Authorization": f"Bearer {API_KEY}"}
        response = requests.get(url, headers=headers)

        if response.status_code > 202:
            ex = error(f"Media Metadata Request has failed! ({response.status_code})", self)
            debug(response.text)
            raise ex

        mediajson = response.json()

        url = f"{BASE_URL}{'movie' if self.movie else 'tv'}/{self.id}/external_ids"
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
            url = f"{BASE_URL}/tv/{self.id}/season/{self.season}?language={self.language}"
            headers = {"accept": "application/json", "Authorization": f"Bearer {API_KEY}"}
            response = requests.get(url, headers=headers)

            if response.status_code > 202:
                ex = error(f"Episode Metadata Request has failed! ({response.status_code})", self)
                debug(response.text)
                raise ex

            self.episodes = response.json()["episodes"]

        try:
            episode = self.episodes[num - 1]
        except:
            raise error(f"Failed to find or parse episode {num:02}!", self)

        return EpisodeMetadata(
            episode.get("name", ""),
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
        if self.write_synposis and not self.movie:
            tags.update(SYNOPSIS=episode.synopsis)

        outfile = make_output("tags", "xml")
        main = ET.Element("Tags")
        tag = ET.SubElement(main, "Tag")
        target = ET.SubElement(tag, "Targets")
        targettype = ET.SubElement(target, "TargetTypeValue")
        targettype.text = "50"

        for k, v in tags.items():
            simple = ET.SubElement(tag, "Simple")
            key = ET.SubElement(simple, "Name")
            key.text = k
            value = ET.SubElement(simple, "String")
            value.text = str(v)

        with open(outfile, "w") as f:
            ET.ElementTree(main).write(f, encoding="unicode")

        return outfile


def TitleTMDB(id: int, season: int = 1, movie: bool = False, language: str = "en-US") -> TmdbConfig:
    return TmdbConfig(id, season, movie, language, False, False, False, False, False, False)
