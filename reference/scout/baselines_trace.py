"""The flat-log baseline for stage 06, given.

The default observability story: log every message, in order, with its text. It answers "what was
said" and nothing else. It cannot say what a stage cost, which read produced a sentence, or which
worker to look at when a sentence is wrong.

It is a real baseline, not a strawman. Most systems start here, and some of them stay here for
years because the log is large enough to feel like a record.
"""

from __future__ import annotations

from .subagent import Finding
from .synth import Answer

Event = tuple[str, str]


def flat_log(findings: tuple[Finding, ...], answer: Answer) -> tuple[Event, ...]:
    """Every event, in order, as (kind, text). No parents, no tokens, no section on a sentence."""
    events: list[Event] = []
    for finding in findings:
        events.append(("worker", finding.question))
        for sentence in finding.sentences:
            events.append(("sentence", sentence.text))
    events.append(("answer", " ".join(sentence.text for sentence in answer.sentences)))
    return tuple(events)


def flat_metrics(events: tuple[Event, ...]) -> dict[str, float]:
    """What a flat log can and cannot report.

    `said` is one because the text is all there. Every other metric is zero by construction: there
    is no token count to attribute, no read record to compare against, and no provenance to
    localise.
    """
    return {
        "said": 1.0 if events else 0.0,
        "completeness": 0.0,
        "attribution": 0.0,
        "reconstruct": 0.0,
        "orphans_found": 0.0,
        "localised": 0.0,
    }
