"""Stage 05 tests: synthesis.

    python stages/05_synthesis/test_stage05.py
    IMPL=reference python stages/05_synthesis/test_stage05.py

The conflict tests are synthetic, because a real supersession pair only appears in three
questions and a test that depends on those three cannot say why it passed.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMPL = os.environ.get("IMPL", "src")
sys.path.insert(0, str(ROOT / IMPL))

from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions, split_questions  # noqa: E402
from scout.model import Reply, ScriptedModel  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.subagent import Finding, Sentence, run_all  # noqa: E402
from scout.synth import (  # noqa: E402
    Candidate,
    MAX_SENTENCES,
    candidates,
    concatenate,
    deduplicate,
    find_conflicts,
    synthesise,
)
from scout.text import normalise  # noqa: E402

BUDGET = 20
QUESTIONS = ROOT / "evals" / "questions.jsonl"


def load():
    documents = load_corpus(ROOT)
    return (
        document_map(documents),
        section_map(documents),
        Index(list(section_map(documents).values())),
        ScriptedModel(),
    )


def finding(sub_question, text, section):
    return Finding(
        sub_question=sub_question,
        question="q",
        sentences=(Sentence(text=text, section=section),),
        reads=(),
        tokens=0,
        prompt_tokens=0,
        answerable=True,
    )


class CountingModel:
    """Wraps the scripted model and counts calls, which is how "one writer" is proven."""

    name = "counting"

    def __init__(self, inner=None):
        self.inner = inner or ScriptedModel()
        self.calls = 0

    def complete(self, task, payload, *, max_tokens=512):
        self.calls += 1
        return self.inner.complete(task, payload, max_tokens=max_tokens)


class TestCandidates(unittest.TestCase):
    def test_order_follows_sub_question(self):
        findings = (
            finding("sq.2", "second", "rfc9111#4.2"),
            finding("sq.1", "first", "rfc9111#4.1"),
        )
        self.assertEqual([c.sub_question for c in candidates(findings)], ["sq.1", "sq.2"])

    def test_one_candidate_per_sentence(self):
        findings = (
            Finding(
                sub_question="sq.1",
                question="q",
                sentences=(Sentence("a", "rfc9111#4.1"), Sentence("b", "rfc9111#4.2")),
                reads=(),
                tokens=0,
                prompt_tokens=0,
                answerable=True,
            ),
        )
        self.assertEqual(len(candidates(findings)), 2)


class TestDeduplicate(unittest.TestCase):
    def test_removes_repeats_and_reports_the_count(self):
        items = (
            Candidate("The  cache is fresh.", "rfc9111#4.2", "sq.1"),
            Candidate("the cache is fresh", "rfc9111#4.2", "sq.2"),
            Candidate("something else", "rfc9111#4.4", "sq.2"),
        )
        kept, removed = deduplicate(items)
        self.assertEqual(removed, 1)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0].sub_question, "sq.1")

    def test_keeps_input_order(self):
        items = (
            Candidate("b", "rfc9111#4.4", "sq.2"),
            Candidate("a", "rfc9111#4.2", "sq.1"),
        )
        kept, _ = deduplicate(items)
        self.assertEqual([item.text for item in kept], ["b", "a"])


class TestConflicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs, cls.sections, _, _ = load()

    def test_superseded_side_is_dropped(self):
        items = (
            Candidate("old rule", "rfc7234#4.2.2", "sq.1"),
            Candidate("new rule", "rfc9111#4.2.2", "sq.1"),
        )
        conflicts, clean = find_conflicts(items, self.docs, self.sections)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].kept.section, "rfc9111#4.2.2")
        self.assertEqual(conflicts[0].dropped.section, "rfc7234#4.2.2")
        self.assertEqual([item.section for item in clean], ["rfc9111#4.2.2"])

    def test_different_sub_questions_do_not_conflict(self):
        items = (
            Candidate("old rule", "rfc7234#4.2.2", "sq.1"),
            Candidate("new rule", "rfc9111#4.2.2", "sq.2"),
        )
        conflicts, clean = find_conflicts(items, self.docs, self.sections)
        self.assertEqual(conflicts, ())
        self.assertEqual(len(clean), 2)

    def test_two_current_documents_do_not_conflict(self):
        items = (
            Candidate("a", "rfc9111#4.2.2", "sq.1"),
            Candidate("b", "rfc9110#9.2.1", "sq.1"),
        )
        conflicts, clean = find_conflicts(items, self.docs, self.sections)
        self.assertEqual(conflicts, ())
        self.assertEqual(len(clean), 2)

    def test_reason_names_both_sections(self):
        items = (
            Candidate("old", "rfc7234#5.5", "sq.1"),
            Candidate("new", "rfc9111#5.5", "sq.1"),
        )
        conflicts, _ = find_conflicts(items, self.docs, self.sections)
        self.assertIn("rfc7234#5.5", conflicts[0].reason)
        self.assertIn("rfc9111#5.5", conflicts[0].reason)


class TestSynthesise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs, cls.sections, cls.index, cls.model = load()
        cls.dev, cls.test = split_questions(load_questions(QUESTIONS))

    def findings_for(self, question):
        built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        return run_all(built.sub_questions, self.index, self.model, max_reads=per_worker)

    def test_uses_exactly_one_model_call(self):
        question = self.dev[0]
        counter = CountingModel(self.model)
        synthesise(
            question.question,
            self.findings_for(question),
            counter,
            documents=self.docs,
            sections=self.sections,
        )
        self.assertEqual(counter.calls, 1)

    def test_respects_the_sentence_cap(self):
        question = self.dev[1]
        answer = synthesise(
            question.question,
            self.findings_for(question),
            self.model,
            documents=self.docs,
            sections=self.sections,
            max_sentences=2,
        )
        self.assertLessEqual(len(answer.sentences), 2)

    def test_permutation_invariant(self):
        question = self.dev[2]
        findings = self.findings_for(question)
        forward = synthesise(
            question.question, findings, self.model, documents=self.docs, sections=self.sections
        )
        backward = synthesise(
            question.question,
            tuple(reversed(findings)),
            self.model,
            documents=self.docs,
            sections=self.sections,
        )
        self.assertEqual(forward, backward)

    def test_removes_redundancy_that_concatenation_keeps(self):
        redundant_concat = redundant_synth = 0
        for question in self.dev:
            if not question.answerable:
                continue
            findings = self.findings_for(question)
            joined = concatenate(findings)
            answer = synthesise(
                question.question, findings, self.model, documents=self.docs, sections=self.sections
            )
            redundant_concat += len(joined.sentences) - len({normalise(s.text) for s in joined.sentences})
            redundant_synth += len(answer.sentences) - len({normalise(s.text) for s in answer.sentences})
        self.assertGreater(redundant_concat, 0)
        self.assertEqual(redundant_synth, 0)

    def test_cap_is_the_only_length_limit(self):
        self.assertEqual(MAX_SENTENCES, 6)


class TestMeasurement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs, cls.sections, cls.index, cls.model = load()
        cls.dev, cls.test = split_questions(load_questions(QUESTIONS))

    def findings_for(self, question):
        built = plan(question.question, self.model, self.index, evidence_budget=BUDGET)
        per_worker = max(1, BUDGET // max(1, len(built.sub_questions)))
        return run_all(built.sub_questions, self.index, self.model, max_reads=per_worker)

    def test_conflicts_are_found_on_the_superseded_questions(self):
        found = 0
        for question in self.dev:
            if question.id not in ("q11", "q13"):
                continue
            answer = synthesise(
                question.question,
                self.findings_for(question),
                self.model,
                documents=self.docs,
                sections=self.sections,
            )
            found += len(answer.conflicts)
        self.assertGreater(found, 0, "no supersession conflict was detected")

    def test_synthesis_keeps_at_least_as_many_gold_sections(self):
        for label, subset in (("dev", self.dev), ("test", self.test)):
            before = after = 0
            for question in subset:
                if not question.answerable:
                    continue
                findings = self.findings_for(question)
                gold = question.gold_sections("current")
                before += len({s.section for s in concatenate(findings).sentences} & gold)
                answer = synthesise(
                    question.question, findings, self.model, documents=self.docs, sections=self.sections
                )
                after += len({s.section for s in answer.sentences} & gold)
            self.assertGreaterEqual(after, before * 0.95, f"{label}: {after} vs {before}")

    def test_synthesis_shortens_the_answer(self):
        before = after = 0
        for question in self.dev:
            if not question.answerable:
                continue
            findings = self.findings_for(question)
            before += len(concatenate(findings).sentences)
            after += len(
                synthesise(
                    question.question, findings, self.model, documents=self.docs, sections=self.sections
                ).sentences
            )
        self.assertLess(after, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
