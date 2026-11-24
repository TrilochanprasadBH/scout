# Stage 02 — Read-only sub-agents

```sh
python stages/02_subagents/test_stage02.py
```

Nineteen tests. Fourteen fail on the stub.

---

## What you will build

`run_subagent`: one sub-question, one worker, a search, a few opens, one answer with the
sections it came from. `run_all`: every sub-question executed in isolation, with findings
returned in plan order whatever order they finished in.

## Why this step is next

Stage 01 produced 2.4 sub-questions per question and no way to execute one. The obvious
implementation is a loop that appends to a shared list. That implementation is the source of
two bugs that are expensive to find later:

- **Shared read state.** Worker 3's search skips a section because worker 1 opened it. Nothing
  errors; the evidence just quietly differs between runs.
- **Completion order leaking into the output.** The list is appended as calls finish, so the
  finding order depends on scheduling. Stage 05 then writes a synthesis that begins with a
  different fact on every run, and stage 06 cannot tell a regression from a reshuffle.

The stage fixes both by construction rather than by care.

## The idea

**The tool surface is the security boundary.** A worker gets `ReadOnlyTools`: `search` and
`open`, and nothing else. There is no `write`, no scratchpad, no reference to the index. That
is not politeness; it is what makes the worker's behaviour a pure function of its
sub-question.

```python
tools = ReadOnlyTools(index)        # one per worker, not one per run
text  = tools.open(section_id)      # records the read, returns the text
```

**Attribution is a structural property, not a formatting choice.** Every `Sentence` carries
the section id it was extracted from, and the test `every_sentence_was_actually_read` asserts
that the cited section is in that worker's read set. A worker that cites a section it never
opened is caught at the boundary, before stage 04 has to reason about it.

**Order independence needs a test, not a comment.** No threads are used, so `run_all` takes a
`schedule`: a permutation of sub-question ids that says which worker "finished" first. The
return is always sorted by id. The test runs the same plan forwards and backwards and compares
the findings object by object. A shuffled list cannot pass.

**What is deliberately absent.** No retries, no cancellation, no rate limiting, no parallel
execution. Each is a real requirement in production and each has its own failure modes; none
of them can be measured until there is a budget to enforce, which is stage 03.

## The measurement

Dev 13 answerable questions, held out 7. Reads are held constant: the single-context arm reads
20 passages in one call, and each worker gets `20 / n` so the fan-out reads about 20 in total.
`cite` is the fraction of produced sentences whose cited section is one of the question's gold
sections.

| split | configuration | facet | full | 95% CI | cite | tokens | max prompt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | single context | 0.538 | 4/13 | 13%–58% | 26% | 20027 | 27664 |
| dev | **fan-out** | **0.654** | **8/13** | 36%–82% | 24% | 17147 | 24427 |
| test | single context | 0.214 | 1/7 | 3%–51% | 10% | 25788 | 31269 |
| test | **fan-out** | **0.571** | **3/7** | 16%–75% | 23% | 22565 | 28461 |

Paired, on "every facet reached": development **4 won, 0 lost**, `p = 0.12`; held out
**2 won, 0 lost**, `p = 0.50`. Six discordant pairs are needed for `p < 0.05` at this sample
size, so the direction is consistent on both splits and the evidence is still thin. The held
out result is the more interesting one: 1/7 to 3/7 on seven questions is a large effect sitting
inside a wide interval.

Three things in that table are worth more than the coverage gain.

**Fan-out did not cost more.** 17147 tokens against 20027 on development. That is not a
general law and the lesson should not be sold as one: a worker asked for 8 passages often gets
5, because the query only has that many positive-scoring sections. On a corpus where every
query returned a full complement, the fan-out would read more, not less. The honest reading is
*no measurable penalty at this size*, not *fan-out is cheaper*.

**Precision did not improve.** 24% against 26% on development. More workers produced more
sentences, and a sentence extracted from a worker's narrow context is not automatically a
better claim. Precision is stage 04's number to move, and it will move by rejecting claims,
not by producing fewer of them.

