from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import muxtools
from muxtools import cli
from muxtools.config import init_config, update_config
from muxtools.utils import binaries as manager
from muxtools.utils.binaries import runner


def _install(root: Path, package: str, version: str, version_code: int, **binaries: str) -> Path:
    directory = root / package / version
    directory.mkdir(parents=True)
    for name, relative in binaries.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"binary")
    metadata = [f'name = "{package}"', f'version = "{version}"', f"version_code = {version_code}", "[binaries]"]
    metadata.extend(f'{name} = "{relative}"' for name, relative in binaries.items())
    (directory / ".metadata.toml").write_text("\n".join(metadata) + "\n", encoding="utf-8")
    return directory


@pytest.fixture(autouse=True)
def global_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def no_catalog(offline: bool = False) -> dict[str, object]:
        raise ValueError("no catalog")

    for name in ("MUXTOOLS_BINARIES_MANAGED_GLOBAL", "MUXTOOLS_BINARIES_PACKAGES", "vof_exe_tool", "vof_exe_python"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runner, "discover_config", lambda: None)
    monkeypatch.setattr(runner, "load_catalog", no_catalog)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    root = tmp_path / "global"
    monkeypatch.setenv("MUXTOOLS_BINARIES_GLOBAL_PATH", str(root))
    return root


@pytest.fixture
def configured_providers(global_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    first = _install(global_root, "codec", "1", 1, tool="first")
    second = _install(global_root, "codec-plus", "1", 1, tool="second")
    config = init_config(tmp_path / "muxtools.toml", mode="global")
    config = update_config(config.path, packages=["codec", "codec-plus"])
    monkeypatch.setattr(runner, "discover_config", lambda: config)
    return first / "first", second / "second"


def test_explicit_package_respects_configured_version(global_root: Path, tmp_path: Path) -> None:
    selected = _install(global_root, "codec", "2", 2, tool="tool")
    _install(global_root, "codec", "3", 3, tool="tool")
    config = init_config(tmp_path / "muxtools.toml", mode="global")
    config = update_config(config.path, packages=["codec==2"])

    assert manager.get_managed_executable("tool", config, package="codec") == str(selected / "tool")


def test_explicit_package_selects_undeclared_provider(global_root: Path, tmp_path: Path) -> None:
    selected = _install(global_root, "extra-tools", "9", 9, other="other")
    config = init_config(tmp_path / "muxtools.toml", mode="global")
    config = update_config(config.path, packages=["codec"])

    assert manager.get_managed_executable("other", config, package="extra-tools") == str(selected / "other")


def test_package_context_restores_nested_selection_on_error(configured_providers: tuple[Path, Path]) -> None:
    first, second = configured_providers

    with muxtools.use_binary_package("codec-plus"):
        with pytest.raises(RuntimeError):
            with muxtools.use_binary_package("codec"):
                assert muxtools.get_executable("tool") == str(first)
                raise RuntimeError("restore context")
        assert muxtools.get_executable("tool") == str(second)
    assert muxtools.get_executable("tool") == str(first)


def test_explicit_package_overrides_context(configured_providers: tuple[Path, Path]) -> None:
    first, _ = configured_providers

    with muxtools.use_binary_package("codec-plus"):
        assert muxtools.get_executable("tool", package="codec") == str(first)


def test_package_context_leaves_unrelated_lookups_alone(configured_providers: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/system/{name}")

    with muxtools.use_binary_package("codec-plus"):
        assert muxtools.get_executable("unrelated") == "/system/unrelated"


def test_proxy_uses_latest_version_of_shortest_global_provider(global_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install(global_root, "local-only", "7", 7, standalone="standalone")
    _install(global_root, "a", "1", 1, standalone="standalone")
    latest = _install(global_root, "a", "2", 2, standalone="standalone")
    launched: list[list[str]] = []

    def launch(args: list[str]) -> None:
        launched.append(args)
        raise SystemExit(0)

    monkeypatch.setattr(cli.os, "execv", lambda executable, args: launch(args))
    monkeypatch.setattr(cli.subprocess, "call", launch)
    with pytest.raises(SystemExit):
        cli.app(["proxy", "standalone", "--version"], result_action="return_value")
    assert launched == [[str(latest / "standalone"), "--version"]]


def test_proxy_reports_missing_global_binary() -> None:
    with pytest.raises(SystemExit) as missing:
        cli.app(["proxy", "missing"], result_action="return_value")
    assert missing.value.code == 127


def test_system_mode_rejects_package_selection(tmp_path: Path) -> None:
    config = init_config(tmp_path / "muxtools.toml", mode="system")

    with pytest.raises(ValueError, match="system"):
        manager.get_managed_executable("tool", config, package="codec")


def test_proxy_forwards_raw_arguments_and_child_exit_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "show_args.py"
    script.write_text("import sys\nprint(repr(sys.argv[1:]))\nraise SystemExit(7)\n", encoding="utf-8")
    monkeypatch.setenv("vof_exe_python", sys.executable)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "muxtools",
            "proxy",
            "--package",
            "missing-package",
            "python",
            str(script),
            "--help",
            "--",
            "--package",
            "forwarded",
        ],
        cwd=Path(__file__).parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 7
    assert result.stdout.strip() == repr(["--help", "--", "--package", "forwarded"])
