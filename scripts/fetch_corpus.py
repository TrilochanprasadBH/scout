#!/usr/bin/env python3
"""Rebuild `corpus/rfc/` from the published RFC text.

    python scripts/fetch_corpus.py --download   # fetch the originals into corpus/raw/
    python scripts/fetch_corpus.py              # clean corpus/raw/ into corpus/rfc/

`corpus/raw/` is not committed: it is 1.4 MB of page-furniture and duplicated running
headers. What is committed is the cleaned text, so a clone is still self-contained and the
default run never touches the network.

The cleaning is deliberately blunt. It removes four things and changes nothing else:

  1. page footers, `Bauer                  Standards Track                    [Page 7]`
  2. running page headers, `RFC 9110                          HTTP Semantics`
  3. the form feed that separated pages
  4. the front matter (the IETF header block) and the table of contents

Everything from the Abstract onwards survives, including the reference lists and the
authors' addresses. Those are noise for retrieval, and removing them would make the corpus
a summary rather than a document.

The three-space body indent is removed so that a quoted span is the sentence itself. No
line is re-wrapped and no word is changed, which is what makes a citation span verifiable:
`check_labels.py` can look for the exact phrase in the exact section.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "corpus" / "raw"
OUT = ROOT / "corpus" / "rfc"

# One entry per document. `obsoleted_by` is what makes a stale citation detectable: a
# question about caching can be answered from RFC 7234 or RFC 9111, and only one of them is
# current. That is a real source conflict, not a planted one.
MANIFEST = (
    {
        "id": "rfc9110",
        "number": 9110,
        "title": "HTTP Semantics",
        "published": "2022-06",
        "obsoletes": "2818, 7230, 7231, 7232, 7233, 7235",
        "obsoleted_by": None,
        "topic": "HTTP request and response semantics",
    },
    {
        "id": "rfc9111",
        "number": 9111,
        "title": "HTTP Caching",
        "published": "2022-06",
        "obsoletes": "7234",
        "obsoleted_by": None,
        "topic": "HTTP caches, freshness, validation",
    },
    {
        "id": "rfc7234",
        "number": 7234,
        "title": "Hypertext Transfer Protocol (HTTP/1.1): Caching",
        "published": "2014-06",
        "obsoletes": "2616",
        "obsoleted_by": "rfc9111",
        "topic": "older HTTP caching rules, superseded",
    },
    {
        "id": "rfc8446",
        "number": 8446,
        "title": "The Transport Layer Security (TLS) Protocol Version 1.3",
        "published": "2018-08",
        "obsoletes": "5077, 5246, 6961",
        "obsoleted_by": None,
        "topic": "TLS 1.3 handshake, resumption, 0-RTT",
    },
    {
        "id": "rfc6749",
        "number": 6749,
        "title": "The OAuth 2.0 Authorization Framework",
        "published": "2012-10",
        "obsoletes": "5849",
        "obsoleted_by": None,
        "topic": "OAuth roles, grants, access tokens",
    },
    {
        "id": "rfc6750",
        "number": 6750,
        "title": "The OAuth 2.0 Authorization Framework: Bearer Token Usage",
        "published": "2012-10",
        "obsoletes": None,
        "obsoleted_by": None,
        "topic": "bearer tokens, scopes, transmission",
    },
    {
        "id": "rfc7519",
        "number": 7519,
        "title": "JSON Web Token (JWT)",
        "published": "2015-05",
        "obsoletes": None,
        "obsoleted_by": None,
        "topic": "JWT claims and validation",
    },
    {
        "id": "rfc8259",
        "number": 8259,
        "title": "The JavaScript Object Notation (JSON) Data Interchange Format",
        "published": "2017-12",
        "obsoletes": "7159",
        "obsoleted_by": None,
        "topic": "JSON grammar and interoperability",
    },
)

HEADER = re.compile(r"^RFC \d+\s")
FOOTER = re.compile(r"\[Page \d+\]\s*$")
HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s{2,}(\S.*)$")
TOC_LINE = re.compile(r"\.\s\.\s\.")


def clean(raw: str) -> str:
    """Turn one raw RFC into the text this project searches."""
    pages = raw.split("\f")
    lines: list[str] = []
    for page in pages:
        for line in page.splitlines():
            if HEADER.match(line):
                continue  # running header
            if FOOTER.search(line):
                continue  # page footer
            lines.append(line.rstrip())

    start = next((i for i, line in enumerate(lines) if line.strip() == "Abstract"), None)
    if start is None:
        raise ValueError("no Abstract line: the layout changed, re-check the cleaner")
    lines = lines[start + 1:]

    # The table of contents is a second copy of every heading, and retrieval would happily
    # return the contents page instead of the section. Cut from the header to the first
    # heading at column zero; the contents entries are indented, so that heading is "1."
    toc = next((i for i, line in enumerate(lines) if line.strip() == "Table of Contents"), None)
    if toc is not None:
        end = next((i for i in range(toc + 1, len(lines)) if HEADING.match(lines[i])), None)
        if end is not None:
            lines = lines[:toc] + lines[end:]

    # Belt and braces: any entry that survived the cut still carries dot leaders.
    lines = [line for line in lines if not TOC_LINE.search(line)]

    out: list[str] = []
    for line in lines:
        if HEADING.match(line):
            # Mark headings explicitly. RFC body text contains numbered lists, and once the
            # three-space indent is removed a list item "3.  Base64url decode ..." is
            # indistinguishable from a section heading. The marker ends that ambiguity.
            out.append(f"## {line}")
        elif line.startswith("   "):
            out.append(line[3:])
        else:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def body_marker(entry: dict) -> str:
    """The heading line written at the top of every cleaned document."""
    return f"# RFC {entry['number']} — {entry['title']}"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    for entry in MANIFEST:
        target = RAW / f"{entry['id']}.txt"
        if target.exists():
            print(f"  have    {target.name}")
            continue
        url = f"https://www.rfc-editor.org/rfc/rfc{entry['number']}.txt"
        with urllib.request.urlopen(url, timeout=60) as response:
            target.write_bytes(response.read())
        print(f"  fetched {target.name} ({target.stat().st_size} bytes)")
    return 0


def build() -> int:
    missing = [e["id"] for e in MANIFEST if not (RAW / f"{e['id']}.txt").exists()]
    if missing:
        print(f"missing raw files: {', '.join(missing)}")
        print("run: python scripts/fetch_corpus.py --download")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    sources = []
    for entry in MANIFEST:
        raw_path = RAW / f"{entry['id']}.txt"
        cleaned = body_marker(entry) + "\n\n" + clean(raw_path.read_text(encoding="utf-8"))
        out_path = OUT / f"{entry['id']}.txt"
        out_path.write_text(cleaned, encoding="utf-8")

        headings = [line for line in cleaned.splitlines() if line.startswith("## ")]
        entry = dict(entry)
        entry.update(
            {
                "url": f"https://www.rfc-editor.org/rfc/rfc{entry['number']}.txt",
                "file": f"corpus/rfc/{entry['id']}.txt",
                "raw_sha256": sha256(raw_path),
                "clean_sha256": sha256(out_path),
                "cleaned_bytes": out_path.stat().st_size,
                "sections": headings,
            }
        )
        sources.append(entry)
        print(f"  built   {out_path.name:<14} {entry['cleaned_bytes']:>7} bytes  {len(headings):>4} headings")

    payload = {
        "licence": "IETF Trust Legal Provisions (BCP 78); RFC text reproduced verbatim",
        "cleaning": "scripts/fetch_corpus.py: page furniture, front matter and TOC removed",
        "documents": sources,
    }
    (ROOT / "corpus" / "SOURCES.json").write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    total = sum(e["cleaned_bytes"] for e in sources)
    print(f"\n  {len(sources)} documents, {total / 1024:.0f} KB cleaned")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="fetch the originals first")
    args = parser.parse_args()
    if args.download:
        return download()
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
