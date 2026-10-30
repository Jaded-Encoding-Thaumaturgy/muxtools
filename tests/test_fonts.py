from muxtools import SubFile, Setup, get_workdir, collect_fonts, LoggingException
from muxtools.subtitle.subutils import create_document
from ass import Dialogue, Style
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree
import logging
from time import sleep
import pytest


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def _build_font(family: str, bold: bool = False, chars: str = "abcdefghijklmnopqrstuvwxyz ") -> TTFont:
    """
    Builds a minimal TrueType font with a square glyph for every character in `chars`.
    """
    glyph_names = {ord(c): f"uni{ord(c):04X}" for c in chars}
    glyph_order = [".notdef", *glyph_names.values()]

    def square():
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((0, 500))
        pen.lineTo((500, 500))
        pen.lineTo((500, 0))
        pen.closePath()
        return pen.glyph()

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(glyph_names)
    builder.setupGlyf({name: square() for name in glyph_order})
    builder.setupHorizontalMetrics({name: (600, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": "Bold" if bold else "Regular"})
    builder.setupOS2(usWeightClass=700 if bold else 400, fsSelection=0x20 if bold else 0x40)
    builder.setupPost()
    builder.updateHead(macStyle=1 if bold else 0)
    return builder.font


def _make_font(path: Path, family: str, bold: bool = False) -> Path:
    _build_font(family, bold).save(path)
    return path


def _write_sub(path: Path, styles: list[tuple[str, str]], lines: list[tuple[str, str]]) -> SubFile:
    """
    :param styles:  (style name, font name) pairs
    :param lines:   (style name, text) pairs
    """
    doc = create_document()
    doc.styles.extend(Style(name=name, fontname=font) for name, font in styles)
    doc.events.extend(Dialogue(style=style, text=text) for style, text in lines)
    with open(path, "w", encoding="utf_8_sig") as writer:
        doc.dump_file(writer)
    return SubFile(path)


class _RecordWarnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages = list[str]()

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def _warnings() -> Iterator[list[str]]:
    """
    Collects everything muxtools logs as a warning or worse.
    """
    handler = _RecordWarnings()
    logger = logging.getLogger("muxtools")
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)


def test_collect_fonts_multiple_subs(tmp_path: Path) -> None:
    """
    Collecting for several subs at once gets the fonts of all of them.
    Different fonts that end up with the same file name in the workdir are both kept, even when used by different subs.
    """
    source = tmp_path / "fonts"
    source.mkdir()
    _make_font(source / "shared.ttf", "MT Test")
    _make_font(source / "one.ttf", "Foo Bar")
    _make_font(source / "two.ttf", "Foo/Bar")
    first = _write_sub(tmp_path / "first.ass", [("Default", "MT Test"), ("Sign", "Foo Bar")], [("Default", "abc"), ("Sign", "abc")])
    second = _write_sub(tmp_path / "second.ass", [("Default", "MT Test"), ("Sign", "Foo/Bar")], [("Default", "def"), ("Sign", "def")])

    Setup("Test", None, error_on_danger=True)
    with _warnings() as warnings:
        collected = collect_fonts([first, second], use_system_fonts=False, additional_fonts=source)
    assert not warnings
    assert len(collected) == 3


def test_collect_fonts_separate_calls(tmp_path: Path) -> None:
    """
    Collecting again reuses the files already in the workdir, but not for a different font that ends up with the same file name.
    """
    source = tmp_path / "fonts"
    source.mkdir()
    _make_font(source / "one.ttf", "Foo Bar")
    _make_font(source / "two.ttf", "Foo/Bar")
    first = _write_sub(tmp_path / "first.ass", [("Default", "Foo Bar")], [("Default", "abc")])
    second = _write_sub(tmp_path / "second.ass", [("Default", "Foo/Bar")], [("Default", "def")])

    collect_fonts(first, use_system_fonts=False, additional_fonts=source)
    collect_fonts(second, use_system_fonts=False, additional_fonts=source)
    collected = collect_fonts(first, use_system_fonts=False, additional_fonts=source)
    assert len(collected) == 2


def test_collect_fonts_checks_repeated_face(tmp_path: Path) -> None:
    """
    Missing glyphs are reported even when an earlier style already used the same font.
    """
    # There's no bold face so the bold text resolves to the regular one again
    _make_font(tmp_path / "font.ttf", "MT Test")
    sub = _write_sub(tmp_path / "sub.ass", [("Default", "MT Test")], [("Default", "abc"), ("Default", R"{\b1}abc€")])

    Setup("Test", None, error_on_danger=True)
    with pytest.raises(LoggingException, match="missing the following glyphs"):
        sub.collect_fonts(use_system_fonts=False, search_current_dir=False, additional_fonts=[tmp_path])
