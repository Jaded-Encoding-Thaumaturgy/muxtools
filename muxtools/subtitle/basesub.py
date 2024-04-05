from abc import ABC
from ass import Document, parse as parseDoc
from datetime import timedelta
from collections.abc import Callable

from ..utils.glob import GlobSearch
from ..utils.types import PathLike
from ..muxing.muxfiles import MuxingFile


class _Line:
    TYPE: str
    layer: int
    start: timedelta
    end: timedelta
    style: str
    name: str
    margin_l: int
    margin_r: int
    margin_v: int
    effect: str
    text: str


class BaseSubFile(ABC, MuxingFile):
    def _read_doc(self, file: PathLike | None = None) -> Document:
        with open(self.file if not file else file, "r", encoding=self.encoding) as reader:
            doc = parseDoc(reader)
            self.__fix_style_definition(doc)
            return doc

    def _update_doc(self, doc: Document):
        with open(self.file, "w", encoding=self.encoding) as writer:
            doc.dump_file(writer)

    def __fix_style_definition(self, doc: Document):
        fields: list[str] = doc.styles.field_order
        valid_casing = [
            "Name",
            "Fontname",
            "Fontsize",
            "PrimaryColour",
            "SecondaryColour",
            "OutlineColour",
            "BackColour",
            "Bold",
            "Italic",
            "Underline",
            "StrikeOut",
            "ScaleX",
            "ScaleY",
            "Spacing",
            "Angle",
            "BorderStyle",
            "Outline",
            "Shadow",
            "Alignment",
            "MarginL",
            "MarginR",
            "MarginV",
            "Encoding",
        ]

        for i, f in enumerate(fields):
            for valid in valid_casing:
                if f.casefold() == valid.casefold():
                    fields[i] = valid
                    break

        setattr(doc.styles, "field_order", fields)

    def manipulate_lines(self, func: Callable[[list[_Line]], list[_Line] | None]) -> None:
        doc = self._read_doc()
        returned = func(doc.events)  # type: ignore
        if returned:
            doc.events = returned
        self._update_doc(doc)
