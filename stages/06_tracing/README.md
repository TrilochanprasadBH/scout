# Stage 06 — Tracing

```sh
python stages/06_tracing/test_stage06.py
```

18 tests. Run them before writing code: the failures are the contract.

---

## What you will build

`record`: a run as a tree of spans, with tokens, parents, reads, and one span per output sentence
carrying the sub-question and section it came from. Plus the functions an incident review needs:
`locate`, `orphan_citations`, `reconstruct_citations`, `attribute`, `completeness`.

## Why this step is next

Every stage before this one produced a number and no way to explain it. When the verifier drops a
sentence, nothing in the system can say which worker produced it, which read it came from, or what
that worker cost. The only available answer is to re-run the pipeline and add a print, which is how
a one-hour investigation becomes a day.

`triage` stage 05 made the same argument for actions: if it cannot be replayed, it did not happen.
This is the research version, and it is harder, because the thing that has to be reconstructed is
not an action but an attribution.

## The idea

**Provenance is a field, not a reconstruction.** After stage 05 deduplicates, the writer returns
sentences with sections. Nothing in that object says which worker found the sentence. So the trace
carries it:

```python
Span(name="sentence", attributes={
    "text": "...",
    "section": "rfc9111#4.2.2",
    "sub_question": "sq.3",
    "kept": False,
})
```

The `sub_question` attribute is what makes `locate` useful. Without it, the trace can say the answer
is wrong and not where it came from.

**Four invariants, each one testable:**

| invariant | test | what breaks without it |
| --- | --- | --- |
| tokens add up | worker + read + write = total | cost reports become fiction |
| every sentence has provenance | `sub_question` is never `"unknown"` | incident review cannot localise |
| no orphan citations | kept section ⊆ read sections | a claim from nowhere looks sourced |
| the same run gives the same trace | two runs compare equal | diffs are noise |

**The trace is built from artefacts, not instrumented.** `record` takes the plan, the findings, the
answer and the citation report. Nothing inside the worker knows it is being traced, which means
tracing cannot change behaviour — the failure mode where adding observability moves the numbers.

**Ids are `s1`, `s2`, ... in creation order.** No timestamps, no uuids, no wall clock. A trace you
cannot diff is a trace you cannot use to find out what changed.

## The measurement

The first table is the system assembled, which is the only configuration in this project where every
stage is present: plan, fan-out, one write, verification, trace.

| split | answers with a gold section | gold | every facet | 95% CI | precision | stale | tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 9/13 | 0.65 | 8/13 | 36%–82% | 34% | 0 | 22945 |
| test | 5/7 | 0.57 | 3/7 | 16%–75% | 24% | 0 | 28925 |

Compared with the stage it started from:

| configuration | coverage | precision | stale citations |
| --- | --- | --- | --- |
| stage 02 fan-out | 0.654 | 24% | not measured |
| stage 06 assembled | **0.65** | **34%** | **0** |

The fan-out's coverage survives two filter stages and one rewrite, precision rises ten points, and
no superseded citation reaches the answer. That is the compounding claim this project can defend: the
stages are not five unrelated improvements.

The second table is what the record buys, against a flat log of the same run:

| metric | trace | flat log |
| --- | --- | --- |
| what was said | 100% | 100% |
| completeness | 100% | 0% |
| cost attribution | 100% | 0% |
| citations reconstructed from the record | 100% | 0% |
| orphan citations found | 100% | 0% |
| dropped sentence localised to its sub-question | 100% | 0% |

**Read the flat-log column as "cannot", not "failed".** A log of messages has no token counts, no
read records and no parent links, so the questions are not answerable from it, not answered wrongly.
It does one thing perfectly, which is why teams keep them: the text is all there.

**The exactness is the point.** Six 100% rows look like a marketing table until you notice that every
one of them is a structural invariant with a test that fails if it lapses. `completeness` is a field
check; `attribution` sums three numbers and compares; `reconstruct` derives the citation set a second
time and compares; `localised` walks every dropped sentence and asks the trace where it came from.
None of them is a judgment call, which is why none of them is 97%.

**A worked incident**, from `--show-errors 1`:

