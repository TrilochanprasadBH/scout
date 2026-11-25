# Stage 03 — Budget control

```sh
python stages/03_budget/test_stage03.py
```

18 tests. Run them before writing code: the failures are the contract.

---

## What you will build

`Budget`: a token ceiling with a reservation and a ledger that cannot go negative.
`plan_budget`: which sub-questions run and how many sections each may open. `run_budgeted`: the
whole execution under that ceiling, with the writer's share protected.

## Why this step is next

Stage 02 ran 2.4 workers per question and the largest single prompt was 27664 tokens. Nothing
stopped it. A research question with eight sub-questions over long documents is not 27k, it is
200k, and at that size an unbounded loop is a bill with no ceiling and a latency that nobody
measured.

The number from stage 02 that makes this urgent is not the coverage. It is that the whole
fan-out spent 17147 tokens to produce roughly six sentences. There is no waste to trim there;
there is only a ceiling to set.

## The idea

**Reserve first, in code.** The writer is the step that turns findings into an answer. A run
that spends everything on reading and cannot afford to write has produced notes. So:

```
reserve = ceil(total * 0.35)
available = total - spent - reserved
```

and `reserve` raises rather than quietly taking the reservation out of work already promised.

**Admit whole units.** A sub-question is the unit of work, and it is either in or out:

```
unit   = reads * mean_section_tokens + max_reply
accept = plan.sub_questions[: available // unit]
```

`available // unit` is why the ledger is a ceiling and not a target. At a 3000-token ceiling
the run spent 1632: the next whole sub-question did not fit, and the system refused to spend
the remainder on a partial one. That is the correct behaviour and it looks like waste until you
try the alternative.

**Enforce at the point of spend.** `BudgetedTools.open` charges `count(text)` before returning
it. A worker that cannot afford the next section stops, keeps what it read, and is listed in
`trimmed`. The prompt does not say "be brief"; the tool returns nothing.

**Degrade in one order.** Try four reads per worker, then two, then one. If a sub-question still
does not fit at one read, drop it and record it in `dropped`. If nothing fits, return no answer
and a reason. What is never done is truncating a sentence: a claim cut in half with a citation
attached is worse than no claim, because the citation still points somewhere.

**Why the reservation ratio is 35%.** It is a guess, and it is stated as one. The scripted
writer produces at most three sentences, so its real cost is a few hundred tokens and 35% is
generous. A writer that drafts a paragraph per finding would need more. The ratio is a policy
knob, and the report shows what happens at four different totals rather than defending one.

## The measurement

Dev 13 answerable questions, held out 7. `cited` is the fraction of gold sections present in the
final answer. `spend` and `over` are tokens per question.

| split | budget | arm | spend | over | cited | dropped | trimmed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 3000 | no budget | 8107 | 5176 | 58% | 0 | 0 |
| dev | 3000 | **budgeted** | 1632 | **0** | 46% | 18 | 1 |
| dev | 6000 | no budget | 8107 | 2887 | 58% | 0 | 0 |
| dev | 6000 | **budgeted** | 2,807 | **0** | 50% | 9 | 1 |
| dev | 12000 | no budget | 8107 | 177 | 58% | 0 | 0 |
| dev | 12000 | **budgeted** | 4177 | **0** | 58% | 0 | 0 |
| test | 3000 | no budget | 10051 | 7182 | 71% | 0 | 0 |
| test | 3000 | **budgeted** | 1517 | **0** | 50% | 10 | 2 |
| test | 12000 | no budget | 10051 | 1237 | 71% | 0 | 0 |
| test | 12000 | **budgeted** | 4846 | **0** | 71% | 0 | 1 |

Three readings, in order of how much they matter.

**At a workable ceiling the answer does not change and the bill halves.** Development, 12000
tokens: 58% cited either way, 4177 spent against 8107. Held out: 71% either way, 4846 against
10051. The budgeted arm reaches the same answer for 52% and 48% of the cost.

**Without enforcement the stated budget is fiction.** At 3000 tokens the uncontrolled arm spent
8107 on development — 172% over — and 10051 on held out, 235% over. It was not that the prompt
was ignored; there was no prompt. Execution had no ceiling, and the "budget" existed only in the
report's column header.

**Below the work, enforcement costs coverage, and that is the honest trade.** At 3000 tokens
development falls from 58% to 46% and held out from 71% to 50%. Eighteen sub-questions were
dropped on development. The system knows this and says so; the uncontrolled arm lost the same
evidence silently by cutting the answer's tail.

