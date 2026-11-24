#!/usr/bin/env python3
"""Verify every label in the golden set before anything trusts it.

    python evals/check_labels.py

`AGENTS.md` requires labels to be verified programmatically, and this corpus makes that
urgent rather than tidy: an `obsolete` span and a `current` span can be the same sentence,
because RFC 7234 and RFC 9111 word several rules identically.

The checks:

  1. ids are unique and every split is present
  2. every `section` exists in the corpus
  3. every `phrase` appears in that section, after whitespace normalisation
  4. every `facet` index is in range, and every facet has at least one current span
  5. an unanswerable question has no evidence at all
  6. an `obsolete` span lives in a document that a later RFC replaces, and the replacing
     document is in the corpus
  7. no question repeats a phrase, and no phrase is a substring of another in the same
     section (which would make two labels indistinguishable)

It exits non-zero and prints every problem. It does not repair anything: a label that fails
here is a bug in the data, and quietly trimming the phrase is how a golden set rots.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.gold import load_questions  # noqa: E402
from scout.text import normalise  # noqa: E402


def main() -> int:
    documents = load_corpus(ROOT)
    sections = section_map(documents)
    docs = document_map(documents)
    questions = load_questions(ROOT / "evals" / "questions.jsonl")

    problems: list[str] = []
    seen_ids: set[str] = set()
    splits: dict[str, int] = {}

    for question in questions:
        if question.id in seen_ids:
            problems.append(f"{question.id}: duplicate id")
        seen_ids.add(question.id)
        splits[question.split] = splits.get(question.split, 0) + 1

        if not question.facets and question.answerable:
            problems.append(f"{question.id}: answerable but no facets")
        if not question.answerable and question.evidence:
            problems.append(f"{question.id}: unanswerable but carries evidence")

        covered: set[int] = set()
        for item in question.evidence:
            section = sections.get(item.section)
            if section is None:
                problems.append(f"{question.id}: no section {item.section!r}")
                continue
            if normalise(item.phrase) not in normalise(section.text):
                problems.append(
                    f"{question.id}: phrase not found in {item.section}: {item.phrase[:60]!r}"
                )
            if not 0 <= item.facet < len(question.facets):
                problems.append(f"{question.id}: facet index {item.facet} out of range")
            if item.status not in ("current", "obsolete"):
                problems.append(f"{question.id}: bad status {item.status!r}")
            if item.status == "current":
                covered.add(item.facet)

            if item.status == "obsolete":
                document = docs[section.document]
                if document.current:
                    problems.append(
                        f"{question.id}: {item.section} is marked obsolete but nothing obsoletes it"
                    )
                elif document.obsoleted_by not in docs:
                    problems.append(
                        f"{question.id}: {item.section} is obsoleted by "
                        f"{document.obsoleted_by}, which is not in the corpus"
                    )

        for index in range(len(question.facets)):
            if index not in covered:
                problems.append(f"{question.id}: facet {index} has no current span")

        # The same sentence can legitimately appear in a current and an obsolete document:
        # RFC 9111 and RFC 7234 word several rules identically. Identical phrasing is only a
        # problem inside one section, where two labels would be indistinguishable.
        seen: dict[tuple[str, str], int] = {}
        for item in question.evidence:
            key = (item.section, normalise(item.phrase))
            seen[key] = seen.get(key, 0) + 1
        for (section_id, phrase), count in seen.items():
            if count > 1:
                problems.append(f"{question.id}: duplicate phrase in {section_id}: {phrase[:50]!r}")

        by_section: dict[str, list[str]] = {}
        for item in question.evidence:
            by_section.setdefault(item.section, []).append(normalise(item.phrase))
        for section_id, phrases in by_section.items():
            for left in phrases:
                for right in phrases:
                    if left != right and left in right:
                        problems.append(f"{question.id}: overlapping phrases in {section_id}")

    if splits.get("dev", 0) < 2:
        problems.append("fewer than two development questions")
    if splits.get("test", 0) < 2:
        problems.append("fewer than two held-out questions")

    current_sections = sum(len(question.current) for question in questions)
    print()
    print(f" documents        {len(documents)}")
    print(f" sections         {len(sections)}")
    print(f" questions        {len(questions)}  ({splits.get('dev', 0)} dev, {splits.get('test', 0)} test)")
    print(f" evidence spans   {current_sections} current, {sum(len(q.obsolete) for q in questions)} obsolete")
    print(f" unanswerable     {sum(1 for q in questions if not q.answerable)}")
    print(f" problems         {len(problems)}")
    for problem in problems:
        print(f"   {problem}")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
