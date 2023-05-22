import os
from pathlib import Path

from ..utils.download import get_executable


def has_arch_resampler() -> bool:
    aegicli = Path(get_executable("aegisub-cli", False))
    sourcedir = Path(aegicli.parent, "automation")
    check = [sourcedir]

    if os.name == "nt":
        check.append(Path(os.getenv("APPDATA"), "Aegisub", "automation"))
    else:
        check.append(Path(Path.home(), ".aegisub", "automation"))

    for d in check:
        for f in d.rglob("*"):
            if f.name.lower() == "arch.resample.moon":
                return True

    return False