Paired at every ceiling: 0 questions won by the budgeted arm and 1 lost at 3000 and 6000,
0 and 0 at 12000 and 24000, `p = 1.00` throughout. That is what "no difference at a workable
budget" looks like when the sample is 13 questions: the effect being claimed is a cost
reduction, not a quality gain, and the quality column is there to show it did not regress.

## Field notes

**Anthropic, *How we built our multi-agent research system* (June 2025).**
anthropic.com/engineering/multi-agent-research-system
Their research agents use about **4×** the tokens of chat and the multi-agent configuration about
**15×**, and they say plainly that "multi-agent systems require tasks where the value of the task
is high enough to pay for the increased performance". They also publish effort rules — "simple
fact-finding requires just 1 agent with 3-10 tool calls, direct comparisons might need 2-4
subagents with 10-15 calls each" — and list their early failure modes: "spawning 50 subagents for
simple queries", "scouring the web endlessly for nonexistent sources", and agents "continuing when
they already had sufficient results".
**In this project.** Those effort rules are the reason `plan_budget` scales the number of workers
to the ceiling instead of always running the plan, and the reason a dropped sub-question is
reported rather than hidden. Not built: a learned estimate of how much work a question deserves.
The unit estimate here is `reads × mean section size`, which is a property of the corpus, not of
the question.

**Cognition, *Don't Build Multi-Agents* (June 2025).** cognition.ai/blog/dont-build-multi-agents
Argues that context is the resource to engineer, and that a single-threaded agent with good context
management is more reliable than a coordination protocol. The relevant part here is that context
is finite and *shared*: every token one part of the system spends is a token another part cannot
use.
**In this project.** The reservation is that principle applied to a pool instead of a window: the
writer's share is taken before reading starts, because otherwise the reader will always win.
Not built: any compression of what is read. A worker keeps whole sections, which is why its unit
estimate is coarse.

## Do this

1. Read `src/scout/budget.py`. `Admission`, `BudgetRun`, `BudgetExhausted` and the constants are
   given.
2. Implement `Budget`. Four properties and two methods; none of them should raise on a zero total.
3. Implement `plan_budget` with the read-step degradation.
4. Implement `BudgetedTools.open`: charge, or raise and change nothing.
5. Implement `run_budgeted`, including the writer call capped at `writer_allowance`.
6. Run the tests, then the sweep.

```sh
python stages/03_budget/test_stage03.py
IMPL=reference python evals/report_budget.py --split dev
IMPL=reference python evals/report_budget.py --sweep 2000 4000 8000 16000
```

## Check yourself

Expected: 18 tests pass. The dev table reproduces the rows above. The sweep shows spend rising
with the ceiling and `over` staying at zero for the budgeted arm.

If `test_never_overruns_at_any_budget` fails, something is spending after a refused charge.
`Budget.spend` must change nothing when it returns False.

If the budgeted arm has better coverage than the uncontrolled one at a small ceiling, you are
probably still running all sub-questions and letting the writer truncate. Check `dropped`: at
3000 it should be non-zero.

If `spend` is much lower than the ceiling at every budget, the admission unit is too coarse.
That is the trade this stage makes on purpose, and it is worth being able to state it.

## If you are stuck

**Hint 1.** Write `Budget` first and test it with three numbers in a shell. `available`,
`writer_allowance` and `overrun` are one-liners; get them right before touching the runner.

**Hint 2.** `plan_budget` is a loop over `read_steps` that returns on the first step where
`available // unit >= 1`. The fall-through case, where nothing fits, is not an exception.

**Hint 3.** The writer call happens after the workers, so it must use `writer_allowance`, not
`available`. Using `available` gives the writer nothing, because the reservation is exactly the
part that `available` excludes.

## What a senior would notice

**That the ledger is the product.** The interesting code here is nine lines of arithmetic. The
interesting engineering is choosing the unit of admission and the order of degradation, and being
able to say what happens at a ceiling below the work.

**That the comparison is a cost claim, not a quality claim.** The table says the same answer for
half the tokens. It does not say the answers got better, and anyone reading it that way should
look at the coverage column, which is flat or worse.

**That nobody has measured the reservation ratio.** 35% is a policy choice. The honest sentence is
"the scripted writer needs a few hundred tokens, we reserved 35% for headroom, and a different
writer would move this number". A project that hides that sentence is inviting someone to copy the
constant into a system where it is wrong.
