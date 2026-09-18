import ctypes
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

from muxtools import cli
from muxtools.utils import binaries as manager, download
from muxtools.utils.binaries import Spec, parse_spec, resolve_name, satisfies, version_code
from muxtools.utils.binaries import operations, runner
from muxtools.config import discover_config, init_config, migrate_config, update_config
from muxtools.main import Setup


def test_discovery_precedence_and_toml_preservation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    path = project / "pyproject.toml"
    path.write_text('# keep this comment\n[project]\nname = "example"\n', encoding="utf-8")
    init_config(path)
    update_config(path, {"show_name": "From TOML"}, ["ffmpeg==9.0-weird"])
    monkeypatch.chdir(nested)
    config = discover_config()
    assert config is not None
    assert config.path == path
    assert config.mode == "local"
    assert config.packages == ["ffmpeg==9.0-weird"]
    assert "# keep this comment" in path.read_text(encoding="utf-8")
    assert '[project]\nname = "example"' in path.read_text(encoding="utf-8")
    setup = Setup("02", show_name="Explicit", debug=False)
    assert setup.show_name == "Explicit"
    assert setup.debug is False
    assert setup.out_dir == "premux"
    assert Setup("02", config_path=path).show_name == "From TOML"


def test_migration_retains_ini(tmp_path: Path) -> None:
    source = tmp_path / "config.ini"
    source.write_text(
        "[SETUP]\nshow_name = Old\nallow_binary_download = no\ndebug = false\nwork_dir = scratch\narbitrary_value = woah\n", encoding="utf-8"
    )
    destination = tmp_path / "muxtools.toml"
    config = migrate_config(source, destination)
    assert source.exists()
    assert config.mode == "system"
    assert config.settings.show_name == "Old"
    assert config.settings.debug is False
    assert getattr(config.settings, "arbitrary_value") == "woah"
    assert "\nwork_dir = " not in destination.read_text(encoding="utf-8")


def test_literal_catalog_versions_and_aliases(tmp_path: Path) -> None:
    catalog = {"packages": {"opus-tools": {"provides": ["opusenc"], "versions": {"0.2-libopus-1.6": {"version_code": 37}}}}}
    spec = parse_spec("opusenc>=0.2-libopus-1.6")
    assert resolve_name(spec.name, catalog) == "opus-tools"
    canonical = Spec("opus-tools", spec.operator, spec.version)
    assert version_code(canonical, catalog["packages"]["opus-tools"], tmp_path) == 37
    assert satisfies(38, canonical.operator, 37)
    with pytest.raises(ValueError, match="Unknown catalog version"):
        version_code(Spec("opus-tools", "==", "0.2-libopus-9"), catalog["packages"]["opus-tools"], tmp_path)


def test_fitting_variant_uses_best_available_cpu_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("baseline", "avx2", "avx512", "zn4"):
        (tmp_path / name).write_bytes(name.encode())
    variants = {name: name for name in ("baseline", "avx2", "avx512", "zn4")}
    tiers = list(runner.TIER_FEATURES.values())
    for count, expected in ((0, "baseline"), (2, "avx2"), (3, "avx512"), (4, "zn4")):
        monkeypatch.setattr(runner, "cpu_state", lambda count=count: set().union(*tiers[:count]))
        assert runner._get_fitting_variant(variants, tmp_path) == tmp_path / expected

    (tmp_path / "zn4").unlink()
    assert runner._get_fitting_variant(variants, tmp_path) == tmp_path / "avx512"
    with pytest.raises(ValueError, match="No compatible executable"):
        runner._get_fitting_variant({"baseline": "../outside"}, tmp_path)


def test_zen4_selection_with_cpuinfo_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("avx512", "zn4"):
        (tmp_path / name).write_bytes(b"binary")
    features = set().union(*runner.TIER_FEATURES.values()) - {"mwaitx", "wbnoinvd", "fsgsbase", "clzero"}
    monkeypatch.setattr(runner, "cpu_state", lambda: features)
    assert runner._get_fitting_variant({"avx512": "avx512", "zn4": "zn4"}, tmp_path) == tmp_path / "zn4"


