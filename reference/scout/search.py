"""Lexical search over sections, given.

The stages in this project are about orchestration, not retrieval: planning, sub-agents,
budgets, citations, synthesis, tracing. So retrieval is complete here and the lessons do not
pretend otherwise. `ragkit` is where retrieval is the subject.

BM25, the usual formula:

    score(q, s) = sum over terms t in q of
                    idf(t) * f(t,s) * (k1 + 1) / (f(t,s) + k1 * (1 - b + b * |s| / avgdl))

    idf(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

The limitation is the one that matters for a research agent: this is lexical. A question
about "ticket lifetime" will not find the section that says "session resumption" unless the
words overlap. A dense retriever would, and it is deliberately absent because it needs
either a model call or a trained file. Every recall number in this project is therefore a
floor set by vocabulary mismatch, not a property of the agent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .corpus import Section
from .text import terms

K1 = 1.5
B = 0.75


@dataclass(frozen=True)
class Hit:
    section: Section
    score: float


class Index:
    """An inverted index over sections, with BM25 scoring."""

    def __init__(self, sections: list[Section]) -> None:
        self.sections = list(sections)
        self.postings: dict[str, dict[int, int]] = {}
        self.lengths: list[int] = []
        self.heading_terms: set[str] = set()
        for position, section in enumerate(self.sections):
            counts: dict[str, int] = {}
            for term in terms(f"{section.heading} {section.text}"):
                counts[term] = counts.get(term, 0) + 1
            self.heading_terms.update(terms(section.heading))
            self.lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings.setdefault(term, {})[position] = frequency
        self.average_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, {}))
        n = len(self.sections)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, position: int) -> float:
        total = 0.0
        length = self.lengths[position]
        for term in set(terms(query)):
            frequency = self.postings.get(term, {}).get(position, 0)
            if not frequency:
                continue
            denominator = frequency + K1 * (1 - B + B * length / (self.average_length or 1.0))
            total += self.idf(term) * frequency * (K1 + 1) / denominator
        return total

    def search(self, query: str, k: int = 10, *, skip: set[str] | None = None) -> list[Hit]:
        """Top `k` sections for `query`, best first, ties broken by section id.

        `skip` drops section ids the caller has already read, which is how a sub-agent
        avoids spending its budget on the same passage twice.
        """
        skip = skip or set()
        scored = []
        for position, section in enumerate(self.sections):
            if section.id in skip:
                continue
            value = self.score(query, position)
            if value > 0:
                scored.append((value, section.id, position))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [Hit(self.sections[position], value) for value, _, position in scored[:k]]
