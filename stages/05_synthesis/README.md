# Stage 05 — Synthesis

```sh
python stages/05_synthesis/test_stage05.py
```

16 tests. Run them before writing code: the failures are the contract.

---

## What you will build

`synthesise`: findings in, one answer out, with duplicates removed, supersession conflicts
resolved, and exactly one model call.

## Why this step is next

Stage 02's findings, joined end to end, produce 87 sentences for 13 development questions. Twenty
two of them are repeats, and 17 cite a document that was replaced in 2022 — in several cases
alongside the document that replaced it, so the answer states an old rule and a new rule and leaves
the reader to choose.

That is not a formatting problem. Two claims that cannot both be right, presented with equal
authority and no note, is the failure mode multi-agent systems are criticised for. The fix is not a
better prompt; it is that exactly one thing writes.

## The idea

**One writer is an architectural property, not an instruction.** The pipeline prepares candidates
deterministically and then calls the model once. `CountingModel` in the tests counts calls and
asserts the number is 1, which is the only way to know that a second author has not crept in.

**Four steps before the writer touches anything:**

| step | mechanism | why before the writer |
| --- | --- | --- |
| flatten | sort findings by sub-question id | the same input order every run |
| deduplicate | fingerprint each sentence | the writer should not choose between twins |
| conflicts | obsoleted-by relation between cited documents | authority is decided by a fact, not by style |
| cap | `max_sentences = 6` | one per facet with slack, not a document |

**Deduplication has to be fingerprinting, not equality.** The same sentence arrives from two workers
with different capitalisation and sometimes a trailing full stop, because each worker quoted it from
the same paragraph independently. `fingerprint` normalises case and whitespace and strips trailing
punctuation; string equality catches almost none of the real duplicates.

**A conflict is a pair, not a flag.** The rule:

```
if section A belongs to document D1 and section B belongs to document D2
and D1.obsoleted_by == D2
and A and B answer the same sub-question
then keep B, drop A, record both
```

The same-sub-question condition matters. RFC 7234 and RFC 9111 discuss dozens of unrelated rules; a
worker citing 7234 on freshness and another citing 9111 on invalidation is not a conflict, it is two
answers to two questions. Requiring the same sub-question is what keeps the detected conflicts
meaningful, and it is also why some obsolete citations survive this stage.

**What this does not detect.** Two *current* documents that contradict each other pass through
untouched. So do two claims from the same document that disagree. The check is about authority, not
about truth, and the lesson says so rather than implying a contradiction detector exists.

## The measurement

Both arms start from identical findings: the stage 02 fan-out over each plan. Only the way findings
become an answer differs. `obsolete` counts sentences citing a superseded document that survive into
the answer.

| split | arm | sentences | distinct | redundant | gold | conflicts | obsolete |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | concatenate | 87 | 65 | 22 | 13 | 0 | 17 |
| dev | **synthesise** | 54 | 54 | **0** | 13 | **8** | 5 |
| test | concatenate | 48 | 40 | 8 | 7 | 0 | 10 |
| test | **synthesise** | 31 | 31 | **0** | 7 | **6** | 3 |

Totals: 87 sentences and 22 redundant before; 54 and 0 after; 8 and 6 conflicts.

**Redundancy goes to zero and the evidence does not move.** Gold coverage is identical: 13 of 13
development questions and 7 of 7 held out keep at least one gold section. The answer shrinks by 38%
on development and 35% on held out without losing a single one. This is the rare change that is
strictly better on both axes, and the paired comparison is 0 lost / 0 gained on coverage — which is
the point: the improvement is not in coverage, it is in redundancy and in what the answer refuses to
say twice.

**Fourteen conflicts are detected, six on held out, and twelve obsolete citations disappear with
them.** Eight detected conflicts on development, six on held out. Seventeen obsolete sentences
become five on development, ten become three on held out.

