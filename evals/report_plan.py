#!/usr/bin/env python3
"""Planning report: what does decomposition buy, and what does it cost.

    python evals/report_plan.py
    IMPL=reference python evals/report_plan.py --show-errors 3
    IMPL=reference python evals/report_plan.py --anchor

Three configurations, one evidence budget:

  one query, k=20        the baseline a careful person would write first
  plan, equal passages   the plan's searches share the same 20 passages
  plan, full depth       each sub-question gets k=20, so the plan costs more

`equal passages` is the honest comparison, because it holds the thing being spent constant.
`full depth` is what a real system does, and the searches column is why stage 03 exists.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import Question, load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import budget_share, plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.stats import mcnemar_exact_p, wilson_interval  # noqa: E402

BUDGET = 20


def one_query(question: Question, index: Index, k: int = BUDGET) -> tuple[set[str], int]:
    return {hit.section.id for hit in index.search(question.question, k=k)}, 1


def planned(
    question: Question, index: Index, model: ScriptedModel, *, full_depth: bool, anchor: bool
) -> tuple[set[str], int]:
    built = plan(
        question.question, model, index, evidence_budget=BUDGET, anchor=anchor
    )
    share = budget_share(built)
    found: set[str] = set()
    for item in built.sub_questions:
        k = BUDGET if full_depth else max(1, share[item.id])
        found |= {hit.section.id for hit in index.search(item.query, k=k)}
    return found, built.searches()


def score(subset: list[Question], runner) -> dict:
    rows = []
    searches = 0
    for question in subset:
        if not question.answerable:
            continue
        found, cost = runner(question)
        covered = question.facets_covered(found)
        rows.append(
            {
                "id": question.id,
                "ratio": len(covered) / len(question.facets),
                "full": len(covered) == len(question.facets),
            }
        )
        searches += cost
    n = len(rows) or 1
    return {
        "mean": sum(row["ratio"] for row in rows) / n,
        "full": sum(row["full"] for row in rows),
        "n": len(rows),
        "searches": searches / n,
        "rows": rows,
    }


def line(label: str, result: dict) -> str:
    low, high = wilson_interval(result["full"], result["n"])
    return (
        f" {label:<26}{result['mean']:>7.3f}"
        f"{result['full']:>7}/{result['n']:<4}"
        f"{low:>7.0%}-{high:<6.0%}"
        f"{result['searches']:>9.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-errors", type=int, default=0)
    parser.add_argument("--anchor", action="store_true", help="include the rare-term anchor")
    args = parser.parse_args()

    documents = load_corpus(ROOT)
    index = Index(all_sections(documents))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(ROOT / "evals" / "questions.jsonl"))

    print()
    print(f" implementation {IMPL}")
    print(f" evidence budget {BUDGET} passages")
    print(f" anchor          {'on' if args.anchor else 'off'}")
    print()
    print(f" {'configuration':<26}{'facet':>7}{'full':>8}  {'95% CI':<14}{'searches/q':>10}")

    results: dict[str, dict[str, dict]] = {}
    for name, subset in (("dev", dev), ("test", test)):
        results[name] = {
            "one query": score(subset, lambda q: one_query(q, index)),
            "plan, equal passages": score(
                subset,
                lambda q: planned(q, index, model, full_depth=False, anchor=args.anchor),
            ),
            "plan, full depth": score(
                subset,
                lambda q: planned(q, index, model, full_depth=True, anchor=args.anchor),
            ),
        }
        for label, result in results[name].items():
            print(f" {name:<5}" + line(label, result))
        print()

    # Paired comparison: did the plan cover a question the baseline missed, or the reverse?
    print(" paired, baseline vs plan at equal passages")
    for name in ("dev", "test"):
        base = results[name]["one query"]["rows"]
        variant = results[name]["plan, equal passages"]["rows"]
        n01 = sum(1 for a, b in zip(base, variant) if not a["full"] and b["full"])
        n10 = sum(1 for a, b in zip(base, variant) if a["full"] and not b["full"])
        p_value = mcnemar_exact_p(n01, n10)
        print(f"   {name:<5} baseline only {n10}, plan only {n01}, both {sum(1 for a, b in zip(base, variant) if a['full'] and b['full'])}, p = {p_value:.2f}")

    if args.show_errors:
        print()
        print(" questions the plan did not fully cover (equal passages)")
        for question in dev + test:
            if not question.answerable:
                continue
            found, _ = planned(question, index, model, full_depth=False, anchor=args.anchor)
            missing = sorted(set(range(len(question.facets))) - question.facets_covered(found))
            if missing:
                names = [question.facets[index] for index in missing]
                print(f"   {question.id} {question.split:4} missing: {'; '.join(names)}")
                if args.show_errors > 1:
                    for item in question.current:
                        if item.facet in missing:
                            print(f"        wanted {item.section}: {item.phrase[:70]!r}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
