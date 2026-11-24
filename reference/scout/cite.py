"""Stage 04 — citation accuracy. Reference implementation.

The four mechanical checks are separate because each is fixed differently:

  unresolved      the citation was invented          -> check the citation exists
  unread          it exists, was never opened        -> log the reads and compare
  not-in-source   the quote was paraphrased          -> quote, do not summarise
  stale           the source is superseded           -> carry the obsoleted-by relation
  weak            it does not bear on the question   -> this is the judgment

The verifier is given the question, the corpus and the read set. It is never given the gold
labels; the report compares its decisions against them afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corpus import Document, Section
from .search import Index
from .subagent import Sentence
from .text import content_terms, normalise, overlap, sentences as split_sentences

MIN_RELEVANCE = 0.20


@dataclass(frozen=True)
class Check:
    sentence: Sentence
    kept: bool
    reason: str
    relevance: float


@dataclass(frozen=True)
class CitationReport:
    checks: tuple[Check, ...]

    @property
    def kept(self) -> tuple[Sentence, ...]:
        return tuple(check.sentence for check in self.checks if check.kept)

    def count(self, reason: str) -> int:
        return sum(1 for check in self.checks if check.reason == reason)


def relevance(claim: str, question: str, index: Index) -> float:
    question_terms = set(content_terms(question))
    claim_terms = set(content_terms(claim))
    if not question_terms:
        return 0.0
    total = sum(index.idf(term) for term in question_terms)
    if total <= 0:
        return 0.0
    shared = sum(index.idf(term) for term in question_terms & claim_terms)
    return shared / total


def best_quote(claim: str, section: Section) -> tuple[float, str]:
    best = (0.0, "")
    for candidate in split_sentences(section.text):
        score = overlap(claim, candidate)
        if score > best[0]:
            best = (score, candidate)
    return best


def verify(
    sentence: Sentence,
    *,
    question: str,
    sections: dict[str, Section],
    documents: dict[str, Document],
    reads: set[str],
    index: Index,
    min_relevance: float = MIN_RELEVANCE,
) -> Check:
    section = sections.get(sentence.section)
    if section is None:
        return Check(sentence, False, "unresolved", 0.0)

    if section.id not in reads:
        return Check(sentence, False, "unread", 0.0)

    if normalise(sentence.text) not in normalise(section.text):
        return Check(sentence, False, "not-in-source", 0.0)

    document = documents[section.document]
    if not document.current:
        return Check(sentence, False, "stale", 0.0)

    score = relevance(sentence.text, question, index)
    if score < min_relevance:
        return Check(sentence, False, "weak", score)

    return Check(sentence, True, "supported", score)


def check_answer(
    answer: tuple[Sentence, ...],
    *,
    question: str,
    sections: dict[str, Section],
    documents: dict[str, Document],
    reads: set[str],
    index: Index,
    min_relevance: float = MIN_RELEVANCE,
) -> CitationReport:
    return CitationReport(
        checks=tuple(
            verify(
                sentence,
                question=question,
                sections=sections,
                documents=documents,
                reads=reads,
                index=index,
                min_relevance=min_relevance,
            )
            for sentence in answer
        )
    )


def summarise(report: CitationReport, *, gold: set[str] | None = None) -> dict[str, float]:
    kept = report.kept
    result: dict[str, float] = {
        "claims": len(report.checks),
        "kept": len(kept),
        "stale": sum(1 for check in report.checks if check.kept and check.reason == "stale"),
        "unresolved": report.count("unresolved"),
        "unread": report.count("unread"),
    }
    if gold is not None:
        cited = {sentence.section for sentence in kept}
        result["precision"] = len(cited & gold) / len(kept) if kept else 0.0
        result["coverage"] = len(cited & gold) / len(gold) if gold else 0.0
        result["false_drops"] = sum(
            1 for check in report.checks if not check.kept and check.sentence.section in gold
        )
    return result
