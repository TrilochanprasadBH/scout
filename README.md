# scout

A research agent: it plans, reads in parallel, keeps track of what it spent, and answers with
citations you can check.

This repository is a **course and a product at the same time**. Six stages, each with a lesson
and a test suite, ending in one system that turns a question into a cited answer and a trace
you can audit.

---

## What it does

```
question  ->  plan  ->  read-only sub-agents  ->  budget check
          ->  one writer  ->  citations verified  ->  answer + trace
```

## Why this project exists

`ragkit` retrieved passages and answered from them. `triage` acted, with an approval gate and
an audit trail. `scout` researches: the answer is not in one passage, the work is spread across
documents, and the output has to say which document each sentence came from.

Three problems appear at this size and none of them is about prompt wording:

- **Decomposition.** A question with three facets is three searches, and the plan that splits
  it is a spending decision before it is a language decision.
- **Attribution.** Every sentence needs a citation to a section, the citation has to exist,
  and a citation to a superseded document is wrong even when the sentence is right.
- **Coordination.** Sub-agents may read and report. Exactly one writer merges what they found.

## Requirements

- Python 3.10 or newer
- No third-party packages
- No API key, no network: the default model is a deterministic scripted stand-in over a
  vendored corpus. Real providers are opt-in; see *Providers* below.

## Quick start

```sh
python3 scripts/status.py
python3 evals/check_labels.py
python3 evals/check_docs.py
open GUIDE.md
python3 stages/01_plan/test_stage01.py
```

## How to work in this repo

- **You write code in `src/scout/`.** Each stage adds one module as a stub with a contract.
  Everything else is given: the corpus loader, the search index, the model interface, the
  golden set, the metrics, and the reports.
- **`reference/scout/` is a complete implementation.** Read it after you have tried.
- **`stages/NN_name/` holds the lesson and the tests.** The tests are the specification.
- `IMPL=reference python3 stages/01_plan/test_stage01.py` checks the reference.
- The shared modules must stay byte-identical between `src/` and `reference/`; `status.py`
  fails if they drift.

## Results

| stage | capability | measure | result |
| --- | --- | --- | --- |
| 01 | planning and decomposition | facet coverage, equal passages | baseline 0.808 dev / 0.857 test; plan **0.885** dev / **1.000** test, 2.4 searches per question |
| 02 | read-only sub-agents | facet coverage, equal reads | single context 0.538 dev / 0.214 test; fan-out **0.654** / **0.571**, 17147 vs 20027 tokens |
| 03 | budget control | gold sections cited at a hard ceiling | at 12000 tokens **58%** dev and **71%** test cited, for 4177 / 4846 tokens against 8107 / 10051; overrun 0 at every ceiling |
| 04 | citation accuracy | precision and obsolete citations | 83 dev claims to 60 kept, precision **15% → 25%**, **16** obsolete citations removed, gold coverage unchanged at 58% |
| 05 | synthesis | redundancy and supersession conflicts | redundancy 22 → **0** sentences, gold coverage unchanged, **8** conflicts resolved, answer 87 → 54 sentences |
| 06 | tracing | assembled pipeline | **8/13** dev and **3/7** test questions with every facet, precision **34%** dev / **24%** test, 0 stale citations, every sentence traceable to its sub-question and read |

The stage 01 gain is 2 discordant questions out of 13 on development, `p = 0.50`; six would be
needed for significance. The lesson reports the number, the interval, and the power floor
together, because the second without the third is marketing.

## Layout

```
src/scout/          you implement here, one module per stage
reference/scout/    a complete implementation
stages/NN_name/     one lesson and one test suite per stage
evals/              golden questions, reports, label and doc checks
corpus/             8 RFCs, 711 sections, with the cleaning script and a licence note
scripts/            status, corpus build, live provider
GUIDE.md            the course
FIELD-NOTES.md      sourced production practice
NOTES.md            your log
```

## Data

`corpus/rfc/` holds eight RFCs: HTTP semantics and caching (including one superseded caching
document), TLS 1.3, OAuth 2.0 and bearer tokens, JWT, and JSON. 711 sections, 1.1 MB of cleaned
text, rebuilt by `scripts/fetch_corpus.py` and licensed under the IETF Trust Legal Provisions.
They are vendored rather than fetched so a clone runs offline in one command.

`evals/questions.jsonl` holds 24 questions: 15 development, 9 held out, 4 unanswerable. Every
evidence phrase is verified against the section it names by `evals/check_labels.py`, including
the three spans that sit in a document a later RFC replaces.

## Providers

The default is `scripted`: deterministic, offline, and the source of every number here.

A real model can be used for your own runs, and is never used by the tests:

```sh
export OPENROUTER_API_KEY=...
SCOUT_PROVIDER=openrouter python3 scripts/live.py "How does TLS 1.3 resume a session?"
SCOUT_PROVIDER=openrouter,gemini,openai python3 scripts/live.py "..."   # first that answers wins
```

Keys come from the environment only. `build_model` refuses to fall back to the scripted model,
because a silent fallback would change what a number means.
