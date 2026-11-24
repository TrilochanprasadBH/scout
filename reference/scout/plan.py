"""Stage 01 — planning a research question. Reference implementation.

The model proposes sub-questions. This module does four things the model cannot be trusted
to do, because they are properties of the *search*, not of the language:

  1. it drops candidates that are scaffolding rather than queries
  2. it keeps the undivided question as the first step
  3. it adds one query built from the rarest term in the question
  4. it caps the plan and splits a fixed evidence budget across it

Every one of those is a general heuristic. None of them was tuned against a particular
question, and the stage 01 lesson reports what each is worth on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import Model
from .search import Index
from .text import content_terms

DEFAULT_EVIDENCE_BUDGET = 20
MAX_PARTS = 4
ID_PREFIX = "sq"


@dataclass(frozen=True)
class SubQuestion:
    id: str
    question: str
    query: str


@dataclass(frozen=True)
class Plan:
    question: str
    sub_questions: tuple[SubQuestion, ...]
    evidence_budget: int = DEFAULT_EVIDENCE_BUDGET
    notes: tuple[str, ...] = field(default_factory=tuple)

    def searches(self) -> int:
        return len(self.sub_questions)


def rarest_term(question: str, index: Index, *, prefer_headings: bool = True) -> str:
    """The content term that appears in the fewest sections.

    A rare term is a good anchor: it is the word the answer almost certainly contains and
    the corpus almost never repeats. Ranking by rarity alone has a trap, though. The rarest
    word in a question is often a verb from the question's phrasing ("carries", "tell"),
    which appears nowhere useful. Restricting the candidates to terms the document authors
    used in a heading is a cheap way to prefer the words the corpus is organised around.
    """
    terms_ = list(dict.fromkeys(content_terms(question)))
    if not terms_:
        return ""
    if prefer_headings:
        preferred = [term for term in terms_ if term in index.heading_terms]
        if preferred:
            terms_ = preferred
    ranked = sorted(
        ((len(index.postings.get(term, {})), term) for term in terms_),
        key=lambda item: (item[0] if item[0] else 10**9, item[1]),
    )
    return ranked[0][1]


def plan(
    question: str,
    model: Model,
    index: Index,
    *,
    evidence_budget: int = DEFAULT_EVIDENCE_BUDGET,
    max_parts: int = MAX_PARTS,
    anchor: bool = False,
) -> Plan:
    notes: list[str] = []
    reply = model.complete(
        "plan", {"question": question, "max_parts": max_parts}, max_tokens=700
    )

    proposals: list[tuple[str, str]] = []
    for row in reply.data.get("sub_questions", []):
        readable = str(row.get("question", "")).strip(" ?.")
        query = str(row.get("query", "")).strip()
        if len(content_terms(query)) < 2:
            notes.append(f"dropped a candidate with no usable query: {query!r}")
            continue
        proposals.append((readable or query, query))

    # The undivided question first. Decomposition gains recall on multi-facet questions and
    # loses it on single-facet ones; this step is what keeps the second case from regressing.
    everything = " ".join(dict.fromkeys(content_terms(question)))
    steps: list[tuple[str, str]] = [(question.strip(" ?."), everything)] if everything else []

    seen: set[str] = {everything.lower()}
    for readable, query in proposals:
        key = " ".join(query.lower().split())
        if key in seen:
            notes.append(f"dropped a duplicate query: {query!r}")
            continue
        seen.add(key)
        steps.append((readable, query))

    rare = rarest_term(question, index) if anchor else ""
    queries = {" ".join(query.lower().split()) for _, query in steps}
    if rare and rare.lower() not in queries:
        notes.append(f"added a rare-term anchor: {rare!r}")
        steps.append((rare, rare))

    steps = steps[:max_parts]
    if len(steps) < len(proposals) + 1:
        notes.append(f"capped the plan at {max_parts} sub-questions")

    sub_questions = tuple(
        SubQuestion(id=f"{ID_PREFIX}.{position}", question=readable, query=query)
        for position, (readable, query) in enumerate(steps, start=1)
    )
    if len(sub_questions) > evidence_budget:
        notes.append(
            f"plan costs more searches ({len(sub_questions)}) than the evidence budget "
            f"({evidence_budget}) allows"
        )

    return Plan(
        question=question,
        sub_questions=sub_questions,
        evidence_budget=evidence_budget,
        notes=tuple(notes),
    )


def budget_share(plan: Plan) -> dict[str, int]:
    count = len(plan.sub_questions)
    if count == 0:
        return {}
    base, remainder = divmod(plan.evidence_budget, count)
    return {
        item.id: base + (1 if position < remainder else 0)
        for position, item in enumerate(plan.sub_questions)
    }


def validate(plan: Plan) -> list[str]:
    problems: list[str] = []
    if not plan.question.strip():
        problems.append("the plan has no question")
    if not plan.sub_questions:
        problems.append("the plan has no sub-questions")
    if len(plan.sub_questions) > MAX_PARTS:
        problems.append(f"{len(plan.sub_questions)} sub-questions exceeds {MAX_PARTS}")

    ids = [item.id for item in plan.sub_questions]
    if len(set(ids)) != len(ids):
        problems.append("sub-question ids are not unique")
    if any(not item.id.strip() for item in plan.sub_questions):
        problems.append("a sub-question has a blank id")

    queries: list[str] = []
    for item in plan.sub_questions:
        if not item.question.strip():
            problems.append(f"{item.id}: no readable question")
        if not content_terms(item.query):
            problems.append(f"{item.id}: query has no content terms")
        queries.append(" ".join(item.query.lower().split()))
    if len(set(queries)) != len(queries):
        problems.append("two sub-questions share a query")

    return problems


def prefixes(plan: Plan) -> list[str]:
    return [f"{item.id}: {item.query}" for item in plan.sub_questions]


def describe(plan: Plan) -> str:
    return f"{len(plan.sub_questions)} sub-questions, {plan.evidence_budget} passages"


def as_dict(plan: Plan) -> dict[str, Any]:
    return {
        "question": plan.question,
        "evidence_budget": plan.evidence_budget,
        "sub_questions": [
            {"id": item.id, "question": item.question, "query": item.query}
            for item in plan.sub_questions
        ],
        "notes": list(plan.notes),
    }