def test_windows_zen4_flags_and_xstate(monkeypatch: pytest.MonkeyPatch) -> None:
    flags = set().union(*runner.TIER_FEATURES.values()) - {"prfchw", "mwaitx", "wbnoinvd", "fsgsbase", "clzero"}
    flags.add("3dnowprefetch")
    monkeypatch.setattr(runner, "get_cpu_info", lambda: {"flags": flags})
    monkeypatch.setattr(runner.sys, "platform", "win32")

    def enabled_xstate() -> int:
        return 0x8E7

    monkeypatch.setattr(ctypes, "WinDLL", lambda _: SimpleNamespace(GetEnabledXStateFeatures=enabled_xstate), raising=False)
    assert runner.supports("zn4", runner.cpu_state())


def test_download_binary_returns_fitting_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_config(tmp_path / "muxtools.toml")
    monkeypatch.chdir(tmp_path)
    for name in ("tool", "tool-avx2"):
        (tmp_path / name).write_bytes(b"binary")
    item = {"_path": str(tmp_path), "binaries": {"tool": {"baseline": "tool", "avx2": "tool-avx2"}}}
    monkeypatch.setattr(operations, "install", lambda spec, catalog, root: item)
    monkeypatch.setattr(operations, "load_catalog", lambda: {})
    monkeypatch.setattr(runner, "cpu_state", lambda: set().union(*list(runner.TIER_FEATURES.values())[:2]))
    assert download.download_binary("tool") == str(tmp_path / "tool-avx2")


def test_install_validates_archive_and_recovers_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = manager.target_name()
    metadata = f'schema_version = 3\nname = "tool"\nversion = "weird-1"\nversion_code = 7\ntarget = "{target}"\n[binaries.tool]\nbaseline = "tool"\n'
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as tar:
        for name, contents in ((".metadata.toml", metadata.encode()), ("tool", b"binary")):
            entry = tarfile.TarInfo(name)
            entry.size = len(contents)
            entry.mode = 0o755 if name == "tool" else 0o644
            tar.addfile(entry, io.BytesIO(contents))
    archive = zstd.compress(archive_bytes.getvalue())
    artifact = {"url": "https://example.test/tool.tar.zst", "sha256": hashlib.sha256(archive).hexdigest(), "binaries": {"tool": {"baseline": "tool"}}}
    catalog = {
        "packages": {
            "tool": {"provides": ["tool"], "versions": {"weird-1": {"version": "weird-1", "version_code": 7, "targets": {target: artifact}}}}
        }
    }
    monkeypatch.setattr(operations, "download_file", lambda url, destination: destination.write_bytes(archive))
    root = tmp_path / "bins"
    item = manager.install(Spec("tool"), catalog, root)
    assert manager._binary_paths(item, Path(item["_path"]))["tool"].read_bytes() == b"binary"
    (root / "installed.json").write_text("broken", encoding="utf-8")
    assert manager.installed(root)[0]["version_code"] == 7
    assert json.loads((root / "installed.json").read_text(encoding="utf-8"))[0]["name"] == "tool"


def test_add_reports_resolved_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = init_config(tmp_path / "muxtools.toml")
    catalog = {"packages": {"x265": {"versions": {"4.2": {"version": "4.2", "version_code": 2}}}}}
    monkeypatch.setattr(operations, "install", lambda spec, catalog, root: {"name": "x265", "version": "4.2"})
    updated, versions = manager.add(config, ["x265"], catalog=catalog)
    assert updated.packages == ["x265==4.2"]
    assert versions == {"x265": "4.2"}


def test_offline_add_uses_installed_metadata_for_uncached_version(tmp_path: Path) -> None:
    config = init_config(tmp_path / "muxtools.toml")
    directory = tmp_path / ".muxtools" / "bins" / "tool" / "local-only"
    directory.mkdir(parents=True)
    (directory / "tool").write_bytes(b"binary")
    (directory / ".metadata.toml").write_text(
        'name = "tool"\nversion = "local-only"\nversion_code = 7\n[binaries]\ntool = "tool"\n', encoding="utf-8"
    )
    catalog = {"packages": {"tool": {"versions": {"old": {"version": "old", "version_code": 1}}}}}

    updated, versions = manager.add(config, ["tool==local-only"], offline=True, catalog=catalog)

    assert updated.packages == ["tool==local-only"]
    assert versions == {"tool": "local-only"}

    (directory / "tool").unlink()
    with pytest.raises(ValueError, match="missing and cannot be installed offline"):
        manager.add(config, ["tool==local-only"], offline=True, catalog=catalog)


