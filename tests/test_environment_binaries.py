from pathlib import Path

import pytest

from muxtools import cli
from muxtools.config import EffectiveBinaryConfig, resolve_binary_config
from muxtools.utils import binaries as manager
from muxtools.utils.binaries import operations, runner


ENVIRONMENT_VARIABLES = (
    "MUXTOOLS_BINARIES_GLOBAL_PATH",
    "MUXTOOLS_BINARIES_MANAGED_GLOBAL",
    "MUXTOOLS_BINARIES_PACKAGES",
)


@pytest.fixture(autouse=True)
def clean_binary_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_environment_sync_uses_normal_manager_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "global"
    monkeypatch.setenv("MUXTOOLS_BINARIES_MANAGED_GLOBAL", "1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_PACKAGES", "tool==1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_GLOBAL_PATH", str(root))
    catalog = {"packages": {"tool": {"versions": {"1": {"version": "1", "version_code": 1}}}}}
    installed_roots: list[Path] = []
    monkeypatch.setattr(operations, "load_catalog", lambda offline=False: catalog)
    monkeypatch.setattr(operations, "installed", lambda path: [])

    def install(spec: manager.Spec, catalog: dict[str, object], path: Path) -> dict[str, object]:
        installed_roots.append(path)
        return {"name": spec.name, "version": "1", "version_code": 1}

    monkeypatch.setattr(operations, "install", install)
    config = resolve_binary_config(None)
    assert config is not None
    assert manager.sync(config) == [manager.SyncResult("tool", "installed", "1")]
    assert installed_roots == [root]


def test_cli_sync_accepts_environment_config(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("MUXTOOLS_BINARIES_MANAGED_GLOBAL", "1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_PACKAGES", "tool==1")
    monkeypatch.setattr(cli, "discover_config", lambda: None)
    received: list[tuple[EffectiveBinaryConfig, bool]] = []

    def sync(config: EffectiveBinaryConfig, offline: bool = False) -> list[manager.SyncResult]:
        received.append((config, offline))
        return [manager.SyncResult("tool", "existing", "1")]

    monkeypatch.setattr(manager, "sync", sync)
    cli.sync(offline=True)
    assert received == [(EffectiveBinaryConfig("global", ["tool==1"]), True)]
    assert capsys.readouterr().out == "• tool 1 · already installed globally\n"


def test_environment_runtime_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "global"
    directory = root / "tool" / "weird-1"
    directory.mkdir(parents=True)
    executable = directory / "tool"
    executable.write_bytes(b"binary")
    (directory / ".metadata.toml").write_text('name = "tool"\nversion = "weird-1"\nversion_code = 7\n[binaries]\ntool = "tool"\n', encoding="utf-8")
    catalog = {"packages": {"tool": {"provides": ["tool"], "versions": {"weird-1": {"version_code": 7}}}}}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MUXTOOLS_BINARIES_MANAGED_GLOBAL", "1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_PACKAGES", "tool==weird-1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_GLOBAL_PATH", str(root))
    monkeypatch.setattr(runner, "load_catalog", lambda offline=False: catalog)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)

    assert manager.get_managed_executable("tool") == str(executable)
    assert manager.get_managed_executable("undeclared") is None


def test_environment_list_marks_selected_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "global"
    directory = root / "tool" / "1"
    directory.mkdir(parents=True)
    (directory / "tool").write_bytes(b"binary")
    (directory / ".metadata.toml").write_text('name = "tool"\nversion = "1"\nversion_code = 1\n[binaries]\ntool = "tool"\n', encoding="utf-8")
    catalog = {"packages": {"tool": {"provides": ["tool"], "versions": {"1": {"version_code": 1}}}}}
    monkeypatch.setenv("MUXTOOLS_BINARIES_MANAGED_GLOBAL", "1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_PACKAGES", "tool==1")
    monkeypatch.setenv("MUXTOOLS_BINARIES_GLOBAL_PATH", str(root))
    monkeypatch.setattr(cli, "discover_config", lambda: None)
    monkeypatch.setattr(manager, "load_catalog", lambda offline=True: catalog)

    cli.list_binaries()

    assert capsys.readouterr().out.splitlines() == [
        "Environment binaries (global)",
        "tool: 1*",
        "* selected by the environment configuration",
    ]
