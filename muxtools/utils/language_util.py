from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langcodes import Language

from .log import error

__all__ = ["standardize_tag", "languages_match"]


def standardize_tag(lang: str, caller: Any | None = None) -> tuple[Language, str]:
    from langcodes import Language, standardize_tag as stdz_tag

    standardized = stdz_tag(lang)
    language = Language.get(standardized)

    if not language.is_valid():
        raise error(f"The language tag '{lang}' is not valid!", caller or standardize_tag)

    return (language, language.to_tag())


def languages_match(query: Language, candidate: Language, *, allow_broader: bool = False) -> bool:
    """
    Match a candidate language against a requested language tag using BCP-47 subtag hierarchy
    and CLDR equivalence (e.g. `zh-CN` <-> `zh-Hans`), without crossing distinct regions or scripts.

    When `allow_broader` is True, a specific query (e.g. `es-419`, `en-US`) also matches broader
    untagged candidates of the same language (e.g. `es`, `en`).
    """
    if query == candidate:
        return True
    if not query.language or query.language != candidate.language:
        return False

    query_tag = query.to_tag()
    candidate_tag = candidate.to_tag()
    if query_tag in candidate.broader_tags():
        return True
    if candidate_tag in query.broader_tags():
        return allow_broader
    return query.distance(candidate) == 0
