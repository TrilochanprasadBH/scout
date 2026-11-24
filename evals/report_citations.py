#!/usr/bin/env python3
"""Citation report: what verification keeps, what it drops, and what it fails to catch.

    IMPL=reference python evals/report_citations.py
    IMPL=reference python evals/report_citations.py --min-relevance 0.30
    IMPL=reference python evals/report_citations.py --show-errors 4

The pipeline is the stage 03 budgeted run at 12000 tokens. Its answer is checked twice: once
with verification off (keep everything) and once with it on.

The evaluation uses the gold labels. The verifier never sees them: it only gets the question,
the corpus, and the set of sections the run opened. That separation is the difference between
measuring a check and measuring a lookup table.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.budget import run_budgeted  # noqa: E402
from scout.cite import MIN_RELEVANCE, check_answer, summarise  # noqa: E402
from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.stats import mcnemar_exact_p  # noqa: E402

TOTAL = 12000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-relevance", type=float, default=MIN_RELEVANCE)
    parser.add_argument("--show-errors", type=int, default=0)
    parser.add_argument("--sweep", action="store_true", help="precision/coverage against the threshold")
    args = parser.parse_args()

    documents = load_corpus(ROOT)
    sections = section_map(documents)
    docs = document_map(documents)
    index = Index(list(sections.values()))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(ROOT / "evals" / "questions.jsonl"))

    print()
    print(f" implementation {IMPL}")
    print(f" min relevance  {args.min_relevance:.2f}")
    print()
    print(
        f" {'split':<5}{'arm':<12}{'claims':>8}{'kept':>6}{'dropped':>9}{'precision':>11}"
        f"{'gold':>7}{'stale':>7}{'weak':>6}{'false drop':>11}"
    )

    def run(question):
        built = plan(question.question, model, index, evidence_budget=20)
        execution = run_budgeted(built, index, model, TOTAL)
        reads: set[str] = set()
        for finding in execution.findings:
            reads |= {read.section for read in finding.reads}
        if not reads:
            # A writer can repeat a sentence the workers found; if nothing was read there is
            # nothing to verify against, so the read set is the corpus-backed answer's own.
            reads = {sentence.section for sentence in execution.answer}
        report = check_answer(
            execution.answer,
            question=question.question,
            sections=sections,
            documents=docs,
            reads=reads,
            index=index,
            min_relevance=args.min_relevance,
        )
        return execution, reads, report

    results = {}
    for name, subset in (("dev", dev), ("test", test)):
        arms = {
            "unverified": {"claims": 0, "kept": 0, "precision": 0.0, "coverage": 0.0,
                           "stale": 0, "unresolved": 0, "unread": 0, "weak": 0,
                           "false_drops": 0, "flags": []},
            "verified": {"claims": 0, "kept": 0, "precision": 0.0, "coverage": 0.0,
                         "stale": 0, "unresolved": 0, "unread": 0, "weak": 0,
                         "false_drops": 0, "flags": []},
        }
        n = 0
        for question in subset:
            if not question.answerable:
                continue
            n += 1
            execution, reads, report = run(question)
            gold = question.gold_sections("current")

            raw = summarise(report, gold=gold)
            raw["claims"] = len(execution.answer)
            raw["kept"] = len(execution.answer)
            raw["precision"] = (
                len({s.section for s in execution.answer} & gold) / len(execution.answer)
                if execution.answer else 0.0
            )
            raw["coverage"] = (
                len({s.section for s in execution.answer} & gold) / len(gold) if gold else 0.0
            )
            raw["stale"] = sum(
                1 for s in execution.answer
                if s.section in sections and not docs[sections[s.section].document].current
            )
            raw["weak"] = 0
            raw["unread"] = 0
            raw["false_drops"] = 0

            verified = summarise(report, gold=gold)

            for label, row in (("unverified", raw), ("verified", verified)):
                for key in ("claims", "kept", "stale", "unresolved", "unread", "false_drops"):
                    arms[label][key] += row.get(key, 0)
                for key in ("precision", "coverage"):
                    arms[label][key] += row.get(key, 0.0)
                if label == "verified":
                    arms[label]["weak"] += report.count("weak")
            arms["verified"]["flags"].append(bool(verified["kept"]))
            arms["unverified"]["flags"].append(bool(execution.answer))

        for label in ("unverified", "verified"):
            row = arms[label]
            print(
                f" {name:<5}{label:<12}{int(row['claims']):>8}{int(row['kept']):>6}"
                f"{int(row['claims'] - row['kept']):>9}"
                f"{row['precision'] / n:>10.0%}{row['coverage'] / n:>7.0%}"
                f"{int(row['stale']):>7}{int(row['weak']):>6}"
                f"{int(row['false_drops']):>11}"
            )
        detected = sum(
            1
            for question in subset
            if question.answerable
            for check in run(question)[2].checks
            if check.reason == "stale"
        )
        print(f" obsolete citations detected and removed: {detected}")
        results[name] = arms
        print()

    print(" paired, unverified vs verified (answer still cites at least one gold section)")
    for name in ("dev", "test"):
        before = results[name]["unverified"]["flags"]
        after = results[name]["verified"]["flags"]
        lost = sum(1 for a, b in zip(before, after) if a and not b)
        gained = sum(1 for a, b in zip(before, after) if not a and b)
        print(f"   {name:<5} lost {lost}, gained {gained}, p = {mcnemar_exact_p(gained, lost):.2f}")

    # The four unanswerable questions, before and after verification.
    print()
    print(" unanswerable questions")
    for name, subset in (("dev", dev), ("test", test)):
        for question in subset:
            if question.answerable:
                continue
            execution, reads, report = run(question)
            print(
                f"   {question.id} {name:4} produced {len(execution.answer)} claims,"
                f" kept {len(report.kept)}"
            )
            if args.show_errors:
                for check in report.checks:
                    print(f"        {check.reason:<13} {check.sentence.section:<16} {check.sentence.text[:64]!r}")

    if args.sweep:
        print()
        print(" operating point: threshold against precision and coverage (dev + test, answerable)")
        print(f" {'threshold':>10}{'kept':>7}{'precision':>11}{'gold':>7}{'weak':>7}{'false drop':>12}")
        for threshold in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
            kept = precision = coverage = weak = false_drops = total = 0.0
            for question in dev + test:
                if not question.answerable:
                    continue
                total += 1
                built = plan(question.question, model, index, evidence_budget=20)
                execution = run_budgeted(built, index, model, TOTAL)
                reads = set()
                for finding in execution.findings:
                    reads |= {read.section for read in finding.reads}
                gold = question.gold_sections("current")
                report = check_answer(
                    execution.answer,
                    question=question.question,
                    sections=sections,
                    documents=docs,
                    reads=reads,
                    index=index,
                    min_relevance=threshold,
                )
                row = summarise(report, gold=gold)
                kept += row["kept"]
                precision += row["precision"]
                coverage += row["coverage"]
                weak += report.count("weak")
                false_drops += row["false_drops"]
            print(
                f" {threshold:>10.2f}{kept/total:>7.1f}{precision/total:>10.0%}"
                f"{coverage/total:>7.0%}{weak:>7.0f}{false_drops:>12.0f}"
            )

    if args.show_errors:
        print()
        print(" dropped claims that were in fact gold")
        for name, subset in (("dev", dev), ("test", test)):
            for question in subset:
                if not question.answerable:
                    continue
                execution, reads, report = run(question)
                gold = question.gold_sections("current")
                for check in report.checks:
                    if not check.kept and check.sentence.section in gold:
                        print(
                            f"   {question.id} {name:4} {check.reason:<12}"
                            f" rel={check.relevance:.2f} {check.sentence.section}"
                        )

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
