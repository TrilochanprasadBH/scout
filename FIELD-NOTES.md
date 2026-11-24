# Field notes

What published teams did, what it means for a research agent, and what we deliberately did not
build.

Same rules as `ragkit/FIELD-NOTES.md` and `triage/FIELD-NOTES.md`: cite only what was read, include
the results that argue against the technique, and end each entry with the omission.

---

## Multi-agent research

### 1. How Anthropic built their multi-agent research system — Anthropic, June 2025

**Source.** https://www.anthropic.com/engineering/multi-agent-research-system

**What they did.** Built the Research feature as an orchestrator-worker system: a lead agent plans,
spawns subagents that search in parallel with their own context windows, synthesises their findings,
and passes the result to a CitationAgent that identifies specific locations for citations. They
report a multi-agent configuration beating single-agent Claude Opus 4 by **90.2%** on an internal
research eval, and give the reason in numbers: on BrowseComp, **token usage alone explained 80% of
performance variance**, with tool-call count and model choice making up 95% jointly. They also
publish the cost — agents use about **4×** the tokens of chat, multi-agent about **15×** — and say
plainly that the architecture only pays on tasks valuable enough to cover it. Effort guidance:
simple fact-finding is one agent and 3–10 tool calls, direct comparisons 2–4 subagents with 10–15
calls each. Early failure modes they name: spawning 50 subagents for a simple query, agents
continuing when they already had enough, and agents distracting each other with status updates.

**What it means.** Multi-agent works by buying tokens, not by being cleverer per token. That makes
the budget a first-class component rather than an optimisation, and it makes "when do you refuse to
fan out" a real design question.

**In this project.** Stage 01's four-sub-question cap is their effort-scaling rule made concrete;
stage 03 reserves for the writer before any worker runs, because a run that cannot afford to write
has produced notes. Not built: real parallel subagents (stage 02 simulates completion order with a
`schedule` list), and any claim resembling 90.2%, because the model here is a deterministic stand-in.

### 2. Don't Build Multi-Agents — Cognition, 12 June 2025

**Source.** https://cognition.ai/blog/dont-build-multi-agents

**What they did.** Argued against parallel multi-agent architectures and stated two principles:
*share context and full agent traces, not individual messages*, and *actions carry implicit
decisions, so conflicting decisions produce bad results*. Their worked example: two subagents build
halves of a game and produce incompatible art styles because neither could see the other's choices.
They point at Claude Code as the architecture that survives — subagents "are usually only tasked with
answering a question, not writing any code", and it "never does work in parallel with the subtask
agent" — and conclude that the reliable default is single-threaded, with context compression when the
window overflows.

**What it means.** The boundary between workers should carry answers, not decisions. A worker that
only reads and reports is safe to run in parallel; a worker that writes into shared state is not,
because its effect depends on what another worker did first.

**In this project.** Stage 02 gives each worker `ReadOnlyTools` and nothing else, and returns
findings sorted by sub-question id so completion order cannot leak into the output. Stage 05 has
exactly one writer, and a test counts the model calls to prove it. Not built: shared context between
workers, which Cognition recommends and which would break the isolation stage 02 depends on. The
trace in stage 06 is the post-hoc substitute: findings are not shared during the run, but every
sentence can be traced afterwards.

---

## The corpus

### 3. RFC 9111 obsoletes RFC 7234 — IETF, June 2022

**Source.** https://www.rfc-editor.org/rfc/rfc9111 — Appendix B, "Changes from RFC 7234"

**What they did.** Replaced the 2014 HTTP caching specification and listed what changed. One entry:
"The Warning response header was obsoleted. Much of the information supported by Warning could be
gleaned by examining the response, and the remaining information — although potentially useful — was
entirely advisory. In practice, Warning was not added by caches or intermediaries." The invalidation
rule also changed: RFC 7234 required invalidating the URIs in `Location` and `Content-Location` after
an unsafe request, while RFC 9111 makes the target URI a MUST and those URIs a MAY.

**What it means.** A research corpus with a superseded document in it is not a flaw, it is the normal
state of a technical corpus. A 2014 answer about caching was correct when it was written and is wrong
now, and nothing inside the sentence says so. The supersession relation lives in the document
metadata, not in the prose.

**In this project.** `corpus/SOURCES.json` carries `obsoleted_by`, `corpus/rfc/` contains both
documents, and three golden questions have evidence spans marked `obsolete` that quote the old rule
in the same words as the new one. Stage 04 removes those citations mechanically; stage 05 resolves
them as conflicts when both sides appear in one answer. Not built: a general supersession graph.
Two documents is a relationship; a corpus of thousands needs a registry, and the IETF has one per
document, which is precisely the kind of metadata a real system would have to ingest.

---

## What we deliberately did not build

| technique | why not here | when you would |
| --- | --- | --- |
| a real model in the graded path | the repository must run offline with no key, and a keyed path makes every documented number move | when the eval set is large enough that model variance is smaller than the effect being measured |
| dense retrieval | needs a model call or a trained file; the project's subject is orchestration, not retrieval | when lexical recall is the bottleneck, which stage 01's `q03` failure shows it can be |
| contradiction detection between current sources | requires judging whether two statements conflict, which is a model judgment | with a judge and a rubric, as `ragkit` stage 07 does for answers |
| retry and re-planning | one round keeps the pipeline auditable and the comparison clean | when a single round's coverage is the binding constraint |
| asynchronous execution | determinism is worth more than wall clock at this size, and `schedule` tests the property that matters | when latency is a product requirement, and then the trace has to be tested under real concurrency |
| a learned effort estimate per question | the admission unit is `reads × mean section size`, which is a property of the corpus | when question difficulty varies enough that a fixed cap wastes budget |
