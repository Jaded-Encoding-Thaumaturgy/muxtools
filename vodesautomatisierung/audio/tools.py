import os
import subprocess
from abc import ABC, abstractmethod
from ..utils.files import AudioFile
from ..utils.types import PathLike


def run_commandline(command: str | list[str], quiet: bool = True, shell: bool = False, stdin=subprocess.DEVNULL, **kwargs) -> int:
    if os.name != "nt" and isinstance(command, str):
        shell = True
    if quiet:
        p = subprocess.Popen(command, stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=shell, **kwargs)
    else:
        p = subprocess.Popen(command, stdin=stdin, shell=shell, **kwargs)

    return p.wait()


class HasExtractor(ABC):
    pass


class HasTrimmer(ABC):
    pass


class Extractor(ABC):
    @abstractmethod
    def extract_audio(self, input: PathLike, quiet: bool = True) -> AudioFile:
        pass


class Trimmer(ABC):
    @abstractmethod
    def trim_audio(self, input: AudioFile, quiet: bool = True) -> AudioFile:
        pass


class Encoder(ABC):
    @abstractmethod
    def encode_audio(self, input: AudioFile, quiet: bool = True, **kwargs) -> AudioFile:
        pass
