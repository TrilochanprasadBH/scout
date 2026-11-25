# Stage 04 — Citation accuracy

```sh
python stages/04_citations/test_stage04.py
```

17 tests. Run them before writing code: the failures are the contract.

---

## What you will build

`verify`: one sentence in, one verdict out, with the reason. `check_answer`: the same for a whole
answer, in order. The verdict decides whether the sentence stays.

## Why this step is next

Stage 03 produced an answer with 83 sentences across 13 development questions, and 16 of those
sentences cited RFC 7234 — a document RFC 9111 replaced in 2022. Nothing in the pipeline noticed,
because nothing in the pipeline ever compared a citation against the corpus. All four unanswerable
questions got answers too.

That is the failure this stage exists for: the output looked finished. A citation is a claim about
a claim, and it can be wrong in five independent ways.

## The idea

**Five reasons, five fixes.** Each is a separate mechanism, and a system that does only some of
them is verifying less than it claims.

| reason | what is wrong | the fix |
| --- | --- | --- |
| `unresolved` | the cited section does not exist | look the id up |
| `unread` | it exists, but this run never opened it | record reads; compare |
| `not-in-source` | the quote was paraphrased or invented | require the quote to be in the text |
| `stale` | the document was replaced by a later one | carry the obsoleted-by relation |
| `weak` | it does not bear on the question | score relevance, threshold it |

The first four are mechanical. `weak` is a judgment, and it is the only one with a threshold.

**The first rule that fires wins, and the order is part of the contract.**

```
unresolved -> unread -> not-in-source -> stale -> weak -> supported
```

A fabricated quote in a missing section is reported as `unresolved`, because that is the fact
somebody fixing it needs first. Reporting it as `stale` would send them to the wrong file.

**Existence is not relevance.** Every claim here is a sentence copied out of the cited section, so
`not-in-source` never fires on this pipeline. It is still checked, because a model that paraphrases
would slip past a system that only checks relevance, and the two failures are indistinguishable
after the fact.

**Relevance is IDF-weighted, not a word count.**

```
relevance(claim, question) = sum(idf(t) : t in question ∩ claim)
                             / sum(idf(t) : t in question)
```

Sharing "the request" proves nothing; sharing "idempotent" proves a lot. The threshold is an
operating point, not a truth, and the sweep below is the honest way to choose it.

**The verifier never sees the gold labels.** It gets the question, the corpus, and the read set.
The report compares its decisions against the labels afterwards. If `verify` imported `gold`, every
number in this lesson would be a lookup table wearing a lab coat.

## The measurement

Pipeline: the stage 03 budgeted run at 12,000 tokens. "Dropped" is sentences removed by the
verifier. `precision` counts sentences citing a gold section; `gold` counts gold sections still
present. Evaluation sees the labels; the verifier does not.

| split | arm | claims | kept | dropped | precision | gold | stale | weak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev | unverified | 83 | 83 | 0 | 15% | 58% | 16 | 0 |
| dev | **verified** | 83 | 60 | 23 | **25%** | 58% | **0** | 7 |
| test | unverified | 46 | 46 | 0 | 17% | 71% | 8 | 0 |
| test | **verified** | 46 | 35 | 11 | **22%** | 71% | **0** | 3 |

**Every obsolete citation is gone.** 16 on development, 8 on held out, all detected and removed.
That is the number this stage can defend absolutely: it is mechanical, and the test
`test_no_stale_citation_survives` walks every kept check and asserts the document is current.

**Precision improves and coverage does not move.** 15% to 25% on development, 17% to 22% on held
out, with gold coverage identical at 58% and 71%. Zero gold claims were dropped (`false drop` is 0
in both splits), which is the number to watch: a verifier that raises precision by discarding good
evidence has not improved anything.

**Precision is still low, and the reason matters.** 25% means three quarters of the surviving
sentences cite a section the golden set does not name. Most of them are *true statements from the
corpus that do not answer the question asked*: a section on freshness invalidation is a real quote
and a real citation, and it is not the facet. Gold sections are the intended evidence, not the only
true sentences in the corpus, so 25% is a lower bound on accuracy and an upper bound on usefulness.

**The threshold is an operating point.** Sweep over both splits, answerable questions only:

