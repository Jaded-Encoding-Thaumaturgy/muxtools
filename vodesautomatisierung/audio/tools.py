from abc import ABC, abstractmethod
from ..utils.files import AudioFile
from ..utils.types import PathLike


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
