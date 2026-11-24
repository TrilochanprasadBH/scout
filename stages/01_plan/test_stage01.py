"""Stage 01 tests: planning and decomposition.

    python stages/01_plan/test_stage01.py
    IMPL=reference python stages/01_plan/test_stage01.py

The thresholds are set just below what the reference measures, so a regression fails and a
different-but-good implementation still passes. The exact numbers are in the lesson and in
`evals/report_plan.py`.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import MAX_PARTS, budget_share, plan, validate  # noqa: E402
from scout.search import Index  # noqa: E402

BUDGET = 20
QUESTIONS = ROOT / "evals" / "questions.jsonl"


def load():
    documents = load_corpus(ROOT)
    index = Index(all_sections(documents))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(QUESTIONS))
    return index, model, dev, test


def execute(question, index, model, *, full_depth=False, anchor=False):
    """Run a plan and return the sections it retrieved, plus how many searches it cost."""
    built = plan(question.question, model, index, evidence_budget=BUDGET, anchor=anchor)
    share = budget_share(built)
    found = set()
    for item in built.sub_questions:
        k = BUDGET if full_depth else max(1, share[item.id])
        found |= {hit.section.id for hit in index.search(item.query, k=k)}
    return found, built


def facet_coverage(questions, index, model, **kwargs):
    total = 0.0
    n = 0
    for question in questions:
        if not question.answerable:
            continue
        found, _ = execute(question, index, model, **kwargs)
        total += len(question.facets_covered(found)) / len(question.facets)
        n += 1
    return total / n


def one_query_coverage(questions, index):
    total = 0.0
    n = 0
    for question in questions:
        if not question.answerable:
            continue
        found = {hit.section.id for hit in index.search(question.question, k=BUDGET)}
        total += len(question.facets_covered(found)) / len(question.facets)
        n += 1
    return total / n


class TestGoldenSet(unittest.TestCase):
    def test_both_splits_present(self):
        _, _, dev, test = load()
        self.assertGreaterEqual(len(dev), 10)
        self.assertGreaterEqual(len(test), 5)

    def test_some_questions_are_unanswerable(self):
        _, _, dev, test = load()
        self.assertTrue(any(not q.answerable for q in dev + test))

    def test_multi_facet_questions_exist(self):
        _, _, dev, test = load()
        self.assertGreaterEqual(sum(1 for q in dev + test if len(q.facets) > 1), 10)


class TestBaseline(unittest.TestCase):
    """The starting point must be weak, or the stage teaches nothing."""

    def test_one_query_is_not_already_good(self):
        index, _, dev, _ = load()
        score = one_query_coverage(dev, index)
        self.assertLess(score, 0.85, f"baseline already covers {score:.3f} of facets")


class TestPlanContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, cls.test = load()

    def test_every_plan_is_valid(self):
        for question in self.dev + self.test:
            built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
            self.assertEqual(validate(built), [], question.id)

    def test_question_with_two_clauses_gets_two_sub_questions(self):
        question = "What is the difference between a safe method and an idempotent method?"
        built = plan(question, self.model, self.index, evidence_budget=BUDGET)
        self.assertGreaterEqual(len(built.sub_questions), 2)

    def test_plan_is_capped(self):
        built = plan(" ".join(["cache freshness invalidation validation"] * 6), self.model, self.index)
        self.assertLessEqual(len(built.sub_questions), MAX_PARTS)

    def test_queries_are_distinct(self):
        for question in self.dev:
            built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
            queries = [item.query.lower() for item in built.sub_questions]
            self.assertEqual(len(queries), len(set(queries)), question.id)

    def test_no_sub_question_is_pure_scaffolding(self):
        for question in self.dev:
            built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
            for item in built.sub_questions:
                self.assertGreaterEqual(len(item.query.split()), 1, item.query)

    def test_deterministic(self):
        question = self.dev[0]
        first = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
        second = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
        self.assertEqual(first, second)


class TestBudgetShare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()

    def test_share_never_exceeds_the_budget(self):
        for question in self.dev:
            built = plan(question.question, self.model, self.index, evidence_budget=7)
            share = budget_share(built)
            self.assertLessEqual(sum(share.values()), 7, question.id)

    def test_every_sub_question_gets_a_passage(self):
        for question in self.dev:
            built = plan(question.question, self.model, self.index, evidence_budget=7)
            share = budget_share(built)
            self.assertTrue(all(value >= 1 for value in share.values()), question.id)

    def test_share_covers_every_sub_question(self):
        built = plan(self.dev[0].question, self.model, self.index, evidence_budget=BUDGET)
        self.assertEqual(set(budget_share(built)), {item.id for item in built.sub_questions})


class TestMeasurement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, cls.test = load()

    def test_dev_facet_coverage(self):
        score = facet_coverage(self.dev, self.index, self.model)
        self.assertGreaterEqual(score, 0.85, f"dev facet coverage was {score:.3f}")

    def test_held_out_facet_coverage(self):
        score = facet_coverage(self.test, self.index, self.model)
        self.assertGreaterEqual(score, 0.90, f"held-out facet coverage was {score:.3f}")

    def test_plan_does_not_lose_ground_at_equal_cost(self):
        for name, subset in (("dev", self.dev), ("test", self.test)):
            baseline = one_query_coverage(subset, self.index)
            planned = facet_coverage(subset, self.index, self.model)
            self.assertGreaterEqual(planned, baseline, f"{name}: {planned:.3f} < {baseline:.3f}")

    def test_four_searches_are_enough(self):
        for question in self.dev:
            _, built = execute(question, self.index, self.model)
            self.assertLessEqual(built.searches(), MAX_PARTS, question.id)


class TestNegativeResult(unittest.TestCase):
    """The rare-term anchor measured worse. This test is why it stays off.

    It is a guard against an obvious idea being switched back on from memory. If someone
    improves the anchor so that it wins, this test fails and says to re-measure and update
    the lesson, which is the correct workflow.
    """

    def test_anchor_does_not_improve_coverage(self):
        index, model, dev, _ = load()
        without = facet_coverage(dev, index, model, anchor=False)
        with_anchor = facet_coverage(dev, index, model, anchor=True)
        self.assertLess(
            with_anchor,
            without,
            f"the anchor now measures {with_anchor:.3f} against {without:.3f}; "
            "re-measure, then update the lesson and this test",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
