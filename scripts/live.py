#!/usr/bin/env python3
"""Run one research question through a real provider.

    export OPENROUTER_API_KEY=...
    python scripts/live.py "How does TLS 1.3 resume a session?"

    SCOUT_PROVIDER=openrouter,gemini,openai python scripts/live.py "..." --budget 20000

This is the only script in the repository that can reach the network, and no test imports it. The
pipeline is the assembled one: plan, one worker per sub-question, one write, verification. There is
no budget enforcement here because a real provider's token counts are not the counts this project's
`text.count` produces, and pretending otherwise would make the numbers lie.

Keys come from the environment. There is no `--key` flag on purpose: a key on a command line ends up
in a shell history and a process list.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The working implementation by default: this script exists to try a provider, not to test a stub.
IMPL = os.environ.get("IMPL", "reference")
sys.path.insert(0, str(ROOT / IMPL))

from scout.cite import check_answer, summarise  # noqa: E402
from scout.corpus import document_map, load_corpus, section_map  # noqa: E402
from scout.model import ProviderError, build_model  # noqa: E402
from scout.plan import plan  # noqa: E402
from scout.search import Index  # noqa: E402
from scout.subagent import run_all  # noqa: E402
from scout.synth import synthesise  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--reads", type=int, default=4, help="sections per worker")
    args = parser.parse_args()

    try:
        model = build_model()
    except (ProviderError, ValueError) as error:
        print(f"provider: {error}")
        print("set SCOUT_PROVIDER and the matching key, or use the offline reports instead")
        return 2

    documents = load_corpus(ROOT)
    sections = section_map(documents)
    docs = document_map(documents)
    index = Index(list(sections.values()))

    built = plan(args.question, model, index)
    findings = run_all(built.sub_questions, index, model, max_reads=args.reads)
    answer = synthesise(
        args.question, findings, model, documents=docs, sections=sections
    )
    reads = set()
    for finding in findings:
        reads |= {read.section for read in finding.reads}
    report = check_answer(
        answer.sentences,
        question=args.question,
        sections=sections,
        documents=docs,
        reads=reads,
        index=index,
    )

    print()
    print(f" provider        {model.name} ({IMPL})")
    print(f" sub-questions   {len(built.sub_questions)}")
    for item in built.sub_questions:
        print(f"   {item.id} {item.query}")
    print(f" conflicts       {len(answer.conflicts)}")
    print(f" sentences       {len(answer.sentences)} produced, {len(report.kept)} kept")
    print()
    for sentence in report.kept:
        print(f" - {sentence.text}")
        print(f"   {sentence.section}")
    dropped = [(check.reason, check.sentence.section) for check in report.checks if not check.kept]
    if dropped:
        print()
        print(" dropped")
        for reason, section in dropped:
            print(f"   {reason:<13} {section}")
    print()
    print(f" summary         {summarise(report)}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
