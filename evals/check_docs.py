#!/usr/bin/env python3
"""Fail if a documented number no longer matches the code.

    python evals/check_docs.py

This file exists from stage 01 on purpose. `triage` added its version after the fact, and the
audit that followed found six numbers that had drifted plus a method that could no longer
reproduce its own table. Building the check first is cheaper than the correction pass.

The check recomputes each headline number from the reference implementation and asserts that
the formatted string appears in every document that quotes it. It does not parse prose. That
is crude, sufficient, and the reason a number can never be edited in one place and left in
another.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
README_DOC = "README.md"
GUIDE_DOC = "GUIDE.md"
sys.path.insert(0, str(ROOT / "reference"))

from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import budget_share, plan  # noqa: E402
from scout.search import Index  # noqa: E402

BUDGET = 20


def main() -> int:
    documents = load_corpus(ROOT)
    index = Index(all_sections(documents))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(ROOT / "evals" / "questions.jsonl"))

    def baseline(question):
        return {hit.section.id for hit in index.search(question.question, k=BUDGET)}

    def planned(question, *, full_depth=False, anchor=False):
        built = plan(question.question, model, index, evidence_budget=BUDGET, anchor=anchor)
        share = budget_share(built)
        found = set()
        for item in built.sub_questions:
            k = BUDGET if full_depth else max(1, share[item.id])
            found |= {hit.section.id for hit in index.search(item.query, k=k)}
        return found, built.searches()

    def coverage(subset, runner):
        ratios, full, searches, n = 0.0, 0, 0, 0
        for question in subset:
            if not question.answerable:
                continue
            found, cost = runner(question)
            covered = question.facets_covered(found)
            ratios += len(covered) / len(question.facets)
            full += len(covered) == len(question.facets)
            searches += cost
            n += 1
        return ratios / n, full, n, searches / n

    dev_base = coverage(dev, lambda q: (baseline(q), 1))
    dev_plan = coverage(dev, lambda q: planned(q))
    dev_full = coverage(dev, lambda q: planned(q, full_depth=True))
    dev_anchor = coverage(dev, lambda q: planned(q, anchor=True))
    test_base = coverage(test, lambda q: (baseline(q), 1))
    test_plan = coverage(test, lambda q: planned(q))

    # ---------------------------------------------------------------- stage 02: sub-agents
    from scout.baselines_subagent import single_context  # noqa: E402
    from scout.subagent import run_all, total_tokens  # noqa: E402

    def fanout(question):
        built = plan(question.question, model, index, evidence_budget=BUDGET)
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        return run_all(built.sub_questions, index, model, max_reads=per_worker)

    def subagents(subset):
        single_cov = fan_cov = 0.0
        single_full = fan_full = 0
        single_tokens = fan_tokens = 0
        single_prompt = fan_prompt = 0
        n = rows = 0
        for question in subset:
            rows += 1
            one = single_context(question.question, index, model, k=BUDGET)
            many = fanout(question)
            single_tokens += one.tokens
            fan_tokens += total_tokens(many)
            single_prompt = max(single_prompt, one.prompt_tokens)
            fan_prompt = max(fan_prompt, max((f.prompt_tokens for f in many), default=0))
            if not question.answerable:
                continue
            n += 1
            single_cov += len(question.facets_covered(set(one.cited))) / len(question.facets)
            single_full += len(question.facets_covered(set(one.cited))) == len(question.facets)
            cited = set()
            for finding in many:
                cited |= finding.cited
            fan_cov += len(question.facets_covered(cited)) / len(question.facets)
            fan_full += len(question.facets_covered(cited)) == len(question.facets)
        return {
            "single_cov": single_cov / n,
            "single_full": single_full,
            "fan_cov": fan_cov / n,
            "fan_full": fan_full,
            "n": n,
            "single_tokens": single_tokens / rows,
            "fan_tokens": fan_tokens / rows,
            "single_prompt": single_prompt,
            "fan_prompt": fan_prompt,
        }

    dev_sub = subagents(dev)
    test_sub = subagents(test)

    # ------------------------------------------------------------------- stage 03: budget
    from scout.baselines_budget import no_budget  # noqa: E402
    from scout.budget import run_budgeted  # noqa: E402

    def budget_arm(subset, total, *, budgeted):
        cited = spend = over = 0.0
        dropped = trimmed = n = 0
        for question in subset:
            if not question.answerable:
                continue
            n += 1
            built = plan(question.question, model, index, evidence_budget=BUDGET)
            gold = question.gold_sections("current")
            if budgeted:
                run = run_budgeted(built, index, model, total)
                found = {sentence.section for sentence in run.answer} & gold
                spend += run.budget.spent
                over += run.budget.overrun
                dropped += len(run.admission.dropped)
                trimmed += len(run.trimmed)
            else:
                _, answer, spent = no_budget(built, index, model, total)
                found = {sentence.section for sentence in answer} & gold
                spend += spent
                over += max(0, spent - total)
            cited += len(found) / len(gold)
        return {
            "cited": cited / n,
            "spend": spend / n,
            "over": over / n,
            "dropped": dropped,
            "trimmed": trimmed,
        }

    dev_small = budget_arm(dev, 3000, budgeted=True)
    dev_roomy = budget_arm(dev, 12000, budgeted=True)
    dev_free = budget_arm(dev, 12000, budgeted=False)
    test_small = budget_arm(test, 3000, budgeted=True)
    test_roomy = budget_arm(test, 12000, budgeted=True)
    test_free = budget_arm(test, 12000, budgeted=False)

    # ---------------------------------------------------------------- stage 04: citations
    from scout.cite import check_answer, summarise  # noqa: E402
    from scout.corpus import document_map, section_map  # noqa: E402

    documents_by_id = document_map(documents)
    sections_by_id = section_map(documents)

    def citation_arm(subset, threshold=0.20):
        rows = []
        for question in subset:
            if not question.answerable:
                continue
            built = plan(question.question, model, index, evidence_budget=BUDGET)
            execution = run_budgeted(built, index, model, 12000)
            reads = set()
            for finding in execution.findings:
                reads |= {read.section for read in finding.reads}
            gold = question.gold_sections("current")
            report = check_answer(
                execution.answer,
                question=question.question,
                sections=sections_by_id,
                documents=documents_by_id,
                reads=reads,
                index=index,
                min_relevance=threshold,
            )
            raw_precision = (
                len({s.section for s in execution.answer} & gold) / len(execution.answer)
                if execution.answer
                else 0.0
            )
            raw_stale = sum(
                1
                for sentence in execution.answer
                if sentence.section in sections_by_id
                and not documents_by_id[sections_by_id[sentence.section].document].current
            )
            rows.append(
                {
                    "claims": len(execution.answer),
                    "kept": len(report.kept),
                    "precision": summarise(report, gold=gold)["precision"],
                    "coverage": summarise(report, gold=gold)["coverage"],
                    "stale": summarise(report, gold=gold)["stale"],
                    "raw_precision": raw_precision,
                    "raw_stale": raw_stale,
                    "detected": report.count("stale"),
                    "gold_dropped": summarise(report, gold=gold)["false_drops"],
                }
            )
        n = len(rows)
        summed = ("claims", "kept", "raw_stale", "detected", "gold_dropped")
        return {
            key: (sum(row[key] for row in rows) if key in summed else sum(row[key] for row in rows) / n)
            for key in rows[0]
        }

    def citation_summary(subset, threshold=0.20):
        rows = []
        for question in subset:
            if not question.answerable:
                continue
            built = plan(question.question, model, index, evidence_budget=BUDGET)
            execution = run_budgeted(built, index, model, 12000)
            reads = set()
            for finding in execution.findings:
                reads |= {read.section for read in finding.reads}
            gold = question.gold_sections("current")
            report = check_answer(
                execution.answer,
                question=question.question,
                sections=sections_by_id,
                documents=documents_by_id,
                reads=reads,
                index=index,
                min_relevance=threshold,
            )
            summary = summarise(report, gold=gold)
            rows.append(
                {
                    "kept": summary["kept"],
                    "coverage": summary["coverage"],
                    "precision": summary["precision"],
                }
            )
        n = len(rows)
        return {
            "kept": sum(row["kept"] for row in rows),
            "coverage": sum(row["coverage"] for row in rows) / n,
            "precision": sum(row["precision"] for row in rows) / n,
        }

    dev_cite = citation_arm(dev)
    test_cite = citation_arm(test)
    both_wide = citation_summary(dev + test, threshold=0.30)
    both_default = citation_summary(dev + test)

    # ---------------------------------------------------------------- stage 06: assembled
    from scout.synth import synthesise  # noqa: E402
    from scout.trace import attribute, completeness, locate, record  # noqa: E402

    def assembled(subset):
        full = answers = 0
        gold = precision = 0.0
        stale = tokens = 0
        localised = dropped = 0
        n = 0
        for question in subset:
            if not question.answerable:
                continue
            n += 1
            built = plan(question.question, model, index, evidence_budget=BUDGET)
            per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
            findings = run_all(built.sub_questions, index, model, max_reads=per_worker)
            answer = synthesise(
                question.question, findings, model,
                documents=documents_by_id, sections=sections_by_id,
            )
            reads = set()
            for finding in findings:
                reads |= {read.section for read in finding.reads}
            report = check_answer(
                answer.sentences,
                question=question.question,
                sections=sections_by_id,
                documents=documents_by_id,
                reads=reads,
                index=index,
            )
            trace = record(question.question, built, findings, answer, report)
            gold_sections = question.gold_sections("current")
            cited = {sentence.section for sentence in report.kept}
            covered = question.facets_covered(cited)
            answers += 1 if cited & gold_sections else 0
            gold += len(cited & gold_sections) / len(gold_sections)
            full += bool(question.facets) and len(covered) == len(question.facets)
            precision += len(cited & gold_sections) / len(cited) if cited else 0.0
            stale += sum(
                1
                for sentence in report.kept
                if not documents_by_id[sections_by_id[sentence.section].document].current
            )
            tokens += trace.total_tokens
            for check in report.checks:
                if check.kept:
                    continue
                span = locate(trace, check.sentence.text)
                dropped += 1
                localised += bool(
                    span and span.attributes.get("sub_question") not in (None, "unknown")
                )
        return {
            "answers": answers,
            "n": n,
            "gold": gold / n,
            "full": full,
            "precision": precision / n,
            "stale": stale,
            "tokens": tokens / n,
            "localised": localised / dropped if dropped else 1.0,
        }

    dev_all = assembled(dev)
    test_all = assembled(test)

    plan_lesson = "stages/01_plan/README.md"
    sub_lesson = "stages/02_subagents/README.md"
    budget_lesson = "stages/03_budget/README.md"
    cite_lesson = "stages/04_citations/README.md"
    synth_lesson = "stages/05_synthesis/README.md"
    trace_lesson = "stages/06_tracing/README.md"
    expectations = [
        (f"{dev_base[0]:.3f}", ["README.md", plan_lesson]),
        (f"{dev_plan[0]:.3f}", ["README.md", GUIDE_DOC, plan_lesson]),
        (f"{dev_base[1]}/{dev_base[2]}", [plan_lesson]),
        (f"{dev_plan[1]}/{dev_plan[2]}", [plan_lesson]),
        (f"{test_base[0]:.3f}", ["README.md", plan_lesson]),
        (f"{test_plan[0]:.3f}", ["README.md", plan_lesson]),
        (f"{dev_anchor[0]:.3f}", [plan_lesson]),
        (f"{dev_plan[3]:.1f}", [GUIDE_DOC, plan_lesson]),
        # stage 02
        (f"{dev_sub['single_cov']:.3f}", ["README.md", sub_lesson]),
        (f"{dev_sub['fan_cov']:.3f}", ["README.md", GUIDE_DOC, sub_lesson]),
        (f"{test_sub['single_cov']:.3f}", ["README.md", sub_lesson]),
        (f"{test_sub['fan_cov']:.3f}", ["README.md", GUIDE_DOC, sub_lesson]),
        (f"{dev_sub['fan_full']}/{dev_sub['n']}", [sub_lesson]),
        (f"{dev_sub['single_tokens']:.0f}", [sub_lesson]),
        (f"{dev_sub['fan_tokens']:.0f}", [sub_lesson]),
        (f"{dev_sub['single_prompt']:.0f}", [sub_lesson]),
        (f"{dev_sub['fan_prompt']:.0f}", [sub_lesson]),
        # stage 03
        (f"{dev_roomy['spend']:.0f}", [README_DOC, budget_lesson]),
        (f"{dev_free['spend']:.0f}", [budget_lesson]),
        (f"{dev_roomy['cited']:.0%}", [README_DOC, budget_lesson]),
        (f"{dev_roomy['spend'] / dev_free['spend']:.0%}", [GUIDE_DOC]),
        (f"{test_roomy['spend'] / test_free['spend']:.0%}", [GUIDE_DOC]),
        (f"{dev_free['cited']:.0%}", [README_DOC, budget_lesson]),
        (f"{dev_small['cited']:.0%}", [budget_lesson]),
        (f"{dev_small['over']:.0f}", [budget_lesson]),
        (f"{test_roomy['cited']:.0%}", [budget_lesson]),
        (f"{test_free['spend']:.0f}", [budget_lesson]),
        (f"{test_small['over']:.0f}", [budget_lesson]),
        # stage 04
        (f"{dev_cite['raw_precision']:.0%}", [README_DOC, cite_lesson]),
        (f"{dev_cite['precision']:.0%}", [README_DOC, GUIDE_DOC, cite_lesson]),
        (f"{test_cite['raw_precision']:.0%}", [cite_lesson]),
        (f"{test_cite['precision']:.0%}", [cite_lesson]),
        (f"{dev_cite['kept']:.0f}", [cite_lesson]),
        (f"{test_cite['kept']:.0f}", [cite_lesson]),
        (f"{dev_cite['detected']:.0f}", [cite_lesson]),
        (f"{test_cite['detected']:.0f}", [cite_lesson]),
        (f"{dev_cite['coverage']:.0%}", [cite_lesson]),
        (f"{both_wide['coverage']:.0%}", [cite_lesson]),
        (f"{dev_cite['gold_dropped']:.0f}", [cite_lesson]),
        # stage 06
        (f"{dev_all['full']}/{dev_all['n']}", [README_DOC, trace_lesson]),
        (f"{test_all['full']}/{test_all['n']}", [README_DOC, trace_lesson]),
        (f"{dev_all['gold']:.2f}", [trace_lesson]),
        (f"{test_all['gold']:.2f}", [trace_lesson]),
        (f"{dev_all['precision']:.0%}", [README_DOC, GUIDE_DOC, trace_lesson]),
        (f"{test_all['precision']:.0%}", [README_DOC, trace_lesson]),
        (f"{dev_all['tokens']:.0f}", [trace_lesson]),
        (f"{test_all['tokens']:.0f}", [trace_lesson]),
        (f"{dev_all['localised']:.0%}", [trace_lesson]),
    ]

    problems: list[str] = []
    for value, files in expectations:
        for relative in files:
            if value not in (ROOT / relative).read_text(encoding="utf-8"):
                problems.append(f"{relative} does not contain {value}")

    print()
    print(f" architecture     scripted model over {len(documents)} documents, {len(index.sections)} sections")
    print(f" planning dev     baseline {dev_base[0]:.3f} ({dev_base[1]}/{dev_base[2]})"
          f"   plan {dev_plan[0]:.3f} ({dev_plan[1]}/{dev_plan[2]})"
          f"   full depth {dev_full[0]:.3f}")
    print(f" planning test    baseline {test_base[0]:.3f} ({test_base[1]}/{test_base[2]})"
          f"   plan {test_plan[0]:.3f} ({test_plan[1]}/{test_plan[2]})")
    print(f" planning cost    {dev_plan[3]:.1f} searches per question")
    print(f" anchor ablation  {dev_anchor[0]:.3f} ({dev_anchor[1]}/{dev_anchor[2]}),"
          f" {dev_anchor[3]:.1f} searches")
    print(f" subagents dev    single {dev_sub['single_cov']:.3f} ({dev_sub['single_full']}/{dev_sub['n']})"
          f"   fan-out {dev_sub['fan_cov']:.3f} ({dev_sub['fan_full']}/{dev_sub['n']})")
    print(f" subagents test   single {test_sub['single_cov']:.3f} ({test_sub['single_full']}/{test_sub['n']})"
          f"   fan-out {test_sub['fan_cov']:.3f} ({test_sub['fan_full']}/{test_sub['n']})")
    print(f" subagent cost    {dev_sub['single_tokens']:.0f} -> {dev_sub['fan_tokens']:.0f} tokens per question,"
          f" max prompt {dev_sub['single_prompt']:.0f} -> {dev_sub['fan_prompt']:.0f}")
    print(f" budget 12000     dev {dev_roomy['spend']:.0f} vs {dev_free['spend']:.0f} tokens,"
          f" cited {dev_roomy['cited']:.0%} vs {dev_free['cited']:.0%}")
    print(f" budget 3000      dev cited {dev_small['cited']:.0%},"
          f" dropped {dev_small['dropped']}, overrun {dev_small['over']:.0f}")
    print(f" citations dev    {dev_cite['claims']:.0f} claims -> {dev_cite['kept']:.0f} kept,"
          f" precision {dev_cite['raw_precision']:.0%} -> {dev_cite['precision']:.0%},"
          f" stale {dev_cite['detected']:.0f} removed")
    print(f" citations test   {test_cite['claims']:.0f} claims -> {test_cite['kept']:.0f} kept,"
          f" precision {test_cite['raw_precision']:.0%} -> {test_cite['precision']:.0%},"
          f" stale {test_cite['detected']:.0f} removed")
    print(f" assembled dev    {dev_all['full']}/{dev_all['n']} full, gold {dev_all['gold']:.2f},"
          f" precision {dev_all['precision']:.0%}, stale {dev_all['stale']:.0f},"
          f" {dev_all['tokens']:.0f} tokens")
    print(f" assembled test   {test_all['full']}/{test_all['n']} full, gold {test_all['gold']:.2f},"
          f" precision {test_all['precision']:.0%}, stale {test_all['stale']:.0f},"
          f" {test_all['tokens']:.0f} tokens")
    print(f" problems         {len(problems)}")
    for problem in problems:
        print(f"   {problem}")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
