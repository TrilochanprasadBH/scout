# The corpus

Eight RFCs, 1.1 MB cleaned, 792 sections. This is what `scout` searches.

| document | topic | why it is here |
| --- | --- | --- |
| RFC 9110 | HTTP Semantics | the largest document; questions need several sections of it |
| RFC 9111 | HTTP Caching | pairs with 9110 on any caching question |
| RFC 7234 | HTTP/1.1 Caching | **obsoleted by RFC 9111** — the stale source |
| RFC 8446 | TLS 1.3 | long, deeply nested sections; handshake and resumption |
| RFC 6749 | OAuth 2.0 | access tokens, grants |
| RFC 6750 | OAuth 2.0 Bearer Tokens | pairs with 6749 |
| RFC 7519 | JWT | self-contained tokens; tension with 6749's opaque-token model |
| RFC 8259 | JSON | small, precise; the easy end of the scale |

Two pairs do work that a single-document corpus cannot:

- **9111 and 7234** describe the same caching rules, and 9111 **removed** the `Warning`
  header that 7234 required. A question about warnings has a correct answer in one document
  and an obsolete one in the other. Nothing was planted; this is what the specs say.
- **6749 and 7519** pull in opposite directions on what an access token should be: 6749
  describes a token the client treats as opaque, 7519 defines a self-contained token that
  the client can read. A synthesis has to hold both, not pick one.

## How it was built

```sh
python scripts/fetch_corpus.py --download   # originals into corpus/raw/ (not committed)
python scripts/fetch_corpus.py              # clean corpus/raw/ into corpus/rfc/
```

`corpus/raw/` is 1.4 MB of page furniture and is gitignored. What is committed is the cleaned
text, so a clone runs with no network. `corpus/SOURCES.json` records the URL, the published
date, the obsoleted-by relation, the section headings found in each file, and a SHA-256 of
both the original and the cleaned bytes.

## Limitation

These are specifications. They are unusually well structured: numbered sections, one topic
per section, consistent vocabulary. Citation extraction over them is easier than over a news
article, a PDF report, or a wiki, and the numbers in stages 04 and 05 should be read with that
in mind. The corpus is also a sample: it contains HTTP, TLS and OAuth, so a question about,
say, DNS is unanswerable here for a reason that has nothing to do with retrieval quality.