def test_sync_distinguishes_existing_and_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    config = init_config(tmp_path / "muxtools.toml")
    config = update_config(config.path, packages=["x265>=4.1", "opus-tools"])
    catalog = {
        "packages": {
            "x265": {"versions": {"4.1": {"version": "4.1", "version_code": 1}}},
            "opus-tools": {"versions": {"1": {"version": "1", "version_code": 1}}},
        }
    }
    existing = {"name": "x265", "version": "4.2", "version_code": 2, "_path": str(tmp_path)}
    monkeypatch.setattr(operations, "load_catalog", lambda offline=False: catalog)
    monkeypatch.setattr(operations, "installed", lambda root: [existing])
    monkeypatch.setattr(operations, "_binary_paths", lambda item, directory: {"x265": tmp_path / "x265"})
    monkeypatch.setattr(operations, "install", lambda spec, catalog, root: {"name": "opus-tools", "version": "1", "version_code": 1})
    monkeypatch.setattr(cli, "discover_config", lambda: config)

    assert manager.sync(config) == [manager.SyncResult("x265", "existing", "4.2"), manager.SyncResult("opus-tools", "installed", "1")]
    cli.sync()
    assert capsys.readouterr().out.splitlines() == ["• x265 4.2 · already installed locally", "✓ opus-tools 1 · installed locally"]

    global_config = update_config(config.path, {"binaries": {"prefer": "global"}})
    monkeypatch.setattr(cli, "discover_config", lambda: global_config)
    monkeypatch.setattr(manager, "sync", lambda config, offline=False: [manager.SyncResult("x265", "existing", "4.2")])
    cli.sync()
    assert capsys.readouterr().out == "• x265 4.2 · already installed globally\n"


def test_video_meta_default_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"video")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.ParsedFile, "from_file", lambda *args: type("Video", (), {"is_video_file": True})())
    received = []
    monkeypatch.setattr(cli, "get_timemeta_from_video", lambda *args: received.append(args))
    cli.video_meta(video)
    assert received[0][2] == tmp_path / "episode_meta.json"


def test_runtime_respects_managed_and_system_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = init_config(tmp_path / "muxtools.toml")
    config = update_config(config.path, packages=["tool==weird-1"])
    catalog = {"packages": {"tool": {"provides": ["tool"], "versions": {"weird-1": {"version_code": 7}}}}}
    monkeypatch.setattr(runner, "load_catalog", lambda offline=False: catalog)
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/system/{name}")
    with pytest.raises(FileNotFoundError, match="binaries sync"):
        manager.get_managed_executable("tool", config)
    assert manager.get_managed_executable("undeclared", config) == "/system/undeclared"
    directory = tmp_path / ".muxtools" / "bins" / "tool" / "weird-1"
    directory.mkdir(parents=True)
    (directory / "tool").write_bytes(b"binary")
    (directory / "tool-avx2").write_bytes(b"optimized")
    (directory / ".metadata.toml").write_text(
        'name = "tool"\nversion = "weird-1"\nversion_code = 7\n[binaries.tool]\nbaseline = "tool"\navx2 = "tool-avx2"\n', encoding="utf-8"
    )
    monkeypatch.setattr(runner, "cpu_state", lambda: set().union(*list(runner.TIER_FEATURES.values())[:2]))
    assert manager.get_managed_executable("tool", config) == str(directory / "tool-avx2")
    monkeypatch.setattr(runner, "cpu_state", set)
    assert manager.get_managed_executable("tool", config) == str(directory / "tool")
    system_config = update_config(config.path, {"binaries": {"prefer": "system"}})
    assert manager.get_managed_executable("tool", system_config) == "/system/tool"
