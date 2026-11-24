"""Stage 05 — synthesis. Reference implementation.

The order is the design:

  1. flatten          deterministic, sub-question order
  2. deduplicate      same text twice is one claim, not two
  3. conflicts        authority, before style; the superseded side never reaches the writer
  4. one model call   the only place wording is chosen
  5. cap              six sentences

Steps 1-3 and 5 are arithmetic and comparison. Only step 4 is a model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corpus import Document
from .model import Model
from .subagent import Finding, Sentence
from .text import fingerprint

MAX_SENTENCES = 6


@dataclass(frozen=True)
class Candidate:
    text: str
    section: str
    sub_question: str


@dataclass(frozen=True)
class Conflict:
    kept: Sentence
    dropped: Sentence
    reason: str


@dataclass(frozen=True)
class Answer:
    sentences: tuple[Sentence, ...]
    conflicts: tuple[Conflict, ...]
    duplicates: int
    tokens: int = 0


def candidates(findings: tuple[Finding, ...]) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(text=sentence.text, section=sentence.section, sub_question=finding.sub_question)
        for finding in sorted(findings, key=lambda finding: finding.sub_question)
        for sentence in finding.sentences
    )


def deduplicate(items: tuple[Candidate, ...]) -> tuple[tuple[Candidate, ...], int]:
    seen: set[str] = set()
    kept: list[Candidate] = []
    for item in items:
        key = fingerprint(item.text)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return tuple(kept), len(items) - len(kept)


def _document_of(section_id: str, sections: dict, documents: dict[str, Document]) -> Document | None:
    section = sections.get(section_id)
    if section is None:
        return None
    return documents.get(section.document)


def find_conflicts(
    items: tuple[Candidate, ...],
    documents: dict[str, Document],
    sections: dict,
) -> tuple[tuple[Conflict, ...], tuple[Candidate, ...]]:
    # Group by the pair of documents that supersede each other, if any.
    supersedes: dict[str, str] = {
        document.id: document.obsoleted_by
        for document in documents.values()
        if document.obsoleted_by
    }

    conflicts: list[Conflict] = []
    dropped: set[int] = set()

    for index, item in enumerate(items):
        document = _document_of(item.section, sections, documents)
        if document is None or document.id not in documents:
            continue
        replacement = documents.get(supersedes.get(document.id, ""))
        if replacement is None:
            continue
        # Find a candidate from the replacing document that is about the same sub-question.
        for other_index, other in enumerate(items):
            if other_index == index or other_index in dropped:
                continue
            other_document = _document_of(other.section, sections, documents)
            if other_document is None or other_document.id != replacement.id:
                continue
            if other.sub_question != item.sub_question:
                continue
            conflicts.append(
                Conflict(
                    kept=Sentence(text=other.text, section=other.section),
                    dropped=Sentence(text=item.text, section=item.section),
                    reason=f"{item.section} is superseded by {other.section}",
                )
            )
            dropped.add(index)
            break

    clean = tuple(item for index, item in enumerate(items) if index not in dropped)
    conflicts.sort(key=lambda conflict: (conflict.kept.section, conflict.dropped.section))
    return tuple(conflicts), clean


def synthesise(
    question: str,
    findings: tuple[Finding, ...],
    model: Model,
    *,
    documents: dict[str, Document],
    sections: dict,
    max_sentences: int = MAX_SENTENCES,
) -> Answer:
    flat = candidates(findings)
    unique, duplicates = deduplicate(flat)
    conflicts, clean = find_conflicts(unique, documents, sections)

    payload = {
        "question": question,
        "findings": [
            {
                "sub_question": item.sub_question,
                "sentences": [{"text": item.text, "section": item.section}],
            }
            for item in clean
        ],
    }
    reply = model.complete("merge", payload, max_tokens=1200)

    sentences = tuple(
        Sentence(text=str(row.get("text", "")), section=str(row.get("section", "")))
        for row in reply.data.get("sentences", [])
    )[:max_sentences]

    return Answer(
        sentences=sentences,
        conflicts=conflicts,
        duplicates=duplicates,
        tokens=reply.tokens,
    )


def concatenate(findings: tuple[Finding, ...]) -> Answer:
    sentences = tuple(sentence for finding in findings for sentence in finding.sentences)
    return Answer(sentences=sentences, conflicts=(), duplicates=0)
