from datetime import timedelta
from pathlib import Path

import pytest
from ass import Dialogue, Style

from muxtools import SubFile, Setup
from muxtools.subtitle.subutils import create_document


def _write_sub(path: Path, text: str) -> Path:
    doc = create_document()
    doc.styles.append(Style(name="Default"))
    doc.events.append(Dialogue(start=timedelta(0), end=timedelta(seconds=1), style="Default", text=text))
    with open(path, "w", encoding="utf_8_sig") as writer:
        doc.dump_file(writer)
    return path


def _swap(tmp_path: Path, text: str, **kwargs) -> str:
    sub = SubFile(_write_sub(tmp_path / "swap.ass", text))
    sub.autoswapper(**kwargs)
    return sub._read_doc().events[0].text


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # SubFile writes its working copies to the current directory
    monkeypatch.chdir(tmp_path)
    # Other tests leave a deleted workdir behind in the global setup, so always point it somewhere that exists
    Setup("Test", None, work_dir=str(tmp_path))


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
