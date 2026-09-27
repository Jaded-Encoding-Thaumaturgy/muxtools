from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from ...config import ProjectConfig

__all__ = ["Spec", "SyncResult", "RemovalPlan", "RemovalFailure", "RemovalResult"]


@dataclass(frozen=True)
class Spec:
    name: str
    operator: str | None = None
    version: str | None = None

    def __str__(self) -> str:
        return self.name + (self.operator + self.version if self.operator and self.version else "")


@dataclass(frozen=True)
class SyncResult:
    name: str
    state: Literal["system", "existing", "installed"]
    version: str | None = None
    version_unchecked: bool = False


@dataclass(frozen=True)
class RemovalPlan:
    root: Path
    items: tuple[dict[str, Any], ...]
    declarations: tuple[str, ...]
    config: ProjectConfig | None


@dataclass(frozen=True)
class RemovalFailure:
    item: dict[str, Any]
    error: OSError | ValueError


@dataclass(frozen=True)
class RemovalResult:
    removed: tuple[dict[str, Any], ...]
    failed: tuple[RemovalFailure, ...]
    declarations: tuple[str, ...]
