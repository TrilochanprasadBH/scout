"""The single-context baseline for stage 02, given.

This is what a careful person writes first: search once, put every passage in one prompt, let
one model call answer the whole question. It is the configuration Cognition argues for, and
it is the right default for short tasks. The stage exists to measure what changes when the
work is split.

`sub_question` is `"all"` on purpose: the baseline has no notion of a facet, so it cannot say
which part of the answer came from which sub-question. That missing label is the difference
the stage measures, and it is not a bug in the baseline.
"""

from __future__ import annotations

from .model import Model
from .search import Index
from .subagent import Finding, Sentence
from .text import count

DEFAULT_K = 20


def single_context(
    question: str,
    index: Index,
    model: Model,
    *,
    k: int = DEFAULT_K,
    max_tokens: int = 1200,
) -> Finding:
    hits = index.search(question, k=k)
    passages = [{"section": hit.section.id, "text": hit.section.text} for hit in hits]
    reading = sum(count(passage["text"]) for passage in passages)
    reply = model.complete(
        "answer", {"question": question, "passages": passages}, max_tokens=max_tokens
    )
    sentences = tuple(
        Sentence(text=str(row.get("text", "")), section=str(row.get("section", "")))
        for row in reply.data.get("sentences", [])
    )
    from .subagent import Read

    return Finding(
        sub_question="all",
        question=question,
        sentences=sentences,
        reads=tuple(Read(section=hit.section.id, tokens=count(hit.section.text)) for hit in hits),
        tokens=reading + reply.tokens,
        prompt_tokens=reply.tokens_in,
        answerable=bool(reply.data.get("answerable", False)),
    )