| threshold | kept | precision | gold | weak drops | gold dropped |
| --- | --- | --- | --- | --- | --- |
| 0.10 | 5.2 | 22% | 62% | 0 | 0 |
| **0.20** | 4.8 | 24% | 62% | 10 | 0 |
| 0.30 | 3.2 | 24% | 50% | 41 | 7 |
| 0.40 | 2.0 | 24% | 38% | 64 | 15 |
| 0.50 | 1.3 | 14% | 22% | 79 | 22 |
| 0.60 | 0.5 | 5% | 8% | 95 | 31 |

Above 0.20, precision does not improve and coverage collapses: the filter starts deleting the
sentences that were right. 0.20 is chosen because it is the last point with zero gold drops, not
because it is the point with the best-looking precision.

**The four unanswerable questions are still not fixed.** They produced 10 sentences and 7 survived
verification. A sentence can quote the corpus exactly, cite a current section, and still fail to
answer a question the corpus cannot answer. `relevance` measures whether a claim is about the
question's words, not whether the corpus contains the answer. That gap needs a different mechanism
— a judge, or an abstention step — and this project does not have one.

## Field notes

**Anthropic, *How we built our multi-agent research system* (June 2025).**
anthropic.com/engineering/multi-agent-research-system
Their pipeline ends with a dedicated step: "once sufficient information is gathered, the system
exits the research loop and passes all findings to a CitationAgent, which processes the documents
and research report to identify specific locations for citations. This ensures all claims are
properly attributed to their sources." Their judge rubric scores "citation accuracy (do the cited
sources match the claims?)" separately from factual accuracy and completeness.
**In this project.** `verify` is that CitationAgent's mechanical half, restricted to what can be
checked without a model: existence, read provenance, verbatim quotation, currency. Not built: the
judgment half. Their rubric needs a reader who can decide whether a passage answers a question, and
every model call in this repository is scripted.

**Cognition, *Don't Build Multi-Agents* (June 2025).** cognition.ai/blog/dont-build-multi-agents
Argues that subagents should return answers rather than actions, because an answer can be checked
and an action cannot be undone.
**In this project.** Stage 02's workers return sentences with sections, which is what makes this
stage possible: a claim with a pointer can be verified, and a claim without one cannot. Not built:
any verification of the *reasoning* that selected the claim.

## Do this

1. Read `src/scout/cite.py`. `Check`, `CitationReport`, `relevance` and `best_quote` are given.
2. Implement `verify`, with the five reasons in the contract's order.
3. Implement `check_answer` so it preserves order and produces one check per sentence.
4. Run the tests, then the report, then the sweep.
5. Read `--show-errors 2` and look at what was dropped. Some of it was true.

```sh
python stages/04_citations/test_stage04.py
IMPL=reference python evals/report_citations.py --show-errors 2
IMPL=reference python evals/report_citations.py --sweep
```

## Check yourself

Expected: 17 tests pass. The table reproduces 16 and 8 obsolete citations removed, precision rising,
coverage flat, zero gold drops.

If `not-in-source` never fires, you are comparing against the section's *sentences* rather than its
text. The claim has to appear in the text; sentence splitting is only for choosing the quote.

If `test_verification_raises_precision` fails, check the order: a `stale` claim that is also `weak`
must be reported once, and the first matching rule decides.

If most claims are dropped as `weak`, your relevance denominator is wrong. It sums over the
question's *content* terms, after stopword removal.

## If you are stuck

**Hint 1.** `verify` is five `if` blocks that return. There is no state and no accumulation; the
whole function is a decision table.

**Hint 2.** `normalise` collapses whitespace and lowercases. Both sides of the containment check
need it, because the model returns a sentence and the section stores a paragraph.

**Hint 3.** `relevance` returns a number in [0, 1]. Print it for one known-good and one known-bad
sentence before choosing a threshold; the difference is usually larger than expected.

## What a senior would notice

**That four of the five checks are mechanical.** The interesting claim is not "we improved
precision"; it is "three classes of citation error are now impossible by construction". A mechanical
check does not drift with the model.

**That the ablation is the deliverable.** Reporting 25% precision without 15% would look like a
weak system. Reporting both, plus the sweep, plus the 7 sentences that still answer a question the
corpus cannot answer, is a system somebody can decide to ship.

**That the threshold was chosen for a reason and could be chosen differently.** The cost of a wrong
answer and the cost of a missing answer are not equal, and the table gives whoever owns that
decision the numbers to make it.
