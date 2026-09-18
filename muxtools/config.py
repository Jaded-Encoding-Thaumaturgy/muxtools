"""Project configuration discovery and editing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

BinaryMode = Literal["local", "global", "system"]


class BinarySettings(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    prefer: BinaryMode = "system"
    packages: list[str] = Field(default_factory=list)


class MuxSettings(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    show_name: str = "Example"
    clean_work_dirs: bool = False
    out_dir: str = "premux"
    out_name: str = "$show$ - $ep$ (premux)"
    mkv_title_naming: str = "$show$ - $ep$"
    debug: bool = True
    error_on_danger: bool = False


class ProjectSettings(MuxSettings):
    binaries: BinarySettings = Field(default_factory=BinarySettings)

    @model_validator(mode="before")
    @classmethod
    def reject_runtime_fields(cls, value: Any) -> Any:
        if isinstance(value, dict) and "work_dir" in value:
            raise ValueError("work_dir is runtime-only; pass it to Setup")
        return value


@dataclass(frozen=True)
class ProjectConfig:
    path: Path
    settings: ProjectSettings

    @property
    def root(self) -> Path:
        return self.path.parent

    @property
    def mode(self) -> BinaryMode:
        return self.settings.binaries.prefer

    @property
    def packages(self) -> list[str]:
        return self.settings.binaries.packages


def _section(path: Path) -> tuple[str, ...]:
    if path.name == "pyproject.toml":
        return ("tool", "muxtools")
    if path.name == "muxtools.toml":
        return ("muxtools",)
    raise ValueError("Config must be pyproject.toml or muxtools.toml")


def _read(path: Path) -> Any:
    return tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()


def load_config(path: Path) -> ProjectConfig:
    path = path.resolve()
    doc = _read(path)
    node: Any = doc
    for part in _section(path):
        if part not in node:
            raise ValueError(f"No muxtools configuration in {path}")
        node = node[part]
    return ProjectConfig(path, ProjectSettings.model_validate(node.unwrap()))


def discover_config(start: Path | None = None, explicit: Path | None = None) -> ProjectConfig | None:
    if explicit is not None:
        return load_config(explicit)
    directory = (start or Path.cwd()).resolve()
    if directory.is_file():
        directory = directory.parent
    for parent in (directory, *directory.parents):
        matches = []
        for name in ("pyproject.toml", "muxtools.toml"):
            path = parent / name
            if path.exists():
                doc = _read(path)
                node: Any = doc
                found = True
                for part in _section(path):
                    if part not in node:
                        found = False
                        break
                    node = node[part]
                if found:
                    matches.append(path)
        if len(matches) > 1:
            raise ValueError(f"Ambiguous muxtools configuration in {parent}; select a config explicitly")
        if matches:
            return load_config(matches[0])
    return None


def update_config(path: Path, values: dict[str, Any] | None = None, packages: list[str] | None = None) -> ProjectConfig:
    path = path.resolve()
    doc = _read(path)
    node: Any = doc
    for part in _section(path):
        if part not in node:
            node[part] = tomlkit.table()
        node = node[part]
    for key, value in (values or {}).items():
        if key != "binaries":
            node[key] = value
    if "binaries" not in node:
        node["binaries"] = tomlkit.table()
    binary = node["binaries"]
    for key, value in (values or {}).get("binaries", {}).items():
        binary[key] = value
    if packages is not None:
        binary["packages"] = packages
    settings = ProjectSettings.model_validate(node.unwrap())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return ProjectConfig(path, settings)


def init_config(path: Path, mode: BinaryMode = "local") -> ProjectConfig:
    if path.exists():
        try:
            return load_config(path)
        except ValidationError:
            raise
        except ValueError:
            pass
    defaults = ProjectSettings(binaries=BinarySettings(prefer=mode)).model_dump()
    return update_config(path, defaults)


def migrate_config(source: Path, destination: Path) -> ProjectConfig:
    from configparser import ConfigParser

    parser = ConfigParser()
    if not parser.read(source, encoding="utf-8") or not parser.has_section("SETUP"):
        raise ValueError(f"No [SETUP] section in {source}")
    if destination.exists():
        try:
            load_config(destination)
        except ValidationError:
            raise
        except ValueError:
            pass
        else:
            raise ValueError(f"muxtools configuration already exists in {destination}")
    settings = parser["SETUP"]
    booleans = {"clean_work_dirs", "debug", "error_on_danger"}
    excluded = {"work_dir", "allow_binary_download", "binaries"}
    values: dict[str, Any] = {key: settings.getboolean(key) if key in booleans else settings[key] for key in settings if key not in excluded}
    values["binaries"] = {"prefer": "local" if settings.getboolean("allow_binary_download", fallback=False) else "system", "packages": []}
    return update_config(destination, values)
