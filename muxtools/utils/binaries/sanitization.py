import re
import platform
import tomllib
from typing import Any
from pathlib import Path

from .types import Spec

SPEC_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:(==|!=|>=|<=|>|<)(\S+))?$")

__all__ = ["parse_spec", "target_name", "version_code", "_installed_metadata", "satisfies"]


def parse_spec(value: str) -> Spec:
    match = SPEC_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid package spec: {value!r}")
    return Spec(*match.groups())


def target_name() -> str:
    system = platform.system().lower()
    arch = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(arch, arch)
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
