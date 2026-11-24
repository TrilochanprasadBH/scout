"""Stage 01 — planning a research question.

Read `stages/01_plan/README.md` first.

A research question is not a search query. "What is the difference between a safe method and
an idempotent method?" contains two questions, and asking it once retrieves the section that
happens to mention both words rather than the two sections that answer it.

This module turns one question into a small, ordered plan of sub-questions. The model
proposes; this code validates, deduplicates, and allocates the evidence budget. Stage 02
executes the plan, stage 03 constrains it, and stage 06 records it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import Model
from .search import Index

# Passages, not sections: one section can be opened several times, and the budget is spent
# on text the model reads. Stage 03 turns this into a hard token budget.
DEFAULT_EVIDENCE_BUDGET = 20
MAX_PARTS = 4


@dataclass(frozen=True)
class SubQuestion:
    """One executable step of a plan.

    `question` is what a person reads; `query` is what the index receives. Keeping them
    separate matters because the readable form contains words that hurt retrieval ("what",
    "does", "the") and the query form loses the wording a human needs to check the plan.
    """

    id: str
    question: str
    query: str


@dataclass(frozen=True)
class Plan:
    """A question, the sub-questions that operationalise it, and the evidence budget."""

    question: str
    sub_questions: tuple[SubQuestion, ...]
    evidence_budget: int = DEFAULT_EVIDENCE_BUDGET
    notes: tuple[str, ...] = field(default_factory=tuple)

    def searches(self) -> int:
        return len(self.sub_questions)


def plan(
    question: str,
    model: Model,
    index: Index,
    *,
    evidence_budget: int = DEFAULT_EVIDENCE_BUDGET,
    max_parts: int = MAX_PARTS,
    anchor: bool = False,
) -> Plan:
    """Build a plan for one research question.

    Contract:
      - ask the model for candidates with task `"plan"`
      - keep the model's sub-questions, but drop any whose query has fewer than two
        content terms, and drop duplicates by query
      - add the whole question as a first sub-question, because decomposition loses
        something and the undivided query is the cheapest insurance against that
      - keep at most `max_parts` sub-questions, numbering them `sq.1`, `sq.2`, ...
      - never exceed `evidence_budget` passages in total; `budget_share` decides the split
      - be deterministic: the same question, model, and index give the same plan

    `anchor=True` adds one extra sub-question built from the question's rarest term. It is
    off by default because it measured *worse* at equal cost: one more search per question,
    and 0.885 -> 0.846 facet coverage on the development split. The ablation is in the stage
    lesson and `evals/report_plan.py` reproduces it. Do not turn it on without re-measuring.

    The plan is allowed to be wrong. Stage 02 measures whether executing it found evidence,
    and stage 03 measures what it cost. A planner that cannot be wrong cannot be measured.
    """
    raise NotImplementedError("stage 01: implement plan")


def budget_share(plan: Plan) -> dict[str, int]:
    """How many passages each sub-question may open.

    Contract:
      - every sub-question gets at least one passage
      - the total is at most `plan.evidence_budget`
      - the remainder goes to the earliest sub-questions, one each, in order
      - a plan with more sub-questions than the budget cannot be satisfied: return one
        passage each anyway and let stage 03 reject it for cost

    Even split is not the best split. It is the one that makes the cost of a plan visible:
    four sub-questions cost four times the searches, and this function is where that shows.
    """
    raise NotImplementedError("stage 01: implement budget_share")


def validate(plan: Plan) -> list[str]:
    """Return the reasons a plan is unusable; an empty list means valid.

    Contract:
      - the plan's question is not blank
      - there is at least one sub-question and at most MAX_PARTS
      - sub-question ids are unique and not blank
      - every sub-question has a readable question and a query with at least one
        content term (`scout.text.content_terms`)
      - no two sub-questions share the same query, ignoring case and spacing

    This is the check a harness runs before it spends money on a plan. It is not a check on
    whether the plan is *good*: that is what the measurement is for.
    """
    raise NotImplementedError("stage 01: implement validate")


def prefixes(plan: Plan) -> list[str]:
    """The distinct query prefixes, for a report that wants to show what was searched.

    Contract: one string per sub-question, in plan order, of the form `id: query`.
    Given, so that every report prints a plan the same way.
    """
    return [f"{item.id}: {item.query}" for item in plan.sub_questions]


def describe(plan: Plan) -> str:
    """A one-line summary: number of sub-questions and the evidence budget."""
    return f"{len(plan.sub_questions)} sub-questions, {plan.evidence_budget} passages"


def as_dict(plan: Plan) -> dict[str, Any]:
    """The plan in a form stage 06 can put in a trace."""
    return {
        "question": plan.question,
        "evidence_budget": plan.evidence_budget,
        "sub_questions": [
            {"id": item.id, "question": item.question, "query": item.query}
            for item in plan.sub_questions
        ],
        "notes": list(plan.notes),
    }
