from langcodes import Language, standardize_tag as stdz_tag
from typing import Any

from .log import error

__all__ = ["standardize_tag"]


def standardize_tag(lang: str, caller: Any | None = None) -> tuple[Language, str]:
    standardized = stdz_tag(lang)
    language = Language.get(standardized)

    if not language.is_valid():
        raise error(f"The language tag '{lang}' is not valid!", caller or standardize_tag)

    return (language, language.to_tag())
