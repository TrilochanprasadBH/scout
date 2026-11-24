"""Stage 06 — tracing.

Read `stages/06_tracing/README.md` first.

Everything before this stage produced an answer. Nothing produced a record of how the answer was
produced, which means every earlier failure had to be diagnosed by guessing.

This stage records a tree: the question at the root, then the plan, each worker's search and reads
and answer, the single write, and one span per output sentence carrying the sub-question and section
it came from.

The property worth building is not "we have logs". It is that a specific sentence in the answer can
be traced back to the read that produced it.

    python -c "from scout.trace import locate; print(locate(trace, 'some sentence'))"
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cite import CitationReport
from .corpus import Document, Section
from .plan import Plan
from .subagent import Finding
from .synth import Answer


@dataclass(frozen=True)
class Span:
    """One node of the trace.

    `parent` is None only for the root. `attributes` carries whatever the stage needs: section ids
    read, sentences produced, the sub-question a sentence came from, whether verification kept it.
    """

    id: str
    parent: str | None
    name: str
    tokens: int
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Trace:
    """A whole run, as spans."""

    question: str
    spans: tuple[Span, ...]

    @property
    def root(self) -> Span:
        raise NotImplementedError("stage 06: implement Trace.root")

    @property
    def total_tokens(self) -> int:
        raise NotImplementedError("stage 06: implement Trace.total_tokens")

    def children(self, span_id: str) -> tuple[Span, ...]:
        raise NotImplementedError("stage 06: implement Trace.children")

    def by_name(self, name: str) -> tuple[Span, ...]:
        raise NotImplementedError("stage 06: implement Trace.by_name")


def record(
    question: str,
    plan: Plan,
    findings: tuple[Finding, ...],
    answer: Answer,
    report: CitationReport,
) -> Trace:
    """Build the trace from the artefacts a run already produced.

    Contract:
      - one root span named `"research"` with the question as an attribute
      - one `"plan"` child carrying the sub-question count and the evidence budget
      - for each finding, one `"worker"` child of the plan span with `tokens=finding.tokens`,
        and one `"read"` child per section that worker opened
      - one `"write"` span with `tokens=answer.tokens`, carrying the conflict count and the
        duplicate count
      - one `"sentence"` child of the write span per answer sentence, with attributes
        `section`, `sub_question` (taken from the finding that first produced the text), and
        `kept` (from the citation report)
      - ids are `s1`, `s2`, ... in creation order, so the trace is deterministic
      - attributes contain only JSON-safe values

    The `sub_question` attribute is the one that makes an incident review possible. Without it the
    write span knows it produced a sentence and nothing about where it came from.
    """
    raise NotImplementedError("stage 06: implement record")


def attribute(trace: Trace, name: str) -> int:
    """Tokens spent by spans of one name.

    Contract: sum of `tokens` over spans whose `name` matches. The sum over all names must equal
    `trace.total_tokens` minus the root's own tokens, which are zero.
    """
    raise NotImplementedError("stage 06: implement attribute")


def locate(trace: Trace, text: str) -> Span | None:
    """The sentence span whose text matches, using `scout.text.fingerprint`.

    Contract: return the first matching `"sentence"` span, or None. This is the function an
    incident review calls first.
    """
    raise NotImplementedError("stage 06: implement locate")


def orphan_citations(trace: Trace, sections: dict[str, Section]) -> set[str]:
    """Cited sections that no `"read"` span recorded.

    Contract: compare the `section` of every kept sentence span against the set of `section`
    attributes on `"read"` spans. Anything cited and not read is an orphan.
    """
    raise NotImplementedError("stage 06: implement orphan_citations")


def reconstruct_citations(trace: Trace) -> set[str]:
    """The cited sections, derived from the trace alone, without the answer object.

    Contract: the `section` of every sentence span whose `kept` attribute is true. If this differs
    from the answer's citations, the trace is not a record of the run.
    """
    raise NotImplementedError("stage 06: implement reconstruct_citations")


def completeness(trace: Trace) -> float:
    """Share of the fields an auditor needs that are present.

    Contract: check every span for a non-empty id and name, a parent unless it is the root, a
    non-negative token count, and — for `"sentence"` spans — `section` and `sub_question`
    attributes. Return present / expected in [0, 1]. No trace can score above 1.
    """
    raise NotImplementedError("stage 06: implement completeness")