**The largest single prompt fell from 27664 to 24427 tokens, which is less than expected.**
One section of RFC 9110 can be 5,000 tokens on its own, so 8 sections and 20 sections are not
as far apart as the counts suggest. Context isolation is real, and it is bounded by the
coarseness of the unit being isolated: sections, not paragraphs.

**The failure that is still here.** Neither arm refuses the unanswerable questions: 0 of 2
correct refusals on development, 1 of 2 on held out. Asked about DNS zone transfers, the
scripted model finds sections that share a word and answers from them. That is a citation
problem, and it is left deliberately in place for stage 04 to measure and fix.

## Field notes

**Cognition, *Don't Build Multi-Agents* (June 2025).** cognition.ai/blog/dont-build-multi-agents
The two principles: *share context and full agent traces, not individual messages*, and
*actions carry implicit decisions, so conflicting decisions produce bad results*. Their worked
example of an architecture that survives is Claude Code, whose subagents "are usually only
tasked with answering a question, not writing any code", and which "never does work in
parallel with the subtask agent". The reason given is exactly this stage's design: a subagent
without the main agent's context can safely answer a well-scoped question, and cannot safely
make a decision that another agent depends on.
**In this project.** `ReadOnlyTools` is that restriction in code, and `run_all`'s sorted
return is the second principle made mechanical. Not built: shared traces between workers.
Each worker's reads are private and the orchestrator never shows one worker another's evidence,
which is a limitation as well as a safeguard — stage 05 has to reconstruct the joint picture
from findings alone.

**Anthropic, *How we built our multi-agent research system* (June 2025).**
anthropic.com/engineering/multi-agent-research-system
Reports subagents operating "in parallel with their own context windows", each returning
condensed findings to a lead agent, and describes the lead agent delegating with "an
objective, an output format, guidance on the tools and sources to use, and clear task
boundaries". Without that detail, subagents "duplicate work, leave gaps, or fail to find
necessary information".
**In this project.** The `SubQuestion` dataclass carries the objective (`question`) and the
tool input (`query`), which is the minimum of that brief. Not built: an output format per
worker beyond "sentences with sections", and no steering between workers, which their
synchronous design also lacks.

## Do this

1. Read `src/scout/subagent.py`. `Read`, `Sentence`, `Finding`, `coverage` and
   `total_tokens` are given.
2. Implement `ReadOnlyTools.open` so it records the read and its token cost.
3. Implement `run_subagent`: search, open, one `task="answer"` call, wrap the sentences.
4. Implement `run_all`: fresh tools per worker, honour `schedule`, sort the result.
5. Run the tests, then the report.

```sh
python stages/02_subagents/test_stage02.py
IMPL=reference python evals/report_subagents.py --show-errors 1
```

## Check yourself

Expected: 19 tests pass. The report reproduces the table above, including the row where
precision gets slightly worse.

If `every_sentence_was_actually_read` fails, you are trusting the model's `section` field
without checking it against `tools.read_sections`. The model is allowed to name a section it
was not given; the harness is not allowed to pass it on.

If `reverse_schedule_gives_the_same_result` fails, findings are being appended in execution
order. Sort by `sub_question` at the end, not in the middle.

## If you are stuck

**Hint 1.** `run_subagent` is four steps and the third one is a single model call. Write the
passages list first and print it; if it is empty, the search is the problem, not the model.

**Hint 2.** `schedule` only changes the order of the loop. Everything else, including the sort,
happens after it.

**Hint 3.** `Finding.tokens` is `tools.read_tokens + reply.tokens`, and `prompt_tokens` is
`reply.tokens_in`. Keeping them separate is what lets the report distinguish "this run read a
lot" from "one call carried a lot".

## What a senior would notice

**That the sub-agent boundary is a type, not a convention.** The argument for read-only
workers is not that workers are untrustworthy. It is that a shared mutable surface makes
ordering observable, and an observable ordering makes every later number unstable.

**That the fan-out won without a parallel executor.** The gain here comes from narrower
contexts and more independent output slots, not from concurrency. Adding threads to this
design would change the wall clock and nothing in the table, which is the correct thing to say
before someone spends a week on an async runtime.

**That one arm answered two questions it could not answer.** A result table that reports
coverage and not false answers invites the reader to conclude that the system works. The
refusal column is the one that says how it fails.
