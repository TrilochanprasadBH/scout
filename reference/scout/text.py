"""Text helpers, given so that every stage measures the same thing.

Four operations, each with a limitation stated where it is defined:

  `count`        approximate model tokens
  `terms`        index tokens
  `content_terms` the same, without the words that carry no meaning
  `sentences`    split prose into sentences

Nothing here stems, because stemming would make a quoted span stop matching the document
it was quoted from, and the whole citation check depends on exact text.
"""

from __future__ import annotations

import re

# The usual English function words. Short on purpose: a word belongs here if removing it
# cannot change which section answers a question.
STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before
    being below between both but by can cannot could did do does doing down during each few
    for from further had has have having he her here hers herself him himself his how i if
    in into is it its itself just me more most my myself no nor not now of off on once only
    or other ought our ours ourselves out over own same she should so some such than that
    the their theirs them themselves then there these they this those through to too under
    until up very was we were what when where which while who whom why will with would you
    your yours yourself yourselves
    """.split()
)

_WORD = re.compile(r"[a-z0-9]+")


def terms(text: str) -> list[str]:
    """Lowercase alphanumeric runs. `Content-Type` becomes `content` and `type`."""
    return _WORD.findall(text.lower())


def content_terms(text: str) -> list[str]:
    """Terms minus stopwords and one-character noise.

    No stemming: `cache` and `caching` stay distinct. BM25 copes with that through term
    frequency; a stemmer would help recall and would break exact-quote verification.
    """
    return [term for term in terms(text) if term not in STOPWORDS and len(term) > 1]


def count(text: str) -> int:
    """Approximate model tokens.

    One token per word plus one per punctuation mark. English prose lands near 1.2 tokens
    per word; a real word-piece tokeniser gives roughly 1.3. Good enough to make budget
    arithmetic concrete, wrong for a bill. Every budget number in this project is in this
    unit and the lessons say so.
    """
    return len(_WORD.findall(text.lower())) + len(re.findall(r"[^\w\s]", text))


def sentences(text: str) -> list[str]:
    """Split prose into sentences.

    Splits after `.`, `!` or `?` followed by whitespace. It therefore splits `e.g. this`
    and `Section 5.5. next` into two, which is wrong and harmless: the pieces are used to
    choose a quotable claim, and an over-short quote is still a real quote. The citation
    check never uses this function, it looks for the quote in the document text.
    """
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [part.strip() for part in parts if part.strip()]


def normalise(text: str) -> str:
    """Lowercase, collapse whitespace. The comparison form for quoted spans."""
    return " ".join(text.lower().split())


def fingerprint(text: str) -> str:
    """Comparison form for "is this the same sentence".

    Normalised, with trailing punctuation removed, so `The cache is fresh.` and
    `the cache is fresh` are the same claim. Used to deduplicate findings, where the same
    sentence arrives from two workers with different capitalisation far more often than a
    genuinely different sentence does.
    """
    return normalise(text).strip(" .!?,;:")


def overlap(left: str, right: str) -> float:
    """Jaccard overlap of content terms, in [0, 1].

    Used to ask "does this sentence talk about the same thing as this claim". Symmetric,
    which is wrong for entailment: a sentence can support a claim without covering it. The
    lessons use it as a cheap screen and say what it misses.
    """
    a = set(content_terms(left))
    b = set(content_terms(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def shared(left: str, right: str) -> int:
    """How many distinct content terms two strings have in common."""
    return len(set(content_terms(left)) & set(content_terms(right)))
