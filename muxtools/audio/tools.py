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


class AutoExtractor(Extractor):
    def extract_audio(self, fileIn, quiet=True, is_temp=False, force_flac=False):
        raise RuntimeError("AutoExtractor is not a class to be used directly and acts as a special type to be replaced.")


class AutoTrimmer(Trimmer):
    def trim_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True) -> AudioFile:
        raise RuntimeError("AutoTrimmer is not a class to be used directly and acts as a special type to be replaced.")


class AutoEncoder(Encoder):
    def encode_audio(self, fileIn: AudioFile | PathLike, quiet: bool = True, **kwargs) -> AudioFile:
        raise RuntimeError("AutoEncoder is not a class to be used directly and acts as a special type to be replaced.")
