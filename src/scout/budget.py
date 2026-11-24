"""Stage 03 — budget control.

Read `stages/03_budget/README.md` first.

Stage 02 spends without asking. Every worker searches, opens what it likes, and the writer gets
whatever is left. On a real API that is a bill with no ceiling.

This stage makes the ceiling real, in this order:

  1. reserve tokens for the writer, before any worker runs
  2. admit whole sub-questions while they fit; drop the rest and say which
  3. let a running worker stop opening sections when it reaches its allowance
  4. report the drop, never the silent truncation

The single rule: **a budget that is not enforced in code is a wish.** A prompt that says "use
at most 6,000 tokens" is a request. `Budget.spend` returning False is a constraint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Model
from .plan import Plan, SubQuestion
from .search import Index
from .subagent import Finding, ReadOnlyTools, Sentence

# The writer is reserved first because it is the step that turns findings into an answer. A
# run that spends everything on reading and cannot write has produced notes, not a result.
WRITER_RESERVE_RATIO = 0.35

# Read allowances tried in order when a sub-question does not fit. Degrading the unit of work
# is the right response to a small budget; dropping everything is not.
READ_STEPS = (4, 2, 1)


class BudgetExhausted(RuntimeError):
    """A worker ran out of allowance and stopped reading."""


@dataclass
class Budget:
    """A token ceiling with a reservation and a ledger.

    Contract:
      - `spend(n)` returns False and changes nothing when `n > available`
      - `reserve(n)` raises ValueError when `n > available`
      - `available` is `total - spent - reserved` and never negative
      - `writer_allowance` is `total - spent`, which includes the reservation
      - nothing here raises on a zero or negative total; a budget of zero simply admits
        nothing, and `overrun` reports zero

    The two properties that matter: spend can never make the ledger negative, and the
    reservation cannot be spent by a worker. Everything else is bookkeeping.
    """

    total: int
    spent: int = 0
    reserved: int = 0

    @property
    def available(self) -> int:
        raise NotImplementedError("stage 03: implement Budget.available")

    @property
    def writer_allowance(self) -> int:
        raise NotImplementedError("stage 03: implement Budget.writer_allowance")

    @property
    def overrun(self) -> int:
        raise NotImplementedError("stage 03: implement Budget.overrun")

    def reserve(self, tokens: int) -> None:
        raise NotImplementedError("stage 03: implement Budget.reserve")

    def spend(self, tokens: int) -> bool:
        raise NotImplementedError("stage 03: implement Budget.spend")


@dataclass(frozen=True)
class Admission:
    """Which sub-questions may run, and how many sections each may open."""

    accepted: tuple[SubQuestion, ...]
    dropped: tuple[SubQuestion, ...]
    reads: int
    reason: str = ""


@dataclass(frozen=True)
class BudgetRun:
    """The whole budgeted execution: what ran, what it cost, and what was written."""

    budget: Budget
    admission: Admission
    findings: tuple[Finding, ...]
    answer: tuple[Sentence, ...]
    trimmed: tuple[str, ...] = field(default_factory=tuple)


def plan_budget(
    plan: Plan,
    budget: Budget,
    index: Index,
    *,
    max_reply: int = 600,
    read_steps: tuple[int, ...] = READ_STEPS,
) -> Admission:
    """Decide what to run, before running it.

    Contract:
      - the writer's reserve has already been taken by the caller
      - estimate one sub-question as `reads * average_section_tokens + max_reply`, where the
        average is measured from `index`
      - take whole sub-questions in plan order while they fit in `budget.available`
      - if none fit at `read_steps[0]`, try the next smaller allowance, and so on
      - if nothing fits at the smallest allowance, accept none and explain why in `reason`
      - everything not accepted is in `dropped`, in plan order
      - deterministic: same plan, same budget, same index, same admission

    An estimate is not a guarantee. It is the admission rule, and `Budget.spend` is what
    enforces the ceiling once execution starts. The lesson reports how far apart they were.
    """
    raise NotImplementedError("stage 03: implement plan_budget")


def run_budgeted(
    plan: Plan,
    index: Index,
    model: Model,
    total: int,
    *,
    max_reply: int = 600,
    reserve_ratio: float = WRITER_RESERVE_RATIO,
) -> BudgetRun:
    """Run the plan under a hard ceiling.

    Contract:
      - reserve `ceil(total * reserve_ratio)` for the writer before anything runs
      - admit with `plan_budget`, then run accepted sub-questions in order
      - each worker opens sections until it hits its allowance; a worker that hits it keeps
        what it read and is listed in `trimmed`
      - the model call is capped at `min(max_reply, budget.available)`
      - the writer is one `task="merge"` call, capped at `budget.writer_allowance`
      - `answer` is the writer's sentences, in order, with their sections
      - the ledger never goes negative, and `budget.overrun` is zero

    A run with nothing admitted is a valid outcome: no findings, an empty answer, and a
    `reason`. Refusing to spend is a result, not an error.
    """
    raise NotImplementedError("stage 03: implement run_budgeted")


class BudgetedTools(ReadOnlyTools):
    """Read-only tools that charge the budget before returning text.

    Contract:
      - `open` charges `count(text)` and returns the text
      - when the charge does not fit, raise `BudgetExhausted` and change nothing
      - `search` is free: it returns section ids and scores, not text
    """

    def __init__(self, index: Index, budget: Budget) -> None:
        super().__init__(index)
        self.budget = budget

    def open(self, section_id: str) -> str:
        raise NotImplementedError("stage 03: implement BudgetedTools.open")