**Five survive, and the reason is the interesting part.** The remaining obsolete sentences come from
sub-questions with no current counterpart, so there is no pair to compare. Those are the ones stage
04 removes: its currency check does not need a counterpart, it just asks whether the document is
current. The two mechanisms are complementary, and neither is redundant:

| situation | removed by |
| --- | --- |
| old rule and new rule both present | stage 05, as a conflict |
| old rule alone | stage 04, as a stale citation |

**The writer was called once per question.** Not measured in the table because it is a structural
property, but `test_uses_exactly_one_model_call` fails the stage if it ever stops being true.

## Field notes

**Cognition, *Don't Build Multi-Agents* (June 2025).** cognition.ai/blog/dont-build-multi-agents
The second principle is that "actions carry implicit decisions, and conflicting decisions carry bad
results", illustrated with two subagents building a game whose art styles do not match because neither
could see the other's choices. Their conclusion is not that parallelism is bad, it is that work which
depends on a shared decision has to be done by one agent that can see the whole context.
**In this project.** Findings are the only thing that crosses the worker boundary, and the writer is
the only component that sees all of them. Not built: any mechanism for a worker to revise its finding
after seeing another's, which is the coordination protocol Cognition argues is not yet reliable.

**Anthropic, *How we built our multi-agent research system* (June 2025).**
anthropic.com/engineering/multi-agent-research-system
Their lead agent "synthesizes these results and decides whether more research is needed", then passes
"all findings to a CitationAgent". They also report the failure that motivates a single writer: early
agents "distracting each other with excessive updates".
**In this project.** `synthesise` is that synthesis step with the citation step taken out, because
stage 04 already owns verification. Not built: the decision to do *more* research after synthesis.
Our pipeline runs one round, which is the correct scope for a six-stage course and the wrong scope
for open-ended research.

## Do this

1. Read `src/scout/synth.py`. `Candidate`, `Conflict`, `Answer` and `concatenate` are given.
2. Implement `candidates` and `deduplicate`.
3. Implement `find_conflicts`: pair by document supersession *and* sub-question.
4. Implement `synthesise`: one `task="merge"` call after the deterministic steps.
5. Run the tests, then the report, then `--show-errors 1` to read the conflicts.

```sh
python stages/05_synthesis/test_stage05.py
IMPL=reference python evals/report_synthesis.py --show-errors 1
```

## Check yourself

Expected: 16 tests pass. Redundancy is zero. Gold coverage is 13 and 7, unchanged from
concatenation. Eight and six conflicts, and the leftover obsolete counts are 5 and 3.

If `test_uses_exactly_one_model_call` fails, you are calling the model inside a loop. Move the
per-candidate decisions into the deterministic steps before the call.

If the conflict count is much higher than 8, you dropped the same-sub-question condition and are
flagging every caching question.

If gold coverage falls, the cap is too small or you are dropping the current side by mistake. The
kept side is the one whose document is *not* listed as obsoleted.

## If you are stuck

**Hint 1.** `documents[section.document].obsoleted_by` gives either `None` or the id of the
replacement. Build a `{old: new}` map once and the pairing is a lookup.

**Hint 2.** Mark dropped indices in a set while iterating, then filter at the end. Removing from the
list while looping over it is how the current side gets dropped by accident.

**Hint 3.** The model call receives only the clean candidates. If you pass it everything and filter
afterwards, the writer has already seen both sides of a conflict, and the count of model calls stays
at one while the answer still contradicts itself.

## What a senior would notice

**That redundancy is the cheap half and conflicts are the expensive half.** Deduplication is
fingerprinting; anyone can do it. Deciding which of two incompatible claims to keep requires knowing
which document supersedes which, and that relation is not in the text. It has to be carried
deliberately, and this corpus only has it because `SOURCES.json` records it.

**That the answer got shorter and better.** A 38% reduction with identical evidence is what a senior
looks for first, because it usually means someone finally removed the repetition.

**That the limitation is stated where the technique is introduced.** "Detects supersession, not
contradiction" is in the docstring of the function, not in a footnote. A reader who builds on this
will know what it cannot do before they find out the hard way.
