"""Catalog-backed managed executable installations."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path, user_data_path
from rich.console import Console

from .sanitization import parse_spec, _installed_metadata, version_code, satisfies, target_name
from .types import Spec, SyncResult
from ...config import ProjectConfig, update_config
from ..download import download_file

CATALOG_URL = "https://github.com/Vodes/muxtools-binaries/releases/download/catalog-v1/versions.json"

__all__ = [
    "scope_path",
    "load_catalog",
    "resolve_name",
    "installed",
    "matching_installed",
    "usable_installed",
    "select_version",
    "_binary_paths",
    "install",
    "add",
    "sync",
    "remove",
]


def scope_path(config: ProjectConfig | None, scope: str | None = None) -> Path:
    mode = scope or (config.mode if config else "global")
    if mode == "local":
        if config is None:
            raise ValueError("Local scope requires a project configuration")
        return config.root / ".muxtools" / "bins"
    if mode == "global":
        return user_data_path("muxtools", appauthor=False) / "bins"
    raise ValueError('Binary management is disabled by prefer = "system"; use --local or --global')


def load_catalog(offline: bool = False) -> dict[str, Any]:
    cache = user_cache_path("muxtools", appauthor=False) / "versions.json"
    if not offline:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache.parent) as work:
            staged = Path(work) / cache.name
            try:
                with Console(stderr=True).status("[cyan]Fetching catalog[/cyan]", spinner="dots"):
                    download_file(CATALOG_URL, staged, show_progress=False)
                catalog = json.loads(staged.read_text(encoding="utf-8"))
                if catalog.get("schema_version") != 1 or not isinstance(catalog.get("packages"), dict):
                    raise ValueError("Invalid binary catalog")
                staged.replace(cache)
                return catalog
            except Exception:
                if not cache.exists():
                    raise
    if not cache.exists():
        raise ValueError("No cached binary catalog is available offline")
    catalog = json.loads(cache.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("packages"), dict):
        raise ValueError("Invalid cached binary catalog")
    return catalog


def resolve_name(name: str, catalog: dict[str, Any]) -> str:
    packages = catalog["packages"]
    if name in packages:
        return name
    providers = [package for package, data in packages.items() if name in data.get("provides", [])]
    if not providers:
        raise ValueError(f"No package or provided binary named {name!r} exists in the catalog")
    return min(providers, key=lambda value: (len(value), value))


def installed(root: Path) -> list[dict[str, Any]]:
    items = _installed_metadata(root)
    if root.exists():
        index = root / "installed.json"
        payload = [{"name": item["name"], "version": item["version"], "version_code": item["version_code"], "path": item["_path"]} for item in items]
        with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False, encoding="utf-8") as output:
            json.dump(payload, output)
            temporary = Path(output.name)
        temporary.replace(index)
    return items


def matching_installed(spec: Spec, package: dict[str, Any], root: Path, items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    required = version_code(spec, package, root)
    return [
        item
        for item in (items if items is not None else installed(root))
        if item["name"] == spec.name and satisfies(item["version_code"], spec.operator, required)
    ]


def usable_installed(spec: Spec, package: dict[str, Any], root: Path, items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    valid = []
    for item in matching_installed(spec, package, root, items):
        try:
            if _binary_paths(item, Path(item["_path"])):
                valid.append(item)
        except ValueError:
            continue
    return valid


def select_version(spec: Spec, package: dict[str, Any], root: Path) -> dict[str, Any]:
    required = version_code(spec, package, root)
    versions = [data for data in package["versions"].values() if satisfies(data["version_code"], spec.operator, required)]
    if not versions:
        raise ValueError(f"No catalog version satisfies {spec}")
    return max(versions, key=lambda data: data["version_code"])


def _binary_paths(metadata: dict[str, Any], directory: Path) -> dict[str, Path]:
    paths = {}
    for name, variants in metadata.get("binaries", {}).items():
        relative = variants.get("baseline") if isinstance(variants, dict) else variants
        if not isinstance(relative, str):
            raise ValueError(f"No baseline executable for {name}")
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError(f"Missing executable {name} in archive")
        paths[name] = path
    return paths


def install(spec: Spec, catalog: dict[str, Any], root: Path) -> dict[str, Any]:
    name = resolve_name(spec.name, catalog)
    spec = Spec(name, spec.operator, spec.version)
    version = select_version(spec, catalog["packages"][name], root)
    target = target_name()
    artifact = version.get("targets", {}).get(target)
    if not artifact:
        raise ValueError(f"No {target} artifact for {name} {version['version']}")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / name / version["version"]
    for item in _installed_metadata(root, name):
        if item.get("version") == version["version"]:
            try:
                if _binary_paths(item, Path(item["_path"])):
                    return item
            except ValueError:
                pass
    with tempfile.TemporaryDirectory(dir=root) as work:
        staged = Path(work)
        archive = staged / f"{name}-{version['version']}.tar.zst"
        download_file(artifact["url"], archive)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        if checksum.lower() != artifact["sha256"].lower():
            raise ValueError(f"SHA256 mismatch for {name} {version['version']}")
        if sys.version_info < (3, 14):
            from backports.zstd import register_shutil

            register_shutil(zip=False)
        unpacked = staged / "package"
        unpacked.mkdir()
        shutil.unpack_archive(archive, unpacked, filter="data")
        metadata = tomllib.loads((unpacked / ".metadata.toml").read_text(encoding="utf-8"))
        if any(
            metadata.get(key) != value
            for key, value in {"name": name, "version": version["version"], "version_code": version["version_code"], "target": target}.items()
        ):
            raise ValueError("Archive metadata does not match catalog")
        paths = _binary_paths(metadata, unpacked)
        if set(paths) != set(artifact["binaries"]):
            raise ValueError("Archive executables do not match catalog")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            backup = staged / "previous"
            destination.replace(backup)
        unpacked.replace(destination)
    installed(root)
    return next(item for item in _installed_metadata(root, name) if item["version"] == version["version"])


def sync(config: ProjectConfig, offline: bool = False) -> list[SyncResult]:
    catalog = load_catalog(offline)
    results = []
    if config.mode == "system":
        for raw in config.packages:
            spec = parse_spec(raw)
            name = resolve_name(spec.name, catalog)
            for binary in catalog["packages"][name].get("provides", []):
                if not shutil.which(binary):
                    raise ValueError(f"Package {name!r} expects {binary!r}, but it was not found on PATH")
            results.append(SyncResult(name, "system", version_unchecked=spec.operator is not None))
        return results
    root = scope_path(config)
    items = installed(root)
    for raw in config.packages:
        spec = parse_spec(raw)
        name = resolve_name(spec.name, catalog)
        canonical = Spec(name, spec.operator, spec.version)
        valid = usable_installed(canonical, catalog["packages"][name], root, items)
        if valid:
            results.append(SyncResult(name, "existing", max(valid, key=lambda item: item["version_code"])["version"]))
        elif offline:
            raise ValueError(f"{name} is missing and cannot be installed offline")
        else:
            item = install(canonical, catalog, root)
            items.append(item)
            results.append(SyncResult(name, "installed", item["version"]))
    return results


def add(
    config: ProjectConfig, specs: list[str], offline: bool = False, catalog: dict[str, Any] | None = None
) -> tuple[ProjectConfig, dict[str, str]]:
    if catalog is None:
        catalog = load_catalog(offline)
    root = scope_path(config) if config.mode != "system" else None
    current = {parse_spec(raw).name: raw for raw in config.packages}
    changes = {}
    versions = {}
    for raw in specs:
        parsed = parse_spec(raw)
        name = resolve_name(parsed.name, catalog)
        spec = Spec(name, parsed.operator, parsed.version)
        if config.mode == "system":
            selected = select_version(spec, catalog["packages"][name], Path())
            for binary in catalog["packages"][name].get("provides", []):
                if not shutil.which(binary):
                    raise ValueError(f"Package {name!r} expects {binary!r}, but it was not found on PATH")
            version = selected["version"]
        else:
            assert root is not None
            if offline:
                matches = usable_installed(spec, catalog["packages"][name], root)
                if not matches:
                    raise ValueError(f"{name} is missing and cannot be installed offline")
                version = max(matches, key=lambda item: item["version_code"])["version"]
            else:
                version = install(spec, catalog, root)["version"]
        resolved = str(spec) if spec.operator else f"{name}=={version}"
        changes[name] = resolved
        versions[name] = version
    current.update(changes)
    return update_config(config.path, packages=list(current.values())), versions


def remove(config: ProjectConfig, names: list[str]) -> ProjectConfig:
    wanted = set(names)
    return update_config(config.path, packages=[raw for raw in config.packages if parse_spec(raw).name not in wanted])
