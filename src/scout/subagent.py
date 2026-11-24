"""Stage 02 — read-only sub-agents.

Read `stages/02_subagents/README.md` first.

One sub-question goes to one worker. The worker may search and open sections. It may not write
anything: not the corpus, not a shared buffer, not another worker's state. It returns a
finding, and the orchestrator owns the list.

That restriction is the point of the stage. Research is read-heavy and parallel; the moment a
worker's output changes shared state, the order of completion starts to matter and the run
stops being reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Model
from .plan import SubQuestion
from .search import Hit, Index

# How many sections one worker may open for one sub-question. Opening is what costs context,
# so it is capped separately from how many sections a search may return.
MAX_READS = 4


@dataclass(frozen=True)
class Read:
    """One section a worker opened, and what reading it cost."""

    section: str
    tokens: int


@dataclass(frozen=True)
class Sentence:
    """A claim, and the section it claims to come from."""

    text: str
    section: str


@dataclass(frozen=True)
class Finding:
    """What one worker came back with."""

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
    """The only tools a worker gets.

    There is deliberately no method that changes anything. Not a write to the corpus, not a
    shared scratchpad, not a counter another worker reads. A worker that cannot mutate shared
    state cannot race with another worker, and its output is reproducible on its own.

    `open` records the section, because a citation is only trustworthy if the worker actually
    read the section it cites. Stage 06 checks that against the trace.
    """

    def __init__(self, index: Index) -> None:
        self._index = index
        self._by_id = {section.id: section for section in index.sections}
        self._read: list[Read] = []

    def search(self, query: str, *, k: int = MAX_READS) -> list[Hit]:
        """Search, skipping sections this worker has already opened."""
        return self._index.search(query, k=k, skip=self.read_sections)

    def open(self, section_id: str) -> str:
        """Return the section text and record the read."""
        section = self._by_id[section_id]
        from .text import count

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
    """Execute one sub-question and return what it found.

    Contract:
      - search with `item.query`, then open at most `max_reads` of the hits
      - send the opened passages to the model with task `"answer"`, together with
        `item.question`, and let `max_tokens` cap the reply
      - return the model's sentences as `Sentence` objects, keeping the section each one
        carries; a sentence whose section is not one this worker opened is a bug, and the
        caller is expected to reject it
      - `tokens` is the cost of reading plus the model's reported tokens, because both are
        context a budget has to pay for
      - a worker that produced no sentences is `refused`, and that is a legitimate outcome
      - never raise on an empty search: return a finding with no reads and no sentences

    Determinism: the same sub-question, tools and model give the same finding. No clocks, no
    randomness, and no dependence on how many other workers exist.
    """
    raise NotImplementedError("stage 02: implement run_subagent")


def run_all(
    items: tuple[SubQuestion, ...],
    index: Index,
    model: Model,
    *,
    max_reads: int = MAX_READS,
    schedule: list[str] | None = None,
) -> tuple[Finding, ...]:
    """Run every sub-question, each with its own tools, and return findings in plan order.

    Contract:
      - a fresh `ReadOnlyTools` per sub-question, so no worker can see another's reads
      - if `schedule` is given, execute in that order of sub-question ids; otherwise plan
        order. `schedule` simulates completion order without threads, so the guarantee is
        testable deterministically
      - the returned tuple is always sorted by sub-question id, whatever the schedule
      - a missing entry in `schedule` is an error, and a duplicate is an error

    The sorted return is the whole guarantee. It means the orchestrator's output does not
    depend on which worker finished first, which is the property that lets stage 05 have a
    single writer and stage 06 a stable trace.
    """
    raise NotImplementedError("stage 02: implement run_all")


def coverage(findings: tuple[Finding, ...]) -> set[str]:
    """Every section cited by any finding. Given, so reports agree on the definition."""
    found: set[str] = set()
    for finding in findings:
        found |= finding.cited
    return found


def total_tokens(findings: tuple[Finding, ...]) -> int:
    """Reading plus model tokens across all findings. Given."""
    return sum(finding.tokens for finding in findings)
