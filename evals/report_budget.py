#!/usr/bin/env python3
"""Budget report: what a ceiling costs in answers, and what no ceiling costs in money.

    IMPL=reference python evals/report_budget.py
    IMPL=reference python evals/report_budget.py --sweep 2000 4000 8000 16000

Two configurations at each total:

  no budget   run everything, then cut the answer to fit
  budgeted    reserve for the writer, admit whole sub-questions, stop workers at allowance

Columns:

  spend     tokens actually spent, against the ceiling
  over      tokens spent above the ceiling (zero for the budgeted arm, by construction)
  cited     gold sections present in the final answer, as a fraction
  dropped   sub-questions never run, which the system knows and can report
  trimmed   workers that stopped opening sections early
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.baselines_budget import no_budget  # noqa: E402
from scout.budget import run_budgeted  # noqa: E402
from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.stats import mcnemar_exact_p  # noqa: E402

DEFAULT_TOTALS = (3000, 6000, 12000, 24000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", type=int, nargs="*", default=list(DEFAULT_TOTALS))
    parser.add_argument("--split", choices=("dev", "test", "both"), default="both")
    args = parser.parse_args()

    documents = load_corpus(ROOT)
    index = Index(all_sections(documents))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(ROOT / "evals" / "questions.jsonl"))
    subsets = {"dev": dev, "test": test}
    if args.split != "both":
        subsets = {args.split: subsets[args.split]}

    print()
    print(f" implementation {IMPL}")
    print()
    print(
        f" {'split':<5}{'budget':>7} {'arm':<10}{'spend':>7}{'over':>6}"
        f"{'cited':>7}{'answers':>9}{'dropped':>9}{'trimmed':>9}"
    )

    paired: dict[int, tuple[int, int]] = {}
    for name, subset in subsets.items():
        for total in args.sweep:
            # no-budget arm
            spend = over = 0
            cited = answers = dropped = trimmed = n = 0
            per_question = []
            for question in subset:
                if not question.answerable:
                    continue
                n += 1
                built = plan(question.question, model, index, evidence_budget=20)
                findings, answer, spent = no_budget(built, index, model, total)
                spend += spent
                over += max(0, spent - total)
                gold = question.gold_sections("current")
                cited += len({s.section for s in answer} & gold) / len(gold)
                answers += 1 if answer else 0
                dropped += 0
                trimmed += 0
                per_question.append(bool({s.section for s in answer} & gold))
            base_flags = per_question
            print(
                f" {name:<5}{total:>7} {'no budget':<10}{spend / n:>7.0f}{over / n:>6.0f}"
                f"{cited / n:>7.2f}{answers:>6}/{n:<2}{dropped:>9}{trimmed:>9}"
            )

            # budgeted arm
            spend = over = cited = answers = dropped = trimmed = 0
            per_question = []
            for question in subset:
                if not question.answerable:
                    continue
                built = plan(question.question, model, index, evidence_budget=20)
                run = run_budgeted(built, index, model, total)
                spend += run.budget.spent
                over += run.budget.overrun
                gold = question.gold_sections("current")
                found = {s.section for s in run.answer} & gold
                cited += len(found) / len(gold)
                answers += 1 if run.answer else 0
                dropped += len(run.admission.dropped)
                trimmed += len(run.trimmed)
                per_question.append(bool(found))
            print(
                f" {name:<5}{total:>7} {'budgeted':<10}{spend / n:>7.0f}{over / n:>6.0f}"
                f"{cited / n:>7.2f}{answers:>6}/{n:<2}{dropped:>9}{trimmed:>9}"
            )

            gained = sum(1 for a, b in zip(base_flags, per_question) if not a and b)
            lost = sum(1 for a, b in zip(base_flags, per_question) if a and not b)
            paired[total] = (gained, lost)
        print()

    print(" paired, no budget vs budgeted (at least one gold section in the answer)")
    for total, (gained, lost) in paired.items():
        print(
            f"   {total:>6}  budgeted only {gained}, no-budget only {lost},"
            f" p = {mcnemar_exact_p(gained, lost):.2f}"
        )

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
