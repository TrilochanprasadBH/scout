"""Stage 06 tests: tracing.

    python stages/06_tracing/test_stage06.py
    IMPL=reference python stages/06_tracing/test_stage06.py

The tests that matter are the four invariants: the tokens add up, every sentence has provenance,
every kept citation has a read behind it, and the same run produces the same trace.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.baselines_trace import flat_log, flat_metrics  # noqa: E402
from scout.cite import check_answer  # noqa: E402
from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
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
QUESTIONS = ROOT / "evals" / "questions.jsonl"


class Pipeline:
    @classmethod
    def setUpClass(cls):
        documents = load_corpus(ROOT)
        cls.sections = section_map(documents)
        cls.docs = document_map(documents)
        cls.index = Index(list(cls.sections.values()))
        cls.model = ScriptedModel()
        cls.dev, cls.test = split_questions(load_questions(QUESTIONS))

    def execute(self, question):
        built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        findings = run_all(built.sub_questions, self.index, self.model, max_reads=per_worker)
        answer = synthesise(
            question.question, findings, self.model, documents=self.docs, sections=self.sections
        )
        reads = set()
        for finding in findings:
            reads |= {read.section for read in finding.reads}
        report = check_answer(
            answer.sentences,
            question=question.question,
            sections=self.sections,
            documents=self.docs,
            reads=reads,
            index=self.index,
        )
        trace = record(question.question, built, findings, answer, report)
        return built, findings, answer, report, trace


class TestShape(Pipeline, unittest.TestCase):
    def test_root_is_the_question(self):
        _, _, _, _, trace = self.execute(self.dev[0])
        self.assertEqual(trace.root.name, "research")
        self.assertIsNone(trace.root.parent)
        self.assertEqual(trace.root.attributes["question"], self.dev[0].question)

    def test_one_plan_span(self):
        _, _, _, _, trace = self.execute(self.dev[0])
        self.assertEqual(len(trace.by_name("plan")), 1)

    def test_one_worker_per_finding_and_one_read_per_read(self):
        _, findings, _, _, trace = self.execute(self.dev[0])
        self.assertEqual(len(trace.by_name("worker")), len(findings))
        self.assertEqual(
            len(trace.by_name("read")), sum(len(finding.reads) for finding in findings)
        )

    def test_one_write_and_one_span_per_sentence(self):
        _, _, answer, _, trace = self.execute(self.dev[0])
        self.assertEqual(len(trace.by_name("write")), 1)
        self.assertEqual(len(trace.by_name("sentence")), len(answer.sentences))

    def test_workers_are_children_of_the_plan(self):
        _, _, _, _, trace = self.execute(self.dev[0])
        plan_span = trace.by_name("plan")[0]
        self.assertEqual(len(trace.children(plan_span.id)), len(trace.by_name("worker")))

    def test_ids_are_sequential(self):
        _, _, _, _, trace = self.execute(self.dev[0])
        self.assertEqual([span.id for span in trace.spans],
                         [f"s{position}" for position in range(1, len(trace.spans) + 1)])


class TestInvariants(Pipeline, unittest.TestCase):
    def test_tokens_add_up(self):
        for question in self.dev:
            if not question.answerable:
                continue
            _, _, _, _, trace = self.execute(question)
            attributed = (
                attribute(trace, "worker") + attribute(trace, "write") + attribute(trace, "read")
            )
            self.assertEqual(attributed, trace.total_tokens, question.id)

    def test_every_sentence_has_provenance(self):
        for question in self.dev:
            if not question.answerable:
                continue
            _, _, _, _, trace = self.execute(question)
            for span in trace.by_name("sentence"):
                self.assertNotIn(span.attributes.get("sub_question"), (None, "unknown"))

    def test_no_orphan_citations(self):
        for question in self.dev + self.test:
            if not question.answerable:
                continue
            _, _, _, _, trace = self.execute(question)
            self.assertEqual(orphan_citations(trace, self.sections), set(), question.id)

    def test_citations_can_be_reconstructed_from_the_trace(self):
        for question in self.dev:
            if not question.answerable:
                continue
            _, _, _, report, trace = self.execute(question)
            self.assertEqual(
                reconstruct_citations(trace), {sentence.section for sentence in report.kept}
            )

    def test_completeness_is_full(self):
        _, _, _, _, trace = self.execute(self.dev[0])
        self.assertEqual(completeness(trace), 1.0)


class TestLocate(Pipeline, unittest.TestCase):
    def test_locates_a_kept_sentence(self):
        _, _, answer, _, trace = self.execute(self.dev[0])
        self.assertIsNotNone(answer.sentences)
        span = locate(trace, answer.sentences[0].text)
        self.assertIsNotNone(span)
        self.assertEqual(span.attributes["section"], answer.sentences[0].section)

    def test_locates_a_dropped_sentence(self):
        for question in self.dev:
            if not question.answerable:
                continue
            _, _, _, report, trace = self.execute(question)
            for check in report.checks:
                if check.kept:
                    continue
                span = locate(trace, check.sentence.text)
                self.assertIsNotNone(span, question.id)
                self.assertFalse(span.attributes["kept"])
                return
        self.skipTest("no dropped sentence in the development split")

    def test_unknown_text_returns_none(self):
        _, _, _, _, trace = self.execute(self.dev[0])
        self.assertIsNone(locate(trace, "this sentence was never in the run"))


class TestDeterminism(Pipeline, unittest.TestCase):
    def test_two_runs_produce_the_same_trace(self):
        first = self.execute(self.dev[1])[4]
        second = self.execute(self.dev[1])[4]
        self.assertEqual(first, second)


class TestFlatLog(Pipeline, unittest.TestCase):
    def test_flat_log_keeps_the_text_but_nothing_else(self):
        _, findings, answer, _, _ = self.execute(self.dev[0])
        events = flat_log(findings, answer)
        self.assertTrue(events)
        metrics = flat_metrics(events)
        self.assertEqual(metrics["said"], 1.0)
        for key in ("completeness", "attribution", "reconstruct", "orphans_found", "localised"):
            self.assertEqual(metrics[key], 0.0, key)


class TestAssembledPipeline(Pipeline, unittest.TestCase):
    def test_no_stale_citation_survives_to_the_answer(self):
        for question in self.dev + self.test:
            if not question.answerable:
                continue
            _, _, _, report, _ = self.execute(question)
            for sentence in report.kept:
                document = self.docs[self.sections[sentence.section].document]
                self.assertTrue(document.current, question.id)

    def test_keeps_the_fan_out_coverage(self):
        full = n = 0
        for question in self.dev:
            if not question.answerable:
                continue
            n += 1
            _, _, _, report, _ = self.execute(question)
            cited = {sentence.section for sentence in report.kept}
            covered = question.facets_covered(cited)
            full += bool(question.facets) and len(covered) == len(question.facets)
        self.assertGreaterEqual(full / n, 0.55, f"{full}/{n}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
