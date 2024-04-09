from abc import ABC
from ass import Document, parse as parseDoc
from datetime import timedelta
from typing import Any
from collections.abc import Callable
from enum import IntEnum

from ..utils.glob import GlobSearch
from ..utils.log import error, warn
from ..utils.types import PathLike
from ..muxing.muxfiles import MuxingFile

__all__ = ["_Line", "ASSHeader"]


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


class ASSHeader(IntEnum):
    LayoutResX = 1
    LayoutResY = 2
    PlayResX = 3
    PlayResY = 4
    WrapStyle = 5
    ScaledBorderAndShadow = 6
    YCbCr_Matrix = 7

    def validate_input(self, value: str | int | bool | None, caller: Any = None) -> str | int | None:
        if self in range(1, 6) and not isinstance(value, int) and value is not None:
            raise error(f"{self.name} needs to be an integer!", caller)
        if self == 5 and value not in range(3) and value is not None:
            raise error(f"The valid values for {self.name} are 0, 1 and 2.", caller)

        if self == 6 and value is not None:
            if not isinstance(value, bool) and str(value).lower() not in ["yes", "no"]:
                raise error(f"The valid values for {self.name} are 'yes', 'no' or a boolean with the same meaning.", caller)
            if str(value).lower() == "no" or value == False:
                warn(f"There's practically no good reason for {self.name} to be 'no'. Carry on if you are sure.", caller, 1)
            if isinstance(value, bool):
                return "yes" if value else "no"
            return str(value).lower()

        if self == 7 and value is not None:
            if not isinstance(value, str):
                raise error(f"{self.name} needs to be a string!", caller)
            if not value.startswith(("TV.", "PC.")):
                raise error(f"{self.name} needs to start with a range value of either 'TV' or 'PC'!", caller)
            known_matrices = ["601", "709", "240M", "FCC"]
            contains_known = False
            for matrix in known_matrices:
                if matrix in value:
                    contains_known = True
            if not contains_known:
                joined = ", ".join(known_matrices)
                warn(f"{self.name} doesn't contain a known valid matrix! ({joined})", caller, 1)

        return value


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

    def set_header(self, header: str | ASSHeader, value: str | int | bool | None, opened_doc: None | Document = None) -> None:
        doc = opened_doc if opened_doc else self._read_doc()
        functional_headers = ASSHeader._member_map_.items()
        section: dict = doc.sections["Script Info"]
        if isinstance(header, str):
            corr = [
                head
                for name, head in functional_headers
                if name.casefold() == header.casefold() or name.replace("_", " ").casefold() == header.casefold()
            ]
            if corr:
                corr = ASSHeader(corr[0])
                value = corr.validate_input(value, "SubFile.set_header")
                if value is None and corr.name != "YCbCr_Matrix":
                    section.pop(corr.name)
                section.update({corr.name.replace("_", " "): str(value)})
            else:
                section.update({header: str(value)})
        else:
            value = header.validate_input(value, "SubFile.set_header")
            if value is None and header.name != "YCbCr_Matrix":
                if header.name in section.keys():
                    section.pop(header.name)
            else:
                section.update({header.name.replace("_", " "): str(value)})

        if not opened_doc:
            self._update_doc(doc)
