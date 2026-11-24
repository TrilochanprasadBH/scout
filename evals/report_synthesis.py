#!/usr/bin/env python3
"""Synthesis report: what one writer buys over concatenation.

    IMPL=reference python evals/report_synthesis.py
    IMPL=reference python evals/report_synthesis.py --show-errors 3

Both arms start from the same findings: the stage 02 fan-out over the plan's sub-questions.
Only the way findings become an answer differs.

Columns:

  sentences   how long the answer is
  distinct    unique sentences, so `sentences - distinct` is the redundancy
  gold        gold sections present in the answer
  conflicts   supersession conflicts detected
  obsolete    sentences citing a superseded document that survived into the answer
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.stats import mcnemar_exact_p  # noqa: E402
from scout.subagent import run_all  # noqa: E402
from scout.synth import concatenate, synthesise  # noqa: E402
from scout.text import normalise  # noqa: E402

BUDGET = 20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-errors", type=int, default=0)
    args = parser.parse_args()

    documents = load_corpus(ROOT)
    sections = section_map(documents)
    docs = document_map(documents)
    index = Index(list(sections.values()))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(ROOT / "evals" / "questions.jsonl"))

    def findings_for(question):
        built = plan(question.question, model, index, evidence_budget=BUDGET)
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        return run_all(built.sub_questions, index, model, max_reads=per_worker)

    def measure(answer, question):
        texts = [normalise(sentence.text) for sentence in answer.sentences]
        gold = question.gold_sections("current")
        cited = {sentence.section for sentence in answer.sentences}
        obsolete = sum(
            1
            for sentence in answer.sentences
            if sentence.section in sections
            and not docs[sections[sentence.section].document].current
        )
        return {
            "sentences": len(answer.sentences),
            "distinct": len(set(texts)),
            "gold": len(cited & gold),
            "conflicts": len(answer.conflicts),
            "obsolete": obsolete,
            "answers": 1 if answer.sentences else 0,
        }

    print()
    print(f" implementation {IMPL}")
    print()
    print(
        f" {'split':<5}{'arm':<14}{'sentences':>10}{'distinct':>9}{'redundant':>10}"
        f"{'gold':>6}{'conflicts':>10}{'obsolete':>9}"
    )

    rows = {}
    for name, subset in (("dev", dev), ("test", test)):
        totals = {}
        questions = []
        for label in ("concatenate", "synthesise"):
            rows_total = {k: 0 for k in ("sentences", "distinct", "gold", "conflicts", "obsolete", "answers")}
            n = 0
            flags = []
            for question in subset:
                if not question.answerable:
                    continue
                n += 1
                findings = findings_for(question)
                if label == "concatenate":
                    answer = concatenate(findings)
                else:
                    answer = synthesise(
                        question.question,
                        findings,
                        model,
                        documents=docs,
                        sections=sections,
                    )
                row = measure(answer, question)
                for key in rows_total:
                    rows_total[key] += row[key]
                flags.append(row["gold"] > 0)
            totals[label] = rows_total
            questions.append((label, flags, n))
            print(
                f" {name:<5}{label:<14}{rows_total['sentences']:>10}{rows_total['distinct']:>9}"
                f"{rows_total['sentences'] - rows_total['distinct']:>10}"
                f"{rows_total['gold']:>6}{rows_total['conflicts']:>10}{rows_total['obsolete']:>9}"
            )
        rows[name] = questions
        print()

    print(" paired, concatenate vs synthesise (answer cites at least one gold section)")
    for name in ("dev", "test"):
        before = rows[name][0][1]
        after = rows[name][1][1]
        lost = sum(1 for a, b in zip(before, after) if a and not b)
        gained = sum(1 for a, b in zip(before, after) if not a and b)
        print(f"   {name:<5} lost {lost}, gained {gained}, p = {mcnemar_exact_p(gained, lost):.2f}")

    if args.show_errors:
        print()
        print(" conflicts detected")
        for name, subset in (("dev", dev), ("test", test)):
            for question in subset:
                if not question.answerable:
                    continue
                findings = findings_for(question)
                answer = synthesise(
                    question.question, findings, model, documents=docs, sections=sections
                )
                for conflict in answer.conflicts:
                    print(f"   {question.id} {name:4} dropped {conflict.dropped.section}: {conflict.reason}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
