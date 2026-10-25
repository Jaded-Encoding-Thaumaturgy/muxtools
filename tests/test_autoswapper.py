from pathlib import Path

import pytest

from muxtools import SubFile

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _swap(tmp_path: Path, text: str, **kwargs) -> str:
    file = tmp_path / "swap.ass"
    file.write_text(HEADER + f"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{text}\n", encoding="utf-8")
    sub = SubFile(file)
    sub.autoswapper(**kwargs)
    return sub._read_doc().events[0].text


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # SubFile writes its working copies to the current directory
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize(
    "text, swapped",
    [
        (r"Hi {*}Mary{*Mary-tan}!", r"Hi {*}Mary-tan{*Mary}!"),
        (r"Karen{**-chan}", r"Karen{*}-chan{*}"),
        (r"Hi{*} there{*}", r"Hi{** there}"),
        # a shown bit followed by a hidden one used to get merged into one broken ab swap
        (r"{*}wow{*} and {**yo}!", r"{**wow} and {*}yo{*}!"),
        # two ab swaps that swap into each other used to get swapped twice
        (r"{*}Gendo{*Ikari}\N\h {*}Ikari{*Gendo}", r"{*}Ikari{*Gendo}\N\h {*}Gendo{*Ikari}"),
        (r"{*}{\i1}abc{*[/b1]def}", r"{*}{\b1}def{*[/i1]abc}"),
        (r"abc{**[/b1]def}", r"abc{*}{\b1}def{*}"),
        (r"abc{*}{\b1}def{*}", r"abc{**[/b1]def}"),
    ],
)
def test_autoswapper_tag_markers(tmp_path: Path, text: str, swapped: str):
    assert _swap(tmp_path, text, inline_tag_markers="[]") == swapped
    assert _swap(tmp_path, swapped, inline_tag_markers="[]") == text


@pytest.mark.parametrize(
    "text, swapped",
    [
        (r"Hi {*}Mary{*Mary-tan}!", r"Hi {*}Mary-tan{*Mary}!"),
        (r"{*}wow{*} and {**yo}!", r"{**wow} and {*}yo{*}!"),
        (r"{*}Gendo{*Ikari}\N\h {*}Ikari{*Gendo}", r"{*}Ikari{*Gendo}\N\h {*}Gendo{*Ikari}"),
        # without tag markers, tags are dropped entirely instead of leaving them half there
        (r"{*}{\i1}Wow!{\i0}{*}", r"{**Wow!}"),
        (r"{*}{\i1}abc{*def}", r"{*}def{*abc}"),
    ],
)
def test_autoswapper_no_tag_markers(tmp_path: Path, text: str, swapped: str):
    assert _swap(tmp_path, text) == swapped
