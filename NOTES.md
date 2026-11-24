# Notes

Three lines per stage. What I expected, what the measurement said, what I changed.

---

## 01 — Planning

Expected decomposition to be the easy win. Measured: 0.808 → 0.885 on development, 0.857 → 1.000
held out, for 2.4× the searches and `p = 0.50`.
The rare-term anchor lost coverage and cost a search, so it is off by default and a test guards it.

## 02 — Sub-agents

Expected fan-out to be expensive. Measured: same tokens, better coverage, more sentences.
Expected isolation to be a purity argument. Measured: it is what makes the output order-independent,
which a reversed schedule test now proves.

## 03 — Budget

Expected the ceiling to cost coverage. Measured: at 12,000 tokens it costs nothing and halves the
spend; below the work it costs 12 points and drops 18 sub-questions.
The ledger is a ceiling, not a target: at 3,000 it used 1,632 because the next whole unit did not fit.

## 04 — Citations

Expected verification to raise precision a lot. Measured: 15% → 25% on development, 22% on held out.
The decisive number was the stale count: 16 → 0, mechanically, by construction.
The four unanswerable questions still get answers; relevance is not answerability.

## 05 — Synthesis

Expected deduplication to be the whole stage. Measured: it removes 22 redundant sentences out of 87
and changes gold coverage not at all.
The conflict rule needed the same-sub-question condition, or every caching question conflicted with
itself.

## 06 — Tracing

Expected a log to be enough. Measured: a flat log answers "what was said" and nothing else.
The `sub_question` attribute on each sentence span is the one that makes an incident review possible.
