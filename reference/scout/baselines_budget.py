"""The no-budget baseline for stage 03, given.

What most prototypes do: run every sub-question, merge everything, then cut the answer to fit
whatever the context window allows. The cut is at the end, so the claims that survive are the
ones the merge happened to put first, and the claims that are lost are lost silently.

It is not a strawman. It is the behaviour you get from a prompt that says "keep the answer
under 6,000 tokens", which is a request rather than a constraint.
"""

from __future__ import annotations

from .model import Model
from .plan import Plan
from .search import Index
from .subagent import Sentence, run_all
from .text import count

DEFAULT_READS = 4


def no_budget(plan: Plan, index: Index, model: Model, total: int, *, max_reads: int = DEFAULT_READS):
    """Return (findings, answer, spent). The answer is truncated to `total` tokens."""
    findings = run_all(plan.sub_questions, index, model, max_reads=max_reads)
    payload = {
        "question": plan.question,
        "findings": [
            {
                "sub_question": finding.sub_question,
                "sentences": [
                    {"text": sentence.text, "section": sentence.section}
                    for sentence in finding.sentences
                ],
            }
            for finding in findings
        ],
    }
    reply = model.complete("merge", payload, max_tokens=max(total, 64))
    spent = sum(finding.tokens for finding in findings) + reply.tokens

    # The cut: keep sentences until the answer fits the budget, then stop.
    kept: list[Sentence] = []
    used = 0
    for row in reply.data.get("sentences", []):
        cost = count(str(row.get("text", "")))
        if used + cost > total:
            break
        kept.append(Sentence(text=str(row.get("text", "")), section=str(row.get("section", ""))))
        used += cost

    return findings, tuple(kept), spent
