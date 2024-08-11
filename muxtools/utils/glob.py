import os
from pathlib import Path
from .types import PathLike

__all__ = ["GlobSearch"]


class GlobSearch:
    paths: list[Path] = []

    def __init__(
        self,
        pattern: str,
        allow_multiple: bool = False,
        target_dir: PathLike = None,
        recursive: bool = True,
    ) -> None:
        """
        Glob Pattern based search for files

        :param pattern:         Glob pattern
        :param allow_multiple:  Will return all file matches if True and only the first if False
        :param target_dir:      Directory to run the search in. Defaults to current working dir.
        :param recursive:       Search recursively
        """

        target_dir = Path(target_dir) if isinstance(target_dir, str) else target_dir

        if target_dir is None:
            target_dir = Path(os.getcwd()).resolve()

        search = target_dir.rglob(pattern) if recursive else target_dir.glob(pattern)

        for f in search:
            self.paths.append(f)

            if not allow_multiple:
                break
