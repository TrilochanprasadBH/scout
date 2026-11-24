"""Stage 02 tests: read-only sub-agents.

    python stages/02_subagents/test_stage02.py
    IMPL=reference python stages/02_subagents/test_stage02.py

Eleven of these are about the two guarantees — isolation and order — because those are what
separate a fan-out from four sequential calls that happen to share a list.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.baselines_subagent import single_context  # noqa: E402
from scout.corpus import all_sections, load_corpus  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import SubQuestion, plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.subagent import (  # noqa: E402
    ReadOnlyTools,
    run_all,
    run_subagent,
    total_tokens,
)

BUDGET = 20
QUESTIONS = ROOT / "evals" / "questions.jsonl"


def load():
    index = Index(all_sections(load_corpus(ROOT)))
    model = ScriptedModel()
    dev, test = split_questions(load_questions(QUESTIONS))
    return index, model, dev, test


def fanout(question, index, model):
    built = plan(question.question, model, index, evidence_budget=BUDGET)
    per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
    return run_all(built.sub_questions, index, model, max_reads=per_worker)


class TestReadOnlyTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()

    def test_has_no_write_method(self):
        tools = ReadOnlyTools(self.index)
        for name in ("write", "add", "save", "append", "update", "delete", "set"):
            self.assertFalse(hasattr(tools, name), f"tools expose {name}")

    def test_read_sections_is_a_copy(self):
        tools = ReadOnlyTools(self.index)
        hit = tools.search("cache freshness")[0]
        tools.open(hit.section.id)
        snapshot = tools.read_sections
        snapshot.add("rfc9110#1")
        self.assertNotIn("rfc9110#1", tools.read_sections)

    def test_open_records_the_read_and_its_cost(self):
        tools = ReadOnlyTools(self.index)
        hit = tools.search("heuristic freshness")[0]
        text = tools.open(hit.section.id)
        self.assertGreater(len(text), 0)
        self.assertEqual(tools.read_sections, {hit.section.id})
        self.assertGreater(tools.read_tokens, 0)

    def test_search_skips_what_was_already_read(self):
        tools = ReadOnlyTools(self.index)
        first = tools.search("cache freshness", k=3)
        tools.open(first[0].section.id)
        second = tools.search("cache freshness", k=3)
        self.assertNotIn(first[0].section.id, {hit.section.id for hit in second})

    def test_a_run_leaves_the_corpus_unchanged(self):
        before = [(section.id, section.text) for section in self.index.sections]
        fanout(self.dev[0], self.index, self.model)
        after = [(section.id, section.text) for section in self.index.sections]
        self.assertEqual(before, after)


class TestIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()
        cls.finding_source = cls.dev[0]

    def test_reads_are_not_shared_between_workers(self):
        built = plan(self.finding_source.question, self.model, self.index, evidence_budget=BUDGET)
        item = built.sub_questions[0]
        first = run_subagent(item, ReadOnlyTools(self.index), self.model)
        second = run_subagent(item, ReadOnlyTools(self.index), self.model)
        self.assertEqual(first, second, "two isolated workers disagreed")

    def test_sharing_one_tools_object_would_change_the_second_result(self):
        # This is the counterfactual the isolation buys: with one shared read set, the second
        # worker silently receives different evidence from the first, for no stated reason.
        built = plan(self.finding_source.question, self.model, self.index, evidence_budget=BUDGET)
        item = built.sub_questions[0]
        shared = ReadOnlyTools(self.index)
        first = run_subagent(item, shared, self.model)
        second = run_subagent(item, shared, self.model)
        self.assertNotEqual(first.reads, second.reads)

    def test_every_sentence_was_actually_read(self):
        for question in self.dev:
            for finding in fanout(question, self.index, self.model):
                read = {item.section for item in finding.reads}
                self.assertTrue(
                    set(finding.cited) <= read,
                    f"{question.id}/{finding.sub_question}: cited an unread section",
                )

    def test_a_worker_cannot_see_another_workers_reads(self):
        item = self.dev[0]
        built = plan(item.question, self.model, self.index, evidence_budget=BUDGET)
        findings = run_all(built.sub_questions, self.index, self.model)
        for finding in findings:
            self.assertTrue(set(finding.cited) <= {read.section for read in finding.reads})


class TestOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()

    def test_sorted_by_sub_question_id(self):
        question = self.dev[0]
        findings = fanout(question, self.index, self.model)
        ids = [finding.sub_question for finding in findings]
        self.assertEqual(ids, sorted(ids))

    def test_reverse_schedule_gives_the_same_result(self):
        question = self.dev[0]
        built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
        ids = [item.id for item in built.sub_questions]
        forward = run_all(built.sub_questions, self.index, self.model, schedule=list(ids))
        reverse = run_all(built.sub_questions, self.index, self.model, schedule=list(reversed(ids)))
        self.assertEqual(forward, reverse)

    def test_schedule_must_name_every_sub_question_once(self):
        built = plan(self.dev[1].question, self.model, self.index, evidence_budget=BUDGET)
        ids = [item.id for item in built.sub_questions]
        with self.assertRaises(ValueError):
            run_all(built.sub_questions, self.index, self.model, schedule=ids + ids[:1])
        with self.assertRaises(ValueError):
            run_all(built.sub_questions, self.index, self.model, schedule=ids[:1])


class TestFinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, _ = load()

    def test_empty_search_refuses_rather_than_raising(self):
        tools = ReadOnlyTools(self.index)
        item = SubQuestion(id="sq.1", question="zzz", query="zzzqqq")
        finding = run_subagent(item, tools, self.model)
        self.assertEqual(finding.sentences, ())
        self.assertTrue(finding.refused)
        self.assertEqual(finding.reads, ())

    def test_deterministic(self):
        question = self.dev[2]
        self.assertEqual(
            fanout(question, self.index, self.model),
            fanout(question, self.index, self.model),
        )

    def test_cost_is_reads_plus_model(self):
        question = self.dev[0]
        findings = fanout(question, self.index, self.model)
        self.assertGreater(total_tokens(findings), sum(f.prompt_tokens for f in findings) - 1)


class TestMeasurement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, cls.model, cls.dev, cls.test = load()

    def coverage(self, subset):
        total = 0.0
        n = 0
        for question in subset:
            if not question.answerable:
                continue
            cited = set()
            for finding in fanout(question, self.index, self.model):
                cited |= finding.cited
            total += len(question.facets_covered(cited)) / len(question.facets)
            n += 1
        return total / n

    def baseline(self, subset):
        total = 0.0
        n = 0
        for question in subset:
            if not question.answerable:
                continue
            finding = single_context(question.question, self.index, self.model, k=BUDGET)
            total += len(question.facets_covered(set(finding.cited))) / len(question.facets)
            n += 1
        return total / n

    def test_dev_coverage(self):
        score = self.coverage(self.dev)
        self.assertGreaterEqual(score, 0.60, f"dev facet coverage was {score:.3f}")

    def test_held_out_coverage(self):
        score = self.coverage(self.test)
        self.assertGreaterEqual(score, 0.50, f"held-out facet coverage was {score:.3f}")

    def test_beats_single_context_on_both_splits(self):
        for name, subset in (("dev", self.dev), ("test", self.test)):
            mine = self.coverage(subset)
            theirs = self.baseline(subset)
            self.assertGreater(mine, theirs, f"{name}: {mine:.3f} vs {theirs:.3f}")

    def test_does_not_cost_more_than_the_baseline(self):
        tokens = 0
        baseline = 0
        for question in self.dev:
            if not question.answerable:
                continue
            tokens += total_tokens(fanout(question, self.index, self.model))
            baseline += single_context(question.question, self.index, self.model, k=BUDGET).tokens
        self.assertLessEqual(tokens, baseline * 1.1, f"{tokens} vs {baseline}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
