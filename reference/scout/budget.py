"""Stage 03 — budget control. Reference implementation.

The mechanism, in the order it acts:

  Budget.reserve        the writer's share leaves the pool before a worker starts
  plan_budget           whole sub-questions are admitted or dropped against that pool
  BudgetedTools.open    a running worker stops at its allowance
  Budget.spend          the only place the ledger changes, and it cannot go negative
  BudgetRun.trimmed     every worker that stopped early is named

What it does not do: retry, borrow from the writer, or shrink a claim to fit. A sentence is
either kept whole or not written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Model
from .plan import Plan, SubQuestion
from .search import Index
from .subagent import Finding, Read, ReadOnlyTools, Sentence
from .text import count

WRITER_RESERVE_RATIO = 0.35
READ_STEPS = (4, 2, 1)


class BudgetExhausted(RuntimeError):
    """A worker ran out of allowance and stopped reading."""


@dataclass
class Budget:
    total: int
    spent: int = 0
    reserved: int = 0

    @property
    def available(self) -> int:
        return max(0, self.total - self.spent - self.reserved)

    @property
    def writer_allowance(self) -> int:
        return max(0, self.total - self.spent)

    @property
    def overrun(self) -> int:
        return max(0, self.spent - self.total)

    def reserve(self, tokens: int) -> None:
        if tokens > self.available:
            raise ValueError(
                f"cannot reserve {tokens} tokens with {self.available} available"
            )
        self.reserved += max(0, tokens)

    def spend(self, tokens: int) -> bool:
        if tokens < 0:
            raise ValueError("cannot spend a negative number of tokens")
        if tokens > self.available:
            return False
        self.spent += tokens
        return True


@dataclass(frozen=True)
class Admission:
    accepted: tuple[SubQuestion, ...]
    dropped: tuple[SubQuestion, ...]
    reads: int
    reason: str = ""


@dataclass(frozen=True)
class BudgetRun:
    budget: Budget
    admission: Admission
    findings: tuple[Finding, ...]
    answer: tuple[Sentence, ...]
    trimmed: tuple[str, ...] = field(default_factory=tuple)


def average_section_tokens(index: Index) -> float:
    """The size of a typical section. Measured, not guessed: the mean, not the median.

    The mean is the right admission estimate because the retriever does not return the median
    section; it returns whatever scored. Using the mean under-estimates for long sections,
    which is why `trimmed` exists.
    """
    sizes = [count(section.text) for section in index.sections]
    return sum(sizes) / len(sizes) if sizes else 0.0


def plan_budget(
    plan: Plan,
    budget: Budget,
    index: Index,
    *,
    max_reply: int = 600,
    read_steps: tuple[int, ...] = READ_STEPS,
) -> Admission:
    typical = average_section_tokens(index)
    for reads in read_steps:
        unit = int(reads * typical) + max_reply
        if unit <= 0:
            continue
        fits = budget.available // unit
        if fits >= 1:
            accepted = plan.sub_questions[:fits]
            dropped = plan.sub_questions[fits:]
            reason = "" if not dropped else f"{len(dropped)} sub-questions did not fit"
            return Admission(accepted=accepted, dropped=dropped, reads=reads, reason=reason)

    return Admission(
        accepted=(),
        dropped=plan.sub_questions,
        reads=0,
        reason=f"no sub-question fits in {budget.available} available tokens",
    )


class BudgetedTools(ReadOnlyTools):
    def __init__(self, index: Index, budget: Budget) -> None:
        super().__init__(index)
        self.budget = budget

    def open(self, section_id: str) -> str:
        section = self._by_id[section_id]
        cost = count(section.text)
        if not self.budget.spend(cost):
            raise BudgetExhausted(section_id)
        self._read.append(Read(section=section_id, tokens=cost))
        return section.text


def _run_one(
    item: SubQuestion,
    index: Index,
    model: Model,
    budget: Budget,
    *,
    max_reads: int,
    max_reply: int,
) -> tuple[Finding, bool]:
    tools = BudgetedTools(index, budget)
    passages: list[dict] = []
    trimmed = False
    for hit in tools.search(item.query, k=max_reads):
        try:
            passages.append({"section": hit.section.id, "text": tools.open(hit.section.id)})
        except BudgetExhausted:
            trimmed = True
            break

    allowance = min(max_reply, budget.available)
    reply = model.complete(
        "answer",
        {"sub_question": item.question, "question": item.question, "passages": passages},
        max_tokens=allowance,
    )
    budget.spend(reply.tokens_out)

    sentences = tuple(
        Sentence(text=str(row.get("text", "")), section=str(row.get("section", "")))
        for row in reply.data.get("sentences", [])
    )
    finding = Finding(
        sub_question=item.id,
        question=item.question,
        sentences=sentences,
        reads=tools.reads,
        tokens=tools.read_tokens + reply.tokens_out,
        prompt_tokens=reply.tokens_in,
        answerable=bool(reply.data.get("answerable", False)),
    )
    return finding, trimmed


def run_budgeted(
    plan: Plan,
    index: Index,
    model: Model,
    total: int,
    *,
    max_reply: int = 600,
    reserve_ratio: float = WRITER_RESERVE_RATIO,
) -> BudgetRun:
    budget = Budget(total=max(0, total))
    reserve = math.ceil(budget.total * reserve_ratio)
    budget.reserve(reserve)

    admission = plan_budget(plan, budget, index, max_reply=max_reply)

    findings = []
    trimmed = []
    for item in admission.accepted:
        finding, was_trimmed = _run_one(
            item, index, model, budget, max_reads=admission.reads, max_reply=max_reply
        )
        findings.append(finding)
        if was_trimmed:
            trimmed.append(item.id)

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
    reply = model.complete("merge", payload, max_tokens=budget.writer_allowance)
    budget.spend(reply.tokens_out)
    answer = tuple(
        Sentence(text=str(row.get("text", "")), section=str(row.get("section", "")))
        for row in reply.data.get("sentences", [])
    )

    return BudgetRun(
        budget=budget,
        admission=admission,
        findings=tuple(findings),
        answer=answer,
        trimmed=tuple(trimmed),
    )
