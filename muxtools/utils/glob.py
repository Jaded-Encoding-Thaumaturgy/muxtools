import os
from pathlib import Path
from .types import PathLike

__all__ = ["GlobSearch"]


class GlobSearch:
    paths: list[Path]

    def __init__(
        self,
        pattern: str,
        allow_multiple: bool = False,
        dir: PathLike = None,
        recursive: bool = True,
    ) -> None:
        """
        Glob Pattern based search for files

        :param pattern:         Glob pattern
        :param allow_multiple:  Will return all file matches if True and only the first if False
        :param dir:             Directory to run the search in. Defaults to current working dir.
        :param recursive:       Search recursively
        """
        self.paths = []
        dir = Path(dir) if isinstance(dir, str) else dir

        if dir is None:
            dir = Path(os.getcwd()).resolve()

        search = dir.rglob(pattern) if recursive else dir.glob(pattern)

        for f in search:
            self.paths.append(f)

            if not allow_multiple:
                break
