"""Stage 04 tests: citation accuracy.

    python stages/04_citations/test_stage04.py
    IMPL=reference python stages/04_citations/test_stage04.py

Most tests here are small and synthetic. That is deliberate: a citation check has five
separate failure modes, and proving each one with a constructed sentence is the only way to
know which check fired.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.budget import run_budgeted  # noqa: E402
from scout.cite import check_answer, relevance, summarise, verify  # noqa: E402
from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.subagent import Sentence  # noqa: E402

TOTAL = 12000
QUESTIONS = ROOT / "evals" / "questions.jsonl"


def load():
    documents = load_corpus(ROOT)
    sections = section_map(documents)
    docs = document_map(documents)
    index = Index(list(sections.values()))
    return sections, docs, index


class TestVerify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sections, cls.docs, cls.index = load()
        cls.good = cls.sections["rfc9111#4.2.2"]
        cls.stale = cls.sections["rfc7234#4.2.2"]

    def check(self, sentence, reads=None, question="How may a cache assign a heuristic expiration time?"):
        return verify(
            sentence,
            question=question,
            sections=self.sections,
            documents=self.docs,
            reads=reads if reads is not None else {sentence.section},
            index=self.index,
        )

    def test_supported(self):
        text = "a cache MAY assign a heuristic expiration time when an explicit time is not specified"
        result = self.check(Sentence(text=text, section="rfc9111#4.2.2"))
        self.assertTrue(result.kept)
        self.assertEqual(result.reason, "supported")
        self.assertGreater(result.relevance, 0.2)

    def test_unresolved(self):
        result = self.check(Sentence(text="anything", section="rfc9999#1"))
        self.assertFalse(result.kept)
        self.assertEqual(result.reason, "unresolved")

    def test_unread(self):
        text = "a cache MAY assign a heuristic expiration time when an explicit time is not specified"
        result = self.check(Sentence(text=text, section="rfc9111#4.2.2"), reads=set())
        self.assertFalse(result.kept)
        self.assertEqual(result.reason, "unread")

    def test_not_in_source(self):
        paraphrase = "a cache can pick any heuristic expiry it likes, whenever it likes"
        result = self.check(Sentence(text=paraphrase, section="rfc9111#4.2.2"))
        self.assertFalse(result.kept)
        self.assertEqual(result.reason, "not-in-source")

    def test_stale(self):
        text = "a cache MAY assign a heuristic expiration time when an explicit time is not specified"
        result = self.check(Sentence(text=text, section="rfc7234#4.2.2"))
        self.assertFalse(result.kept)
        self.assertEqual(result.reason, "stale")

    def test_weak(self):
        text = "The status code is a three-digit integer."
        result = self.check(
            Sentence(text=text, section="rfc9111#4.2.2"),
            question="What must a TLS client do when resuming with a pre-shared key?",
        )
        self.assertFalse(result.kept)
        self.assertIn(result.reason, ("weak", "not-in-source"))

    def test_unread_wins_over_stale(self):
        text = "a cache MAY assign a heuristic expiration time when an explicit time is not specified"
        result = self.check(Sentence(text=text, section="rfc7234#4.2.2"), reads=set())
        self.assertEqual(result.reason, "unread")


class TestRelevance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, _, cls.index = load()

    def test_rare_terms_weigh_more_than_common_ones(self):
        question = "What must a cache do after a successful POST invalidates a URI?"
        on_topic = "A cache MUST invalidate the target URI when it receives a non-error status code"
        off_topic = "A successful response has a status code and a header field"
        self.assertGreater(
            relevance(on_topic, question, self.index),
            relevance(off_topic, question, self.index),
        )

    def test_empty_question_scores_zero(self):
        self.assertEqual(relevance("anything", "the of and", self.index), 0.0)


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sections, cls.docs, cls.index = load()

    def test_one_check_per_sentence_in_order(self):
        answer = (
            Sentence("a cache MAY assign a heuristic expiration time when an explicit time is not specified", "rfc9111#4.2.2"),
            Sentence("The status code is a three-digit integer.", "rfc9111#4.2.2"),
        )
        report = check_answer(
            answer,
            question="How may a cache assign a heuristic expiration time?",
            sections=self.sections,
            documents=self.docs,
            reads={"rfc9111#4.2.2"},
            index=self.index,
        )
        self.assertEqual(len(report.checks), 2)
        self.assertEqual([c.sentence for c in report.checks], list(answer))

    def test_summarise_without_gold_has_no_precision(self):
        answer = (
            Sentence("a cache MAY assign a heuristic expiration time when an explicit time is not specified", "rfc9111#4.2.2"),
        )
        report = check_answer(
            answer,
            question="How may a cache assign a heuristic expiration time?",
            sections=self.sections,
            documents=self.docs,
            reads={"rfc9111#4.2.2"},
            index=self.index,
        )
        summary = summarise(report)
        self.assertEqual(summary["kept"], 1)
        self.assertNotIn("precision", summary)


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sections, cls.docs, cls.index = load()
        cls.model = ScriptedModel()
        cls.dev, cls.test = split_questions(load_questions(QUESTIONS))

    def run_one(self, question):
        built = plan(question.question, self.model, self.index, evidence_budget=20)
        execution = run_budgeted(built, self.index, self.model, TOTAL)
        reads = set()
        for finding in execution.findings:
            reads |= {read.section for read in finding.reads}
        report = check_answer(
            execution.answer,
            question=question.question,
            sections=self.sections,
            documents=self.docs,
            reads=reads,
            index=self.index,
        )
        return execution, report

    def test_no_stale_citation_survives(self):
        for question in self.dev + self.test:
            if not question.answerable:
                continue
            _, report = self.run_one(question)
            for check in report.checks:
                if not check.kept:
                    continue
                document = self.docs[self.sections[check.sentence.section].document]
                self.assertTrue(document.current, f"{question.id} kept a citation to {document.id}")

    def test_the_stale_check_actually_fires(self):
        # q02 and q12 are the questions whose answer looks correct in the superseded document.
        fired = 0
        for question in self.dev + self.test:
            if question.id not in ("q02", "q11", "q12", "q13"):
                continue
            _, report = self.run_one(question)
            fired += report.count("stale")
        self.assertGreater(fired, 0, "no obsolete citation was detected anywhere")

    def test_verification_raises_precision(self):
        def arm(verified):
            total = n = 0.0
            for question in self.dev:
                if not question.answerable:
                    continue
                n += 1
                execution, report = self.run_one(question)
                gold = question.gold_sections("current")
                kept = report.kept if verified else execution.answer
                if not kept:
                    continue
                total += len({s.section for s in kept} & gold) / len(kept)
            return total / n

        self.assertGreater(arm(True), arm(False))

    def test_verification_does_not_lose_gold_sections(self):
        def coverage(verified):
            total = n = 0.0
            for question in self.dev:
                if not question.answerable:
                    continue
                n += 1
                execution, report = self.run_one(question)
                gold = question.gold_sections("current")
                kept = report.kept if verified else execution.answer
                total += len({s.section for s in kept} & gold) / len(gold)
            return total / n

        self.assertGreaterEqual(coverage(True), coverage(False))

    def test_few_gold_claims_are_dropped(self):
        dropped = 0
        for question in self.dev + self.test:
            if not question.answerable:
                continue
            _, report = self.run_one(question)
            gold = question.gold_sections("current")
            dropped += sum(
                1 for check in report.checks if not check.kept and check.sentence.section in gold
            )
        self.assertLessEqual(dropped, 2, f"{dropped} gold claims were dropped")

    def test_deterministic(self):
        question = self.dev[0]
        first = self.run_one(question)
        second = self.run_one(question)
        self.assertEqual(first[1], second[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
