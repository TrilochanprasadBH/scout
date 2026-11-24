# Stage 01 — Planning and decomposition

```sh
python stages/01_plan/test_stage01.py
```

Eighteen tests. Fifteen fail on the stub.

---

## What you will build

`plan()`: one research question in, an ordered list of validated sub-questions out, plus the
rule that divides a fixed evidence budget between them.

## Why this step is next

A research question is not a search query. "How does a client send an OAuth access token,
and which header field carries it?" needs one section of RFC 6750 and one section of RFC
9110, and a single query returns one ranked list that is mostly about the first half.

`ragkit` measured what one query can do on a well-formed corpus: 87.5% recall@5 for a hybrid
retriever against 83.3% for lexical. That is a number for *finding a passage that answers a
query*. This project asks questions that have two or three answers in different documents,
so the unit of work changes from "a query" to "a plan".

Everything downstream consumes the plan: stage 02 executes it, stage 03 prices it, stage 06
traces it. A plan that is a list of strings cannot be any of those things, because there is
nothing to validate, price, or attach a result to.

## The idea

**A facet is one thing that has to be true for the question to be answered.** "What is the
difference between a safe method and an idempotent method?" has two: what safe means, and
what idempotent means. A plan is good when executing it reaches the evidence for every
facet. It is affordable when it does that without spending more than the budget.

Three decisions, and only the third is really about the model:

**The model proposes.** Ask it for sub-questions; it will split on the words it recognises.
Our scripted stand-in splits on `and`, `versus` and `;`, which means it finds explicit
coordination and misses implicit facets entirely. Its second weakness is structural: asked
"which header field carries it?", it returns that clause as a sub-question, even though the
clause is scaffolding rather than a search.

**The harness validates.** Four operations the model cannot do, because they are properties
of the search and not of the language:

| operation | why |
| --- | --- |
| drop candidates with fewer than two content terms | `which header field carries it` is not a query |
| drop duplicate queries | two identical searches cost two budgets and return one answer |
| keep the whole question as the first step | decomposition loses single-facet questions; this is the insurance |
| cap at 4 and split the budget | a plan is an allocation, and an allocation needs a ceiling |

**The budget is the interesting part.** The evidence budget `B` is a number of *passages*,
and `budget_share` divides it:

```
passages(sub-question i) = floor(B / n) + (1 if i <= B mod n else 0)
```

so four sub-questions against twenty passages get five each. This is where decomposition
stops being free. One query with `k = 20` sees a section ranked twentieth. Four queries with
`k = 5` each see only their own top five, and a section that would have ranked sixth for
every one of them is found by nobody. **Splitting a budget raises recall only when the
facets live far apart in the ranking; when they are adjacent it just tightens four cut-offs.**

That gives the one comparison worth making, and it is the comparison this stage reports:
same twenty passages, two ways of spending them. The plan is also measured at full depth
(`k = 20` per sub-question), which is what a real system would do, and the searches column is
the price.

## The measurement

Development split, 13 answerable questions; held-out split, 7. `facet` is the mean fraction
of facets reached. `full` counts questions where every facet was reached, with a 95% Wilson
interval. `searches` is per question.

| split | configuration | facet | full | 95% CI | searches |
| --- | --- | --- | --- | --- | --- |
| dev | one query, k=20 | 0.808 | 9/13 | 42%–87% | 1.0 |
| dev | plan, equal passages | **0.885** | **11/13** | 58%–96% | 2.4 |
| dev | plan, full depth | 0.923 | 11/13 | 58%–96% | 2.4 |
| test | one query, k=20 | 0.857 | 6/7 | 49%–97% | 1.0 |
| test | plan, equal passages | **1.000** | **7/7** | 65%–100% | 2.4 |
| test | plan, full depth | 1.000 | 7/7 | 65%–100% | 2.4 |

Paired, on "every facet reached": development 2 questions won by the plan, 0 lost, 9 tied,
**p = 0.50**. Held out: 1 won, 0 lost, 6 tied, p = 1.00.

**Those p-values are not a formality.** With 13 pairs, exact McNemar cannot reach `p < 0.05`
until six discordant pairs all point the same way — `stats.discordant_needed(13)` returns 6.
Two is not evidence; it is a direction. The held-out split is one question out of seven, which
is the entire statistical content of the 1.000. `ragkit` stage 07 makes the same point about
22 questions; this project makes it with seven.

**The negative result.** The obvious third idea was a "rare-term anchor": add a query made of
the question's rarest content term, on the theory that a rare word is the one the answer must
contain. Measured, it cost a search per question and lost coverage:

