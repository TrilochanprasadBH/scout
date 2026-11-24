"""The documents, given.

A `Document` is one RFC. A `Section` is one numbered heading and the prose under it, which
is the unit `scout` cites. Section ids are stable strings of the form `rfc9111#5.5`, so a
citation survives reloading, re-indexing, and any change to the search layer.

`corpus/rfc/*.txt` is the cleaned text and `corpus/SOURCES.json` carries the metadata that
cannot be recovered from the text itself: publication date, and which document obsoletes
which. Both are needed, because a citation to a superseded section is a real error and the
project has to be able to see it.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

SECTION_HEADING = re.compile(r"^##\s+(\d+(?:\.\d+)*)\.?\s{2,}(\S.*)$")
DOCUMENT_TITLE = re.compile(r"^# RFC (\d+) — (.+)$")


@dataclass(frozen=True)
class Section:
    """One numbered section, and the prose that belongs to it."""

    id: str
    document: str
    number: str
    heading: str
    text: str

    @property
    def title(self) -> str:
        return f"{self.number}  {self.heading}"


@dataclass(frozen=True)
class Document:
    """One RFC."""

    id: str
    number: int
    title: str
    published: str
    obsoleted_by: str | None
    topic: str
    sections: tuple[Section, ...] = field(default_factory=tuple)

    @property
    def current(self) -> bool:
        """False when a later RFC replaces this one."""
        return self.obsoleted_by is None


def parse_document(text: str, meta: dict) -> Document:
    """Parse one cleaned file into sections.

    The first line carries the title. Every line matching `N.N.  Heading` starts a section;
    prose before the first heading becomes a section called `abstract`.
    """
    lines = text.splitlines()
    match = DOCUMENT_TITLE.match(lines[0]) if lines else None
    if match is None:
        raise ValueError(f"{meta['id']}: missing '# RFC N — Title' line")

    sections: list[Section] = []
    number, heading, body = "abstract", "Abstract", []

    def flush() -> None:
        prose = "\n".join(body).strip()
        if not prose and number == "abstract":
            return
        sections.append(
            Section(
                id=f"{meta['id']}#{number}",
                document=meta["id"],
                number=number,
                heading=heading,
                text=prose,
            )
        )

    for line in lines[1:]:
        found = SECTION_HEADING.match(line)
        if found:
            flush()
            number, heading, body = found.group(1), found.group(2).strip(), []
        else:
            body.append(line)
    flush()

    return Document(
        id=meta["id"],
        number=int(match.group(1)),
        title=match.group(2).strip(),
        published=meta["published"],
        obsoleted_by=meta["obsoleted_by"],
        topic=meta["topic"],
        sections=tuple(sections),
    )


def load_corpus(root: pathlib.Path) -> list[Document]:
    """Load every document, sorted by RFC number so the order never depends on the disk."""
    sources = json.loads((root / "corpus" / "SOURCES.json").read_text(encoding="utf-8"))
    documents: list[Document] = []
    for meta in sorted(sources["documents"], key=lambda item: item["number"]):
        text = (root / meta["file"]).read_text(encoding="utf-8")
        documents.append(parse_document(text, meta))
    return documents


def all_sections(documents: list[Document]) -> list[Section]:
    """Flatten, in a fixed order."""
    return [section for document in documents for section in document.sections]


def section_map(documents: list[Document]) -> dict[str, Section]:
    return {section.id: section for section in all_sections(documents)}


def document_map(documents: list[Document]) -> dict[str, Document]:
    return {document.id: document for document in documents}
