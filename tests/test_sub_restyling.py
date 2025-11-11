from muxtools import Setup, get_workdir, ensure_path, SubFile, GJM_GANDHI_PRESET
from shutil import rmtree
from time import sleep
import pytest

test_dir = ensure_path(__file__, None).parent


@pytest.fixture(autouse=True)
def setup_and_remove():
    Setup("Test", None)

    yield

    sleep(0.1)
    rmtree(get_workdir())


def test_regular_unfuck_cr() -> None:
    actual = SubFile(test_dir / "test-data" / "input" / "vigilantes_s01e01_en.ass")
    actual.unfuck_cr().restyle(GJM_GANDHI_PRESET)
    actual_doc = actual._read_doc()

    expected = SubFile(test_dir / "test-data" / "output" / "vigilantes_s01e01_en_unfuck_cr_restyled.ass")
    expected_doc = expected._read_doc()

    for style_ac, style_ex in zip(actual_doc.styles, expected_doc.styles, strict=True):
        assert style_ac.name == style_ex.name

    for line_ac, line_ex in zip(actual_doc.events, expected_doc.events, strict=True):
        assert line_ac.text == line_ex.text
        assert line_ac.style == line_ex.style


def test_ccc_unfuck_cr() -> None:
    actual = SubFile(
        test_dir
        / "test-data"
        / "input"
        / "A.Wild.Last.Boss.Appeared.S01E01.A.Wild.Last.Boss.Appears.1080p.CR.WEB-DL.AAC2.0.H.264-VARYG_track3.eng.ass"
    )
    actual.unfuck_cr().restyle(GJM_GANDHI_PRESET)
    actual_doc = actual._read_doc()

    expected = SubFile(test_dir / "test-data" / "output" / "A.Wild.Last.Boss.Appeared.S01E01.unfuck_cr_restyled.ass")
    expected_doc = expected._read_doc()

    for style_ac, style_ex in zip(actual_doc.styles, expected_doc.styles, strict=True):
        assert style_ac.name == style_ex.name

    for line_ac, line_ex in zip(actual_doc.events, expected_doc.events, strict=True):
        assert line_ac.text == line_ex.text
        assert line_ac.style == line_ex.style
