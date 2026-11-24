"""Metrics, given so that every stage is measured the same way.

Four numbers, and they are deliberately not blended:

  `facet_coverage`   did the run reach the evidence for each facet of the question
  `span_recall`      how much of the gold evidence was retrieved
  `citation_precision` of the citations produced, how many are supported
  `citation_coverage`  of the claims made, how many carry a supported citation

A single "accuracy" number hides the trade this project is always making: a system that
answers less can have better precision, and a system that answers more can have better
coverage. Both are reported, always, and the errors are split into false answers and false
refusals the way `AGENTS.md` requires.
"""

from __future__ import annotations

from .gold import Question


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def span_recall(question: Question, sections: set[str]) -> float:
    """Fraction of the current gold spans whose section was retrieved.

    Section-level, not phrase-level: a span counts as found when its section is in front of
    the model. Whether the model then picks the right sentence is stage 04's problem, and
    collapsing the two would hide which one failed.
    """
    gold = question.gold_sections("current")
    if not gold:
        return 0.0
    return len(gold & sections) / len(gold)


def facet_coverage(question: Question, sections: set[str]) -> float:
    """Fraction of facets with at least one current span in the retrieved sections."""
    if not question.facets:
        return 0.0
    return len(question.facets_covered(sections)) / len(question.facets)


def answered_correctly(question: Question, sections: set[str], threshold: float = 1.0) -> bool:
    """A question counts as answered when every facet is covered and it was answerable.

    This is the strict version. The reports also print the per-facet number, because a
    single missed facet on a three-facet question is not the same failure as missing all of
    them, and one boolean cannot say that.
    """
    if not question.answerable:
        return False
    return facet_coverage(question, sections) >= threshold


def citations_supported(pairs: list[tuple[bool, bool]]) -> tuple[int, int]:
    """Count (supported, made) from a list of per-claim results."""
    return sum(1 for supported, _ in pairs if supported), len(pairs)
