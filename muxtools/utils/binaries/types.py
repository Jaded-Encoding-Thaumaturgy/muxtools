from dataclasses import dataclass
from typing import Literal

__all__ = ["Spec", "SyncResult"]


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
