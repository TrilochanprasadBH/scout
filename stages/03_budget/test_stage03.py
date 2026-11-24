"""Stage 03 tests: budget control.

    python stages/03_budget/test_stage03.py
    IMPL=reference python stages/03_budget/test_stage03.py

The invariant tests matter more than the coverage thresholds. A budget bug shows up as a
negative ledger or an overrun, and both are cheap to check on every run.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.baselines_budget import no_budget  # noqa: E402
from scout.budget import (  # noqa: E402
    Budget,
    BudgetedTools,
    BudgetExhausted,
    plan_budget,
    run_budgeted,
)
from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402

TOTALS = (3000, 6000, 12000, 24000)
QUESTIONS = ROOT / "evals" / "questions.jsonl"


def load():
    index = Index(all_sections(load_corpus(ROOT)))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(QUESTIONS))
    return index, model, dev, test


class TestBudgetLedger(unittest.TestCase):
    def test_available_never_goes_negative(self):
        budget = Budget(total=100)
        self.assertFalse(budget.spend(101))
        self.assertEqual(budget.spent, 0)
        self.assertEqual(budget.available, 100)

    def test_spend_within_available(self):
        budget = Budget(total=100)
        self.assertTrue(budget.spend(40))
        self.assertTrue(budget.spend(60))
        self.assertEqual(budget.available, 0)
        self.assertFalse(budget.spend(1))

    def test_reservation_cannot_be_spent(self):
        budget = Budget(total=100)
        budget.reserve(30)
        self.assertEqual(budget.available, 70)
        self.assertFalse(budget.spend(71))
        self.assertTrue(budget.spend(70))
        self.assertEqual(budget.reserved, 30)

    def test_reserve_above_available_raises(self):
        budget = Budget(total=100)
        with self.assertRaises(ValueError):
            budget.reserve(101)

    def test_writer_allowance_includes_the_reservation(self):
        budget = Budget(total=100)
        budget.reserve(30)
        budget.spend(20)
        self.assertEqual(budget.available, 50)
        self.assertEqual(budget.writer_allowance, 80)

    def test_overrun_reports_zero_for_a_well_behaved_ledger(self):
        budget = Budget(total=100)
        budget.spend(100)
        self.assertEqual(budget.overrun, 0)


class TestBudgetedTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()

    def test_charges_and_returns_text(self):
        budget = Budget(total=10000)
        tools = BudgetedTools(self.index, budget)
        hit = tools.search("heuristic freshness")[0]
        text = tools.open(hit.section.id)
        self.assertGreater(len(text), 0)
        self.assertGreater(budget.spent, 0)

    def test_raises_when_the_charge_does_not_fit(self):
        budget = Budget(total=1)
        tools = BudgetedTools(self.index, budget)
        hit = tools.search("heuristic freshness")[0]
        with self.assertRaises(BudgetExhausted):
            tools.open(hit.section.id)
        self.assertEqual(budget.spent, 0)


class TestAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()
        cls.plan = plan(cls.dev[0].question, cls.model, cls.index, evidence_budget=20)

    def test_accepted_and_dropped_partition_the_plan(self):
        budget = Budget(total=6000)
        budget.reserve(int(6000 * 0.35))
        admission = plan_budget(self.plan, budget, self.index)
        self.assertEqual(
            len(admission.accepted) + len(admission.dropped), len(self.plan.sub_questions)
        )

    def test_accepted_is_a_prefix_in_plan_order(self):
        budget = Budget(total=6000)
        budget.reserve(int(6000 * 0.35))
        admission = plan_budget(self.plan, budget, self.index)
        self.assertEqual(
            list(admission.accepted), list(self.plan.sub_questions[: len(admission.accepted)])
        )

    def test_tiny_budget_admits_nothing_and_says_why(self):
        budget = Budget(total=50)
        budget.reserve(10)
        admission = plan_budget(self.plan, budget, self.index)
        self.assertEqual(admission.accepted, ())
        self.assertTrue(admission.reason)

    def test_deterministic(self):
        budget = Budget(total=6000)
        budget.reserve(2000)
        self.assertEqual(
            plan_budget(self.plan, budget, self.index),
            plan_budget(self.plan, budget, self.index),
        )


class TestExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, cls.test = load()

    def test_never_overruns_at_any_budget(self):
        for total in TOTALS:
            for question in self.dev:
                built = plan(question.question, self.model, self.index, evidence_budget=20)
                run = run_budgeted(built, self.index, self.model, total)
                self.assertEqual(run.budget.overrun, 0, f"{question.id} at {total}")
                self.assertLessEqual(run.budget.spent, total)

    def test_spend_is_monotone_in_the_budget(self):
        question = self.dev[0]
        built = plan(question.question, self.model, self.index, evidence_budget=20)
        spends = [run_budgeted(built, self.index, self.model, t).budget.spent for t in TOTALS]
        self.assertEqual(spends, sorted(spends))

    def test_an_impossible_budget_refuses_rather_than_raising(self):
        built = plan(self.dev[0].question, self.model, self.index, evidence_budget=20)
        run = run_budgeted(built, self.index, self.model, 200)
        self.assertEqual(run.findings, ())
        self.assertEqual(run.answer, ())
        self.assertTrue(run.admission.reason)

    def test_a_comfortable_budget_does_not_lose_coverage(self):
        for name, subset in (("dev", self.dev), ("test", self.test)):
            mine = theirs = n = 0
            for question in subset:
                if not question.answerable:
                    continue
                n += 1
                built = plan(question.question, self.model, self.index, evidence_budget=20)
                gold = question.gold_sections("current")
                run = run_budgeted(built, self.index, self.model, 24000)
                mine += len({s.section for s in run.answer} & gold) / len(gold)
                _, answer, _ = no_budget(built, self.index, self.model, 24000)
                theirs += len({s.section for s in answer} & gold) / len(gold)
            self.assertGreaterEqual(mine / n, 0.9 * theirs / n, name)


class TestEfficiency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()

    def test_same_answers_for_half_the_tokens(self):
        budgeted = uncontrolled = 0
        for question in self.dev:
            if not question.answerable:
                continue
            built = plan(question.question, self.model, self.index, evidence_budget=20)
            budgeted += run_budgeted(built, self.index, self.model, 12000).budget.spent
            _, _, spent = no_budget(built, self.index, self.model, 12000)
            uncontrolled += spent
        self.assertLess(budgeted, uncontrolled * 0.75, f"{budgeted} vs {uncontrolled}")

    def test_an_uncontrolled_run_overspends_a_small_budget(self):
        overspent = 0
        for question in self.dev:
            if not question.answerable:
                continue
            built = plan(question.question, self.model, self.index, evidence_budget=20)
            _, _, spent = no_budget(built, self.index, self.model, 3000)
            overspent += max(0, spent - 3000)
        self.assertGreater(overspent, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
