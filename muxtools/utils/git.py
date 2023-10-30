from pathlib import Path

__all__: list[str] = ["gitignore"]


def gitignore(ignored_files: str | list[str] = "") -> None:
    """
    Generate and modify a gitignore file.
    These are used to limit files that get stored in a git instance.

    :param ignored_files:   A list of files to ignore. These get appended to the gitignore file.
                            Not passing any files is a no-op.
    """
    if not ignored_files:
        return

    loc = Path().cwd() / ".gitignore"

    if isinstance(ignored_files, str):
        ignored_files = [ignored_files]

    loc.touch(exist_ok=True)

    with open(loc, "a") as f:
        f.write("\n".join(ignored_files) + "\n")
