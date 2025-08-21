from abc import ABC, abstractmethod

from ..utils.types import PathLike
from ..muxing.muxfiles import AudioFile
from ..utils.dataclass import CLIKwargs


class HasExtractor(ABC):
    pass


class HasTrimmer(ABC):
    pass


class Extractor(CLIKwargs):
    _no_print = False

    @abstractmethod
    def extract_audio(self, fileIn: PathLike, quiet: bool = True, is_temp: bool = False, force_flac: bool = False) -> AudioFile:
        pass


class Trimmer(CLIKwargs):
    @abstractmethod
    def trim_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True) -> AudioFile:
        pass


class Encoder(CLIKwargs):
    lossless = False

    @abstractmethod
    def encode_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True, **kwargs) -> AudioFile:
        pass


class LosslessEncoder(Encoder):
    lossless = True


class AutoTrimmer(Trimmer):
    def trim_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True) -> AudioFile:
        # Dummy func
        ...


class AutoEncoder(Encoder):
    def encode_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True, **kwargs) -> AudioFile:
        # Dummy func
        ...
