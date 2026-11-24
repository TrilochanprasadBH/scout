"""Stage 06 — tracing. Reference implementation.

The trace is built from artefacts the run already had. No instrumentation of the model, no
dependency on timing, and no random ids, so two runs of the same question produce the same trace.

The one non-obvious piece is the provenance of each output sentence. `synthesise` deduplicates
candidates, so the finding that first produced a text is the one that gets credited. That is a
choice: a duplicate removed in stage 05 has no output span, which is correct, because it is not in
the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cite import CitationReport
from .corpus import Document, Section
from .plan import Plan
from .subagent import Finding
from .synth import Answer
from .text import fingerprint


@dataclass(frozen=True)
class Span:
    id: str
    parent: str | None
    name: str
    tokens: int
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Trace:
    question: str
    spans: tuple[Span, ...]

    @property
    def root(self) -> Span:
        return self.spans[0]

    @property
    def total_tokens(self) -> int:
        return sum(span.tokens for span in self.spans)

    def children(self, span_id: str) -> tuple[Span, ...]:
        return tuple(span for span in self.spans if span.parent == span_id)

    def by_name(self, name: str) -> tuple[Span, ...]:
        return tuple(span for span in self.spans if span.name == name)


class _Builder:
    def __init__(self) -> None:
        self.spans: list[Span] = []

    def add(self, parent: str | None, name: str, tokens: int = 0, **attributes) -> str:
        span_id = f"s{len(self.spans) + 1}"
        self.spans.append(
            Span(
                id=span_id,
                parent=parent,
                name=name,
                tokens=tokens,
                attributes={key: value for key, value in attributes.items() if value is not None},
            )
        )
        return span_id


def record(
    question: str,
    plan: Plan,
    findings: tuple[Finding, ...],
    answer: Answer,
    report: CitationReport,
) -> Trace:
    builder = _Builder()
    root = builder.add(None, "research", question=question)
    plan_span = builder.add(
        root,
        "plan",
        sub_questions=len(plan.sub_questions),
        evidence_budget=plan.evidence_budget,
    )

    for finding in findings:
        worker = builder.add(
            plan_span,
            "worker",
            tokens=finding.tokens,
            sub_question=finding.sub_question,
            sentences=len(finding.sentences),
        )
        for read in finding.reads:
            builder.add(worker, "read", tokens=read.tokens, section=read.section)

    writer = builder.add(
        root,
        "write",
        tokens=answer.tokens,
        conflicts=len(answer.conflicts),
        duplicates=answer.duplicates,
    )

    provenance: dict[str, str] = {}
    for finding in findings:
        for sentence in finding.sentences:
            provenance.setdefault(fingerprint(sentence.text), finding.sub_question)

    verdicts = {fingerprint(check.sentence.text): check.kept for check in report.checks}
    for sentence in answer.sentences:
        key = fingerprint(sentence.text)
        builder.add(
            writer,
            "sentence",
            text=sentence.text,
            section=sentence.section,
            sub_question=provenance.get(key, "unknown"),
            kept=verdicts.get(key, False),
        )

    return Trace(question=question, spans=tuple(builder.spans))


def attribute(trace: Trace, name: str) -> int:
    return sum(span.tokens for span in trace.by_name(name))


def locate(trace: Trace, text: str) -> Span | None:
    key = fingerprint(text)
    for span in trace.by_name("sentence"):
        if fingerprint(str(span.attributes.get("text", ""))) == key:
            return span
    return None


def orphan_citations(trace: Trace, sections: dict[str, Section]) -> set[str]:
    read = {str(span.attributes.get("section")) for span in trace.by_name("read")}
    cited = {
        str(span.attributes.get("section"))
        for span in trace.by_name("sentence")
        if span.attributes.get("kept")
    }
    return cited - read


def reconstruct_citations(trace: Trace) -> set[str]:
    return {
        str(span.attributes.get("section"))
        for span in trace.by_name("sentence")
        if span.attributes.get("kept")
    }


def completeness(trace: Trace) -> float:
    present = 0
    expected = 0
    for position, span in enumerate(trace.spans):
        expected += 3
        present += bool(span.id and span.name)
        present += span.parent is not None or position == 0
        present += span.tokens >= 0
        if span.name == "sentence":
            expected += 2
            present += bool(span.attributes.get("section"))
            present += bool(span.attributes.get("sub_question"))
    return present / expected if expected else 0.0