```
q01 weak          rfc9110#9.1
     sub-question sq.3 -> s17 -> read span s24
     'Additional methods, outside the scope of this specification, have been specified for use i'
```

Question, sub-question, worker span, read span, section, reason. That is the whole output of the
stage, and it is what someone needs at 3am.

## Field notes

**Anthropic, *How we built our multi-agent research system* (June 2025).**
anthropic.com/engineering/multi-agent-research-system
On diagnosis: "users would report agents 'not finding obvious information', but we couldn't see why.
Were the agents using bad search queries? Choosing poor sources? Hitting tool failures? Adding full
production tracing let us diagnose why agents failed and fix them systematically." They also report
that agents "make dynamic decisions and are non-deterministic between runs, even with identical
prompts", which is why they monitor decision patterns rather than conversation contents.
**In this project.** `locate` is that diagnosis path with the model removed: deterministic, so the
trace is reproducible, and per-sentence, so "why is this sentence here" has an answer. Not built:
production tracing across a fleet, sampling, or privacy filtering, all of which exist because real
traces contain user data.

**Cognition, *Don't Build Multi-Agents* (June 2025).** cognition.ai/blog/dont-build-multi-agents
The first principle is to "share context, and share full agent traces, not just individual messages",
because a message without the decisions around it is not enough context to act on.
**In this project.** The `sentence` span carries the sub-question that produced it, which is the
minimum of a shared trace. Not built: sharing one worker's reads with another during the run, which
Cognition recommends and which would break the isolation stage 02 depends on. The trace is the
post-hoc version of the same idea, and the trade is stated rather than hidden.

## Do this

1. Read `src/scout/trace.py`. `Span` and `Trace` are given as dataclasses with four unimplemented
   properties.
2. Implement `Trace.root`, `total_tokens`, `children` and `by_name`.
3. Implement `record`, in the order the contract lists: root, plan, workers, reads, write, sentences.
4. Implement `locate`, `orphan_citations`, `reconstruct_citations`, `attribute`, `completeness`.
5. Run the tests, then the report, then `--show-errors 1`.

```sh
python stages/06_tracing/test_stage06.py
IMPL=reference python evals/report_trace.py --show-errors 1
```

## Check yourself

Expected: 18 tests pass. Every trace invariant holds. The assembled pipeline shows 8/13 and 3/7
questions with every facet covered, 34% and 24% precision, and zero stale citations.

If `test_tokens_add_up` fails, you are counting a worker's tokens twice, usually by putting
`finding.tokens` on the worker span and again on each read span. The read spans are a breakdown of
the worker's cost, and the contract sums all three names, so a read span must carry only what it
read.

If `test_every_sentence_has_provenance` fails with `"unknown"`, the fingerprint of the writer's
sentence does not match any finding's sentence. Print both fingerprints; the usual cause is the
writer returning a sentence it joined from two candidates.

If `completeness` is below 1, run it span by span. It reports the first missing field in the message
if you assert on it directly.

## If you are stuck

**Hint 1.** Build the trace with a tiny helper that appends and returns the new id. Recording a tree
with raw list indices is how parents end up pointing at the wrong span.

**Hint 2.** Provenance comes from the findings, not from the writer. Build `fingerprint -> sub_question`
from the findings first, then look up each output sentence.

**Hint 3.** `kept` comes from the citation report, matched by fingerprint too. A sentence can appear
in the trace and not in the kept set; that is the normal case for a dropped claim.

## What a senior would notice

**That the trace is deterministic.** No clock, no uuid, no sampling. A trace that changes between
identical runs cannot answer "what changed", which is the only question anyone asks it.

**That the trace is built from artefacts rather than instrumented into the loop.** Observability that
changes timing changes behaviour, and in an agent that spends a budget it also changes the output.

**That the invariants are the product.** The interesting claim is not "we have traces". It is "a
sentence cannot appear in the answer without a read behind it, and the tokens on the trace are the
tokens that were spent". Both are checkable, and both have a test that would fail tomorrow if someone
changed the writer.

**That the numbers are the same numbers.** Coverage 0.65 here and 0.654 in stage 02, precision 34%
here and 24% there, tokens 22945 against 17147 plus a writer and a verifier. A stage 06 that reported
better numbers than its predecessors would be reporting a different pipeline.
