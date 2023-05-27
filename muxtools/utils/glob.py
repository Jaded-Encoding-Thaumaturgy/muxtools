import os
from pathlib import Path
from .types import PathLike

__all__ = ["GlobSearch"]


class GlobSearch:
    paths: Path | list[Path] = None

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

        dir = Path(dir) if isinstance(dir, str) else dir
        if dir is None:
            dir = Path(os.getcwd()).resolve()

        search = dir.rglob(pattern) if recursive else dir.glob(pattern)
        # print(search)
        for f in search:
            if allow_multiple:
                if self.paths:
                    self.paths.append(f)
                else:
                    init: list[Path] = [
                        f,
                    ]
                    self.paths = init
            else:
                self.paths = f
                break
