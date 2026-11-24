"""The golden set, given.

One line of JSON per research question. Every claim in it is checkable:

  `facets`     the sub-questions a careful researcher would have to answer. A plan is scored
               on how many of these it reaches, not on how it words them.
  `evidence`   spans that answer a facet. `section` is a section id, `phrase` is text that
               must appear in that section, `facet` is the index it answers, and `status`
               is `current` or `obsolete`.
  `answerable` false means the corpus cannot answer it and the agent must refuse.

The `status` field is the part that is specific to this corpus. `obsolete` marks a span in a
document that a later RFC replaces: it looks like a correct answer, and it is not. A citation
to one is a real error with a real cause, and `check_labels.py` verifies that every obsolete
span really does live in a superseded document.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    section: str
    phrase: str
    facet: int
    status: str


@dataclass(frozen=True)
class Question:
    id: str
    split: str
    question: str
    answerable: bool
    facets: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    notes: str = ""

    @property
    def current(self) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if item.status == "current")

    @property
    def obsolete(self) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if item.status == "obsolete")

    def gold_sections(self, status: str | None = None) -> set[str]:
        return {
            item.section
            for item in self.evidence
            if status is None or item.status == status
        }

    def facets_covered(self, sections: set[str]) -> set[int]:
        """Which facets have at least one current span inside the retrieved sections."""
        return {
            item.facet for item in self.current if item.section in sections
        }


def load_questions(path: pathlib.Path) -> list[Question]:
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        questions.append(
            Question(
                id=row["id"],
                split=row["split"],
                question=row["question"],
                answerable=bool(row["answerable"]),
                facets=tuple(row["facets"]),
                evidence=tuple(Evidence(**item) for item in row["evidence"]),
                notes=row.get("notes", ""),
            )
        )
    return sorted(questions, key=lambda question: question.id)


def split_questions(questions: list[Question]) -> tuple[list[Question], list[Question]]:
    """Development first. The held-out split is looked at once, at the end."""
    return (
        [question for question in questions if question.split == "dev"],
        [question for question in questions if question.split == "test"],
    )
