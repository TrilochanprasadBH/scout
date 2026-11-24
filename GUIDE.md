# Guide

Six stages. Each has a lesson in `stages/NN_name/README.md` and tests that define what done means.

Read this page once. Then work one stage at a time.

---

## 1. How to work

For each stage:

1. Read the lesson, all of it, before writing code.
2. Run the tests and read the failures; they describe the contract.
3. Implement in `src/scout/`.
4. Run the tests until they pass.
5. Run the report, and compare the number against the stage lesson's table.
6. Write three lines in `NOTES.md`.

If you are stuck for more than 30 minutes, read `reference/`. Diff it against yours, then close it
and rewrite your version from memory.

Two rules that are not about code:

- **Never tune on the held-out split.** Every lesson reports development numbers and then the held
  out number once. If you look at held-out failures and adjust, the number stops being a test.
- **Never report a proportion without its denominator and its interval.** Every table in this
  project has both.

## 2. The stages

| stage | you build | the idea it teaches | ends with |
| --- | --- | --- | --- |
| 01 | planner | a plan is an allocation of searches, and it can make recall worse | dev facet coverage 0.808 → 0.885, 2.4 searches per question, `p = 0.50` |
| 02 | read-only workers | a worker that cannot write cannot race, and its output is reproducible | 0.538 → **0.654** dev, 0.214 → **0.571** held out, at equal reads |
| 03 | budget | a budget that is not enforced in code is a wish | same answer for **52%** and **48%** of the tokens; overrun 0 at every ceiling |
| 04 | citation check | existence, provenance, quotation, currency, relevance are five checks | **16** and **8** obsolete citations removed; precision 15% → 25% |
| 05 | one writer | redundancy is a choice, and conflicts are decided by a fact | redundancy **22 → 0**, **8** conflicts resolved, gold coverage unchanged |
| 06 | trace | a sentence must be traceable to the read that produced it | every invariant holds; **34%** precision on the assembled pipeline, 0 stale |

## 3. What you should be able to say after each stage

**After 01:** "Decomposition moved development facet coverage from 0.808 to 0.885 for 2.4 times the
searches, which is two questions out of thirteen and `p = 0.50`. The rare-term anchor I expected to
help cost a search and lost coverage, so it is off and there is a test that fails if someone turns it
back on."

**After 02:** "Fan-out beat one big context on both splits at equal reads — 0.654 against 0.538 on
development, 0.571 against 0.214 held out — and it did not cost more tokens. It also answered two
questions it could not answer, which is what stage 04 exists for."

**After 03:** "At 12,000 tokens the budgeted run produced the same answer for half the money. Below
the work it drops sub-questions and says which; the uncontrolled arm spent 172% of the ceiling and
lost the same evidence silently by cutting the answer's tail."

**After 04:** "Four classes of citation error are now impossible by construction: invented sections,
sections never read, paraphrased quotes, and superseded documents. Relevance is a threshold, and the
sweep shows the point where raising it starts deleting correct sentences."

**After 05:** "One write, after deduplication and conflict resolution. The answer shrank by 38% with
identical gold coverage, and the fourteen conflicts were resolved by the obsoleted-by relation rather
than by which sentence sounded better. It detects supersession, not contradiction."

**After 06:** "Every sentence in the answer maps to a sub-question, a worker span and a read span, and
the tokens on the trace are the tokens that were spent. A flat log of the same run can tell you what
was said and nothing else."

## 4. The rules

**The model is scripted by default.** Every number in this repository comes from a deterministic
stand-in over a vendored corpus, so a clone runs with no key and the numbers do not move between
runs. The real providers in `model.py` are for your own experiments.

**The graded path never reaches the network.** `scripts/live.py` is the only thing that can, and no
test imports it.

**Each stage adds a module.** No stage rewrites an earlier one, which is what lets you diff them and
what keeps earlier measurements meaningful.

**Shared modules are identical in `src/` and `reference/`.** `scripts/status.py` fails if they drift,
because a divergence there changes what a test means.

**Every documented number has a check.** `evals/check_docs.py` recomputes the headline numbers from
the reference and asserts the formatted value appears in the documents that quote it.

## 5. When you finish

All six stages are complete. The finished system answers the part of the interview that `ragkit` and
`triage` cannot: what happens when the answer is assembled from several sources, and how you prove
where each sentence came from.

What it still cannot do, stated here so it is not discovered late:

- **Answer what the corpus cannot.** Four unanswerable questions still get answers after verification.
  `relevance` measures whether a claim is about the question's words, not whether the corpus holds the
  answer.
- **Detect contradiction.** Two current documents that disagree pass through untouched.
- **Retry.** One round of research, no loop.
- **Run in parallel.** `schedule` simulates completion order; nothing spawns a thread.
