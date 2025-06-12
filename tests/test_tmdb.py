from muxtools import TmdbConfig, TMDBOrder


def test_tmdb_custom_order() -> None:
    cfg = TmdbConfig(95479, 2, order=TMDBOrder.PRODUCTION)
    episode_meta = cfg.get_episode_meta(1)
    assert episode_meta is not None
    assert episode_meta.release_date == "2023-07-06"


def test_tmdb_sanitization() -> None:
    cfg = TmdbConfig(65336)
    episode_meta = cfg.get_episode_meta(1)
    assert episode_meta is not None
    assert episode_meta.title == "Chapter 1 Rei Kiriyama / Chapter 2 The Town Along the River"
    assert episode_meta.title_sanitized == "Chapter 1 Rei Kiriyama  Chapter 2 The Town Along the River"
