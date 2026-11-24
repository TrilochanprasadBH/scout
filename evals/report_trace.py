#!/usr/bin/env python3
"""Trace report: the assembled pipeline, and what its record can answer.

    IMPL=reference python evals/report_trace.py
    IMPL=reference python evals/report_trace.py --show-errors 2

Two tables.

The first is the system as assembled: plan, fan-out, one write, verification, trace. These are
the numbers the project's README quotes, because this is the only pipeline in which every stage
is present.

The second is what the record can answer, against a flat log of the same run:

  completeness  fields an auditor needs are present
  attribution   tokens can be assigned to a named stage
  reconstruct   the answer's citations can be derived from the trace alone
  orphans       kept citations with no recorded read, which should be zero
  localised     a dropped sentence can be traced to the sub-question that produced it
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.baselines_trace import flat_log, flat_metrics  # noqa: E402
from scout.cite import check_answer  # noqa: E402
from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.stats import wilson_interval  # noqa: E402
from scout.subagent import run_all  # noqa: E402
from scout.synth import synthesise  # noqa: E402
from scout.trace import (  # noqa: E402
    attribute,
    completeness,
    locate,
    orphan_citations,
    record,
    reconstruct_citations,
)

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

    def run(question):
        built = plan(question.question, model, index, evidence_budget=BUDGET)
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        findings = run_all(built.sub_questions, index, model, max_reads=per_worker)
        answer = synthesise(
            question.question, findings, model, documents=docs, sections=sections
        )
        reads = set()
        for finding in findings:
            reads |= {read.section for read in finding.reads}
        report = check_answer(
            answer.sentences,
            question=question.question,
            sections=sections,
            documents=docs,
            reads=reads,
            index=index,
        )
        trace = record(question.question, built, findings, answer, report)
        return findings, answer, report, trace, reads

    print()
    print(f" implementation {IMPL}")
    print()
    print(" assembled pipeline")
    print(
        f" {'split':<5}{'answers':>8}{'gold':>7}{'full':>8}  {'95% CI':<14}"
        f"{'precision':>10}{'stale':>7}{'tokens':>8}"
    )

    results = {}
    for name, subset in (("dev", dev), ("test", test)):
        rows = []
        for question in subset:
            if not question.answerable:
                continue
            findings, answer, report, trace, reads = run(question)
            gold = question.gold_sections("current")
            cited = {sentence.section for sentence in report.kept}
            covered = question.facets_covered(cited)
            rows.append(
                {
                    "gold": len(cited & gold) / len(gold) if gold else 0.0,
                    "full": bool(question.facets) and len(covered) == len(question.facets),
                    "precision": len(cited & gold) / len(cited) if cited else 0.0,
                    "stale": sum(
                        1
                        for sentence in report.kept
                        if not docs[sections[sentence.section].document].current
                    ),
                    "tokens": trace.total_tokens,
                }
            )
        n = len(rows)
        full = sum(1 for row in rows if row["full"])
        low, high = wilson_interval(full, n)
        print(
            f" {name:<5}{sum(1 for row in rows if row['gold'] > 0):>5}/{n:<2}"
            f"{sum(row['gold'] for row in rows) / n:>7.2f}{full:>4}/{n:<2}  {low:>6.0%}-{high:<6.0%}"
            f"{sum(row['precision'] for row in rows) / n:>10.0%}"
            f"{sum(row['stale'] for row in rows):>7}"
            f"{sum(row['tokens'] for row in rows) / n:>8.0f}"
        )
        results[name] = rows

    print()
    print(" what the record can answer")
    print(f" {'metric':<15}{'trace':>8}{'flat log':>10}")
    totals = {
        "said": 0.0,
        "completeness": 0.0,
        "attribution": 0.0,
        "reconstruct": 0.0,
        "orphans_found": 0.0,
        "localised": 0.0,
    }
    n = 0
    dropped_total = 0
    for name, subset in (("dev", dev), ("test", test)):
        for question in subset:
            if not question.answerable:
                continue
            n += 1
            findings, answer, report, trace, reads = run(question)

            attributed = (
                attribute(trace, "worker") + attribute(trace, "write") + attribute(trace, "read")
            )
            totals["completeness"] += completeness(trace)
            totals["attribution"] += 1.0 if attributed == trace.total_tokens else 0.0
            totals["reconstruct"] += 1.0 if reconstruct_citations(trace) == {
                sentence.section for sentence in report.kept
            } else 0.0
            totals["orphans_found"] += 0.0 if orphan_citations(trace, sections) else 1.0
            totals["said"] += 1.0 if flat_log(findings, answer) else 0.0

            dropped = [check for check in report.checks if not check.kept]
            for check in dropped:
                span = locate(trace, check.sentence.text)
                if span is not None and span.attributes.get("sub_question") not in (None, "unknown"):
                    totals["localised"] += 1
            dropped_total += len(dropped)

    flat = flat_metrics(flat_log((), type("A", (), {"sentences": ()})()))
    rows = {
        "said": totals["said"] / n,
        "completeness": totals["completeness"] / n,
        "attribution": totals["attribution"] / n,
        "reconstruct": totals["reconstruct"] / n,
        "orphans_found": totals["orphans_found"] / n,
        "localised": totals["localised"] / dropped_total if dropped_total else 1.0,
    }
    for key in ("said", "completeness", "attribution", "reconstruct", "orphans_found", "localised"):
        print(f" {key:<15}{rows[key]:>7.0%}{flat[key]:>10.0%}")

    if args.show_errors:
        print()
        print(" a dropped sentence, traced")
        for question in dev:
            if not question.answerable:
                continue
            findings, answer, report, trace, reads = run(question)
            for check in report.checks:
                if check.kept:
                    continue
                span = locate(trace, check.sentence.text)
                if span is None:
                    continue
                parent = next((s for s in trace.spans if s.id == span.parent), None)
                worker = next(
                    (s for s in trace.by_name("worker") if s.attributes.get("sub_question")
                     == span.attributes.get("sub_question")),
                    None,
                )
                print(f"   {question.id} {check.reason:<13} {check.sentence.section}")
                print(f"        sub-question {span.attributes.get('sub_question')} -> {worker.id if worker else '?'}"
                      f" -> read span {parent.id if parent else '?'}")
                print(f"        {span.attributes.get('text', '')[:90]!r}")
                break
            else:
                continue
            break

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
