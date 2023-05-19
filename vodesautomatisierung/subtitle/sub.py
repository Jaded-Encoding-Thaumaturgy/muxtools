from ass import Document, parse as parseDoc
from font_collector import AssDocument


from ..utils.log import debug, warn
from ..utils.glob import GlobSearch
from ..utils.files import MuxingFile, ensure_path_exists, make_output

DEFAULT_DIALOGUE_STYLES = ["Default", "Main", "Alt", "Overlap", "Flashback", "Top", "Italics"]


class SubFile(MuxingFile):
    """
    Utility class representing a subtitle file with various functions to run on.

    :param file:            Can be a string, Path object or GlobSearch.
                            If the GlobSearch returns multiple results or if a list was passed it will merge them.

    :param container_delay: Set a container delay used in the muxing process later.
    :param source:          The file this sub originates from, will be set by the constructor.
    :param encoding:        Encoding used for reading and writing the subtitle files.
    """

    encoding = "utf_8_sig"

    def __post_init__(self):
        if isinstance(self.file, GlobSearch):
            self.file = self.file.paths

        if isinstance(self.file, list) and len(self.file) > 1:
            debug("Merging sub files...", self)
            docs: list[Document] = []
            for f in self.file:
                f = ensure_path_exists(f, self)
                with open(f, "r", encoding=self.encoding) as read:
                    docs.append(parseDoc(read))

            main = docs[0]
            existing_styles = [style.name for style in (main.styles)]
            docs.remove(main)

            for doc in docs:
                main.events.extend(doc.events)
                for style in doc.styles:
                    if style.name.casefold() in [s.name.casefold() for s in existing_styles]:
                        warn(f"Ignoring style '{style.name}' due to preexisting style of the same name.", self)
                        continue
                    main.styles.append(style)

            out = make_output(self.file[0], "ass", "merged")
            with open(out, "w", encoding=self.encoding) as writer:
                main.dump_file(writer)

            self.file = out
            debug("Done")
        else:
            self.file = ensure_path_exists(self.file, self)

    def __read_doc(self) -> Document:
        with open(self.file, "r", encoding=self.encoding) as reader:
            return parseDoc(reader)

    def __update_doc(self, doc: Document):
        with open(self.file, "w", encoding=self.encoding) as writer:
            doc.dump_file(writer)

    def clean_styles(self) -> "SubFile":
        """
        Deletes unused styles from the document
        """
        doc = self.__read_doc()
        adoc = AssDocument(doc)
        print(adoc.get_used_style())
        return self
