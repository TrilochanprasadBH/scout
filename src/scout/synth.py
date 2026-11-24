"""Stage 05 — synthesis.

Read `stages/05_synthesis/README.md` first.

Stage 02 returns findings: several workers, each with sentences and the sections they came from.
The naive answer is to join them. That produces an answer that repeats itself, keeps both sides of
a superseded rule, and has no single author.

This stage produces one answer from many findings:

  * deduplicate by text, keeping the first occurrence and its section
  * detect authority conflicts — two candidates whose documents stand in an obsoleted-by relation
  * drop the superseded side, and record that you did
  * call the model exactly once, after the deterministic preparation

The writer is single. That is the rule this stage exists to enforce in code rather than in a
diagram.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corpus import Document
from .model import Model
from .subagent import Finding, Sentence

# An answer longer than this is a document. Six sentences is roughly one per facet, with slack.
MAX_SENTENCES = 6


@dataclass(frozen=True)
class Candidate:
    """One sentence from one finding, with the finding it came from."""

    text: str
    section: str
    sub_question: str


@dataclass(frozen=True)
class Conflict:
    """Two candidates that cannot both be right, and the one that was dropped."""

    kept: Sentence
    dropped: Sentence
    reason: str


@dataclass(frozen=True)
class Answer:
    """The synthesised answer: what it says, what it dropped, and what it flagged."""

    sentences: tuple[Sentence, ...]
    conflicts: tuple[Conflict, ...]
    duplicates: int
    tokens: int = 0


def candidates(findings: tuple[Finding, ...]) -> tuple[Candidate, ...]:
    """Flatten findings into candidates, in sub-question order.

    Contract: one candidate per sentence; findings must be ordered by `sub_question`, and the
    output order is that order, so the result never depends on completion order.
    """
    raise NotImplementedError("stage 05: implement candidates")


def deduplicate(items: tuple[Candidate, ...]) -> tuple[tuple[Candidate, ...], int]:
    """Drop repeated text, keeping the first.

    Contract:
      - compare on `scout.text.fingerprint`, so case, whitespace and a trailing full stop
        do not defeat the check
      - keep the first occurrence and its section
      - return the surviving candidates in input order, and how many were removed
    """
    raise NotImplementedError("stage 05: implement deduplicate")


def find_conflicts(
    items: tuple[Candidate, ...],
    documents: dict[str, Document],
    sections: dict,
) -> tuple[tuple[Conflict, ...], tuple[Candidate, ...]]:
    """Separate authority conflicts from clean candidates.

    Contract:
      - a conflict is a pair of candidates whose sections belong to two documents where one
        document's `obsoleted_by` names the other
      - the current document's candidate is kept, the superseded one becomes the conflict's
        `dropped`, and the reason names both sections
      - a group larger than two resolves to the current document, and every superseded
        candidate becomes its own conflict entry
      - candidates with no conflict are returned unchanged, in input order
      - deterministic: ties are broken by section id

    This detects supersession, not contradiction. Two current documents that disagree pass
    through untouched, and the lesson says so.
    """
    raise NotImplementedError("stage 05: implement find_conflicts")


def synthesise(
    question: str,
    findings: tuple[Finding, ...],
    model: Model,
    *,
    documents: dict[str, Document],
    sections: dict,
    max_sentences: int = MAX_SENTENCES,
) -> Answer:
    """Write one answer from many findings.

    Contract:
      - flatten with `candidates`, deduplicate, then separate conflicts
      - call the model once, with task `"merge"`, over the remaining candidates only
      - keep at most `max_sentences` of the model's sentences, in the order it returned them
      - every kept sentence keeps its section; nothing is rewritten
      - the answer is the same for the same findings, whatever order they arrived in

    One call is the point. A second call is a second author, and two authors are how an answer
    ends up contradicting itself.
    """
    raise NotImplementedError("stage 05: implement synthesise")


def concatenate(findings: tuple[Finding, ...]) -> Answer:
    """Given: the baseline. Every sentence from every finding, in order, with duplicates.

    This is what "merge the sub-agent results" means if nobody thinks about it, and it is the
    configuration the stage measures against.
    """
    sentences = tuple(
        sentence for finding in findings for sentence in finding.sentences
    )
    return Answer(sentences=sentences, conflicts=(), duplicates=0)
