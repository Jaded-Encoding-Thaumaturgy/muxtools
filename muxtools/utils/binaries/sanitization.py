import re
import platform
import tomllib
from collections.abc import Sequence
from typing import Any
from pathlib import Path

from .types import Spec

SPEC_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:(==|!=|>=|<=|>|<)(\S+))?$")

__all__ = [
    "parse_spec",
    "target_name",
    "version_code",
    "_installed_metadata",
    "satisfies",
    "resolve_name",
    "resolve_installed_name",
    "managed_install_directory",
]


def parse_spec(value: str) -> Spec:
    match = SPEC_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid package spec: {value!r}")
    return Spec(*match.groups())


def resolve_name(name: str, catalog: dict[str, Any]) -> str:
    packages = catalog["packages"]
    if name in packages:
        return name
    providers = [package for package, data in packages.items() if name in data.get("provides", [])]
    if not providers:
        raise ValueError(f"No package or provided binary named {name!r} exists in the catalog")
    return min(providers, key=lambda value: (len(value), value))


def resolve_installed_name(name: str, items: Sequence[dict[str, Any]], catalog: dict[str, Any] | None = None) -> str:
    """Resolve an executable alias using the catalog or installed metadata."""
    if catalog:
        try:
            return resolve_name(name, catalog)
        except ValueError:
            pass
    providers = {item["name"] for item in items if item["name"] == name or name in item.get("binaries", {})}
    return min(providers, key=lambda value: (len(value), value)) if providers else name


def managed_install_directory(root: Path, item: dict[str, Any]) -> Path:
    """Validate a metadata entry before removing its installation directory."""
    directory = Path(item["_path"])
    if directory.parent.parent != root or (directory.parent.name, directory.name) != (item.get("name"), item.get("version")):
        raise ValueError(f"Unsafe installed binary path: {directory}")
    if directory.parent.is_symlink() or directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Unsafe installed binary path: {directory}")
    return directory


def target_name() -> str:
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    arch = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    return f"{system}-{arch}"


def version_code(spec: Spec, package: dict[str, Any], root: Path) -> int | None:
    if spec.version is None:
        return None
    version = package.get("versions", {}).get(spec.version)
    if version is not None:
        return version["version_code"]
    for item in _installed_metadata(root, spec.name):
        if item.get("version") == spec.version:
            return item["version_code"]
    raise ValueError(f"Unknown catalog version {spec.version!r} for {spec.name}")


def _installed_metadata(root: Path, name: str | None = None) -> list[dict[str, Any]]:
    result = []
    for metadata_file in root.glob("*/*/.metadata.toml"):
        try:
            data = tomllib.loads(metadata_file.read_text(encoding="utf-8"))
            if isinstance(data.get("version_code"), int) and (name is None or data.get("name") == name):
                data["_path"] = str(metadata_file.parent)
                result.append(data)
        except (OSError, tomllib.TOMLDecodeError):
            continue
    return result


def satisfies(code: int, operator: str | None, required: int | None) -> bool:
    if operator is None or required is None:
        return True
    return {
        "==": code == required,
        "!=": code != required,
        ">=": code >= required,
        "<=": code <= required,
        ">": code > required,
        "<": code < required,
    }[operator]
