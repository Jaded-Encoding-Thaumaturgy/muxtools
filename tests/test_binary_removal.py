from pathlib import Path

import pytest

from muxtools import cli
from muxtools.config import init_config, update_config
from muxtools.utils.binaries import operations


def _install(root: Path, name: str, version: str, code: int) -> Path:
    directory = root / name / version
    directory.mkdir(parents=True)
    (directory / name).write_bytes(b"binary")
    (directory / ".metadata.toml").write_text(
        f'name = "{name}"\nversion = "{version}"\nversion_code = {code}\n[binaries]\n{name} = "{name}"\n',
        encoding="utf-8",
    )
    return directory


def test_cleanup_keeps_selected_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = update_config(init_config(tmp_path / "muxtools.toml").path, packages=["x265<=9.0"])
    root = operations.scope_path(config)
    old = _install(root, "x265", "8.0", 8)
    selected = _install(root, "x265", "9.0", 9)
    newer = _install(root, "x265", "10.0", 10)
    unused = _install(root, "opus", "1.0", 1)
    monkeypatch.setattr(operations, "load_catalog", lambda offline=True: {"packages": {"x265": {}}})

    operations.apply_removal(operations.plan_removal(config, "local", ["*"]))

    assert selected.exists()
    assert not old.exists() and not newer.exists() and not unused.exists()


def test_remove_requires_confirmation_without_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = init_config(tmp_path / "muxtools.toml")
    directory = _install(operations.scope_path(config), "x265", "9.0", 9)
    monkeypatch.setattr(cli, "discover_config", lambda: config)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(operations, "load_catalog", lambda offline=True: {"packages": {"x265": {}}})

    with pytest.raises(ValueError, match="--yes"):
        cli.remove("x265")
    assert directory.exists()


def test_remove_rejects_mismatched_metadata_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = init_config(tmp_path / "muxtools.toml")
    directory = _install(operations.scope_path(config), "x265", "9.0", 9)
    (directory / ".metadata.toml").write_text('name = "../outside"\nversion = "9.0"\nversion_code = 9\n', encoding="utf-8")
    monkeypatch.setattr(operations, "load_catalog", lambda offline=True: {"packages": {}})

    with pytest.raises(ValueError, match="Unsafe installed binary path"):
        operations.plan_removal(config, "local", ["*"])
    assert directory.exists()