| configuration | dev facet | full | searches |
| --- | --- | --- | --- |
| plan, no anchor | 0.885 | 11/13 | 2.4 |
| plan, with anchor | 0.846 | 10/13 | 3.4 |

The reason is visible in the failures: the rarest term in a question is usually a verb from
the question's phrasing (`carries`, `tell`), not a word the document is organised around.
`TestNegativeResult` fails if anyone turns the anchor back on without re-measuring.

**What the plan still cannot do.** `q03` fails completely: neither arm retrieves RFC 6750 §2.1
or RFC 9110 §11.6.2, because the question never says "Authorization" and both sections are
about it. No amount of decomposition fixes a vocabulary gap. That is a retrieval problem, and
the honest fix is a different retriever, not a better plan.

## Field notes

**Anthropic, *How we built our multi-agent research system* (June 2025).**
anthropic.com/engineering/multi-agent-research-system
Their Research feature is an orchestrator-worker system: a lead agent plans, spawns subagents
that search in parallel, then synthesises. They report a multi-agent configuration beating a
single agent by **90.2%** on their internal research eval, and explain why with a number that
matters more than the first one: **token usage alone explained 80% of the variance** on
BrowseComp, with tool-call count and model choice making up the other 15%. Multi-agent
systems use about **15×** the tokens of a chat. They also publish effort guidance — one agent
and 3–10 tool calls for simple fact-finding, 2–4 subagents and 10–15 calls each for direct
comparisons — and an early failure mode: agents spawning 50 subagents for a simple query.
**In this project.** Stage 01's `MAX_PARTS = 4` is that effort-scaling rule made concrete,
and `evals/report_plan.py` prints the searches column so the 2.4× is visible rather than
implied. Not built: real parallel subagents, and any claim about a 90% gain, because the
model here is scripted.

**Cognition, *Don't Build Multi-Agents* (June 2025).** cognition.ai/blog/dont-build-multi-agents
Two principles: *share context and full agent traces, not individual messages*, and *actions
carry implicit decisions, so conflicting decisions produce bad results*. Their example of the
architecture that does work is Claude Code, whose subagents "answer a question" and never
write code, so the only thing crossing the boundary is an answer.
**In this project.** Stage 01 plans; it never writes. Stage 02 will fan sub-agents out to read
and report, and stage 05 will have exactly one writer. Not built: any agent-to-agent
dialogue, which is the case Cognition argues against.

## Do this

1. Read `src/scout/plan.py`. The dataclasses, `prefixes`, `describe` and `as_dict` are given.
2. Implement `plan`. Ask the model with `task="plan"`, then apply the four harness operations.
3. Implement `budget_share`, including the remainder rule.
4. Implement `validate`: return a list of problems, empty when the plan is usable.
5. Run the tests, then the report, then the ablation.

```sh
python stages/01_plan/test_stage01.py
IMPL=reference python evals/report_plan.py
IMPL=reference python evals/report_plan.py --anchor
```

## Check yourself

Expected: 18 tests pass. The report reproduces the table above. `--anchor` reproduces the
negative result: coverage falls and searches rise.

If your plan is valid but coverage is below the baseline, you are almost certainly spending
the budget evenly on sub-questions that duplicate each other. Print `budget_share` and the
plan's queries before changing anything else.

If `validate` passes a plan with two identical queries, the deduplication compares the
readable question rather than the query string.

## If you are stuck

**Hint 1.** Build the plan in three passes: collect the model's candidates, filter them, then
number what survives. Trying to number while filtering is where the ids go wrong.

**Hint 2.** `budget_share` is `divmod`. The remainder goes to the earliest sub-questions
because the first one is the whole question, which is the safest place to spend a spare
passage.

**Hint 3.** `validate` returns a list, not a boolean, so the harness can print every reason at
once. Nothing in it should raise.

## What a senior would notice

**That the plan is a spend decision.** The interview question is not "can you decompose"; it
is "what does decomposition cost, and when do you refuse it". This stage has a table with the
answer at two budgets, and it includes the configuration where the answer is no.

**That the validation is the product.** A model's plan is an input. The code that decides
what reaches the search layer is the part that has to be right, and it is testable without a
model at all.

**That two facets out of thirteen is a direction.** The honest sentence is "0.808 to 0.885 on
development, 0.857 to 1.000 held out, 2 discordant questions, p = 0.50, and six would be
needed". Anyone who reports the second number without the first three is selling.
