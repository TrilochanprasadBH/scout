"""Stage 02 — read-only sub-agents. Reference implementation.

The three guarantees worth naming:

  isolation     a worker's read set is its own; `ReadOnlyTools` is constructed per worker
  attribution   every sentence carries the section it was extracted from, and that section
                was opened by the worker that returned it
  order         findings come back sorted by sub-question id, whatever order they finished in

Nothing here spawns a thread. `schedule` simulates completion order, which is enough to test
the property that matters, and it keeps the run deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Model
from .plan import SubQuestion
from .search import Hit, Index
from .text import count

MAX_READS = 4


@dataclass(frozen=True)
class Read:
    section: str
    tokens: int


@dataclass(frozen=True)
class Sentence:
    text: str
    section: str


@dataclass(frozen=True)
class Finding:
    sub_question: str
    question: str
    sentences: tuple[Sentence, ...]
    reads: tuple[Read, ...]
    tokens: int
    prompt_tokens: int
    answerable: bool

    @property
    def refused(self) -> bool:
        return not self.sentences

    @property
    def cited(self) -> frozenset[str]:
        return frozenset(sentence.section for sentence in self.sentences)


class ReadOnlyTools:
    def __init__(self, index: Index) -> None:
        self._index = index
        self._by_id = {section.id: section for section in index.sections}
        self._read: list[Read] = []

    def search(self, query: str, *, k: int = MAX_READS) -> list[Hit]:
        return self._index.search(query, k=k, skip=self.read_sections)

    def open(self, section_id: str) -> str:
        section = self._by_id[section_id]
        self._read.append(Read(section=section_id, tokens=count(section.text)))
        return section.text

    @property
    def read_sections(self) -> set[str]:
        return {read.section for read in self._read}

    @property
    def reads(self) -> tuple[Read, ...]:
        return tuple(self._read)

    @property
    def read_tokens(self) -> int:
        return sum(read.tokens for read in self._read)


def run_subagent(
    item: SubQuestion,
    tools: ReadOnlyTools,
    model: Model,
    *,
    max_reads: int = MAX_READS,
    max_tokens: int = 600,
) -> Finding:
    hits = tools.search(item.query, k=max_reads)
    passages = [
        {"section": hit.section.id, "text": tools.open(hit.section.id)} for hit in hits
    ]
    reply = model.complete(
        "answer",
        {"sub_question": item.question, "question": item.question, "passages": passages},
        max_tokens=max_tokens,
    )
    sentences = tuple(
        Sentence(text=str(row.get("text", "")), section=str(row.get("section", "")))
        for row in reply.data.get("sentences", [])
    )

    return Finding(
        sub_question=item.id,
        question=item.question,
        sentences=sentences,
        reads=tools.reads,
        tokens=tools.read_tokens + reply.tokens,
        prompt_tokens=reply.tokens_in,
        answerable=bool(reply.data.get("answerable", False)),
    )


def run_all(
    items: tuple[SubQuestion, ...],
    index: Index,
    model: Model,
    *,
    max_reads: int = MAX_READS,
    schedule: list[str] | None = None,
) -> tuple[Finding, ...]:
    by_id = {item.id: item for item in items}
    if schedule is None:
        order = [item.id for item in items]
    else:
        if len(set(schedule)) != len(schedule):
            raise ValueError("schedule contains a duplicate id")
        unknown = [key for key in schedule if key not in by_id]
        if unknown:
            raise ValueError(f"schedule names unknown sub-questions: {unknown}")
        if len(schedule) != len(items):
            raise ValueError("schedule must name every sub-question exactly once")
        order = schedule

    findings = []
    for key in order:
        tools = ReadOnlyTools(index)
        findings.append(run_subagent(by_id[key], tools, model, max_reads=max_reads))

    return tuple(sorted(findings, key=lambda finding: finding.sub_question))


def coverage(findings: tuple[Finding, ...]) -> set[str]:
    found: set[str] = set()
    for finding in findings:
        found |= finding.cited
    return found


def total_tokens(findings: tuple[Finding, ...]) -> int:
    return sum(finding.tokens for finding in findings)
