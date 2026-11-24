"""Stage 04 — citation accuracy.

Read `stages/04_citations/README.md` first.

A citation is a claim about a claim. "Session resumption is described in RFC 8446 §4.6.1" asserts
that the section exists, that it says what the answer says, and that it is still the current
document. Each of those can be false independently.

This module checks each sentence of an answer against the corpus and decides whether to keep it.
The check has to use only what the system has: the question, the corpus, and what the run
actually read. It must never look at the gold labels, or the measurement becomes a tautology.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corpus import Document, Section
from .search import Index
from .subagent import Sentence
from .text import content_terms, normalise, sentences as split_sentences

# How much of the question's information weight a claim must carry to count as relevant.
# IDF-weighted, so sharing "the request" proves nothing and sharing "idempotent" proves a lot.
MIN_RELEVANCE = 0.20


@dataclass(frozen=True)
class Check:
    """What happened to one sentence of the answer."""

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
    """Share of the question's IDF weight that the claim carries.

    Given, because the weighting is arithmetic rather than judgment:

        relevance = sum(idf(t) for t in question terms also in claim)
                    / sum(idf(t) for t in question terms)

    A claim that repeats the question's rare words is about the question. A claim that repeats
    only its common words is not, however many words it repeats.
    """
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
    """The sentence of `section` closest to the claim, with a Jaccard overlap score.

    Given. Used for the "not verbatim" check and for the lesson's examples; not used to decide
    relevance, because a paraphrase can share most of its words and still say something the
    section does not.
    """
    from .text import overlap

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
    """Decide whether one sentence may stay in the answer.

    Contract, in this order — the first rule that fires decides the reason:
      1. `unresolved`  the cited section id does not exist in the corpus
      2. `unread`      the section exists but this run never opened it
      3. `not-in-source` the claim text does not appear in the section, after whitespace
                         normalisation, so it was not quoted from it
      4. `stale`       the section belongs to a document that a later document replaces
      5. `weak`        `relevance` is below `min_relevance`
      6. `supported`   none of the above; kept

    The order is not arbitrary. A fabricated quote in a missing section is reported as
    unresolved, because that is the fact a person fixing it needs first.
    """
    raise NotImplementedError("stage 04: implement verify")


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
    """Verify every sentence, in order. Contract: one `Check` per sentence, same order."""
    raise NotImplementedError("stage 04: implement check_answer")


def summarise(report: CitationReport, *, gold: set[str] | None = None) -> dict[str, float]:
    """Turn a report into the numbers the documents quote.

    Given, so that every report and `check_docs.py` agree on the definitions:

      claims        how many sentences were produced
      kept          how many survived
      precision     of the kept claims, the share citing a gold section (needs `gold`)
      coverage      of the gold sections, the share still cited after filtering (needs `gold`)
      stale         kept claims citing an obsolete document, which must be zero
      false_drops   dropped claims that were in fact citing a gold section (needs `gold`)
    """
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
            1
            for check in report.checks
            if not check.kept and check.sentence.section in gold
        )
    return result
