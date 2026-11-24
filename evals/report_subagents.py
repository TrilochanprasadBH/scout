#!/usr/bin/env python3
"""Sub-agent report: what fan-out buys and what it costs.

    IMPL=reference python evals/report_subagents.py
    IMPL=reference python evals/report_subagents.py --show-errors 2

Two configurations, the same evidence budget:

  single context   one agent, 20 passages, one model call
  fan-out          one worker per sub-question, 4 passages each, isolated read sets

The numbers reported separately, because they trade against each other:

  facet coverage   did the cited sections reach every facet
  precision        of the claims made, how many cite a section that answers the question
  tokens           reading plus model, per question
  max call         the largest prompt any single model call had to carry
  refusal          what happened on the four unanswerable questions
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.baselines_subagent import single_context  # noqa: E402
from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.stats import mcnemar_exact_p, wilson_interval  # noqa: E402
from scout.subagent import run_all  # noqa: E402
from scout.text import count  # noqa: E402

BUDGET = 20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-errors", type=int, default=0)
    args = parser.parse_args()

    documents = load_corpus(ROOT)
    index = Index(all_sections(documents))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(ROOT / "evals" / "questions.jsonl"))

    def run_single(question):
        finding = single_context(question.question, index, model, k=BUDGET)
        return finding, 1

    def run_fanout(question):
        built = plan(question.question, model, index, evidence_budget=BUDGET)
        # Equal reads: the single-context arm reads BUDGET sections in one call, so each
        # worker gets BUDGET / n. Holding this constant is the difference between measuring
        # fan-out and measuring a smaller evidence budget.
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        findings = run_all(built.sub_questions, index, model, max_reads=per_worker)
        return findings, len(findings)

    def evaluate(subset, runner):
        rows = []
        for question in subset:
            result, calls = runner(question)
            findings = result if isinstance(result, tuple) else (result,)
            cited = set()
            sentences = 0
            supported = 0
            tokens = 0
            largest = 0
            for finding in findings:
                cited |= finding.cited
                tokens += finding.tokens
                largest = max(largest, finding.prompt_tokens)
                gold = question.gold_sections("current")
                for sentence in finding.sentences:
                    sentences += 1
                    supported += sentence.section in gold
            covered = question.facets_covered(cited)
            rows.append(
                {
                    "id": question.id,
                    "answerable": question.answerable,
                    "coverage": len(covered) / len(question.facets) if question.facets else 0.0,
                    "full": bool(question.facets) and len(covered) == len(question.facets),
                    "sentences": sentences,
                    "supported": supported,
                    "refused": sentences == 0,
                    "tokens": tokens,
                    "largest": largest,
                    "calls": calls,
                }
            )
        return rows

    def summarise(rows, subset):
        answerable = [row for row in rows if row["answerable"]]
        unanswerable = [row for row in rows if not row["answerable"]]
        n = len(answerable)
        return {
            "coverage": sum(row["coverage"] for row in answerable) / n,
            "full": sum(row["full"] for row in answerable),
            "n": n,
            "tokens": sum(row["tokens"] for row in rows) / max(1, len(rows)),
            "largest": max((row["largest"] for row in rows), default=0),
            "sentences": sum(row["sentences"] for row in answerable),
            "supported": sum(row["supported"] for row in answerable),
            "false_answers": sum(
                1 for row in unanswerable if not row["refused"]
            ),
            "correct_refusals": sum(1 for row in unanswerable if row["refused"]),
            "unanswerable": len(unanswerable),
            "rows": rows,
            "calls": sum(row["calls"] for row in rows) / max(1, len(rows)),
        }

    print()
    print(f" implementation {IMPL}")
    print(f" evidence budget {BUDGET} passages")
    print()
    print(
        f" {'split':<5}{'configuration':<16}{'facet':>7}{'full':>7}  {'95% CI':<14}"
        f"{'cite':>6}{'tokens':>8}{'max prompt':>11}{'refusals':>10}"
    )

    results = {}
    for name, subset in (("dev", dev), ("test", test)):
        results[name] = {}
        for label, runner in (
            ("single context", run_single),
            ("fan-out", run_fanout),
        ):
            summary = summarise(evaluate(subset, runner), subset)
            results[name][label] = summary
            low, high = wilson_interval(summary["full"], summary["n"])
            precision = (
                summary["supported"] / summary["sentences"] if summary["sentences"] else 0.0
            )
            print(
                f" {name:<5}{label:<16}{summary['coverage']:>7.3f}"
                f"{summary['full']:>4}/{summary['n']:<2}  {low:>6.0%}-{high:<6.0%}"
                f"{precision:>6.0%}{summary['tokens']:>8.0f}{summary['largest']:>11.0f}"
                f"{summary['correct_refusals']:>4}/{summary['unanswerable']:<5}"
            )
        print()

    print(" paired, single context vs fan-out (every facet reached)")
    for name in ("dev", "test"):
        base = [row["full"] for row in results[name]["single context"]["rows"] if row["answerable"]]
        fan = [row["full"] for row in results[name]["fan-out"]["rows"] if row["answerable"]]
        n01 = sum(1 for a, b in zip(base, fan) if not a and b)
        n10 = sum(1 for a, b in zip(base, fan) if a and not b)
        print(f"   {name:<5} single only {n10}, fan-out only {n01}, p = {mcnemar_exact_p(n01, n10):.2f}")

    if args.show_errors:
        print()
        print(" unanswerable questions the agent answered anyway")
        for name in ("dev", "test"):
            for row in results[name]["fan-out"]["rows"]:
                if not row["answerable"] and not row["refused"]:
                    print(f"   {row['id']} {name}: {row['sentences']} unsupported sentences")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
